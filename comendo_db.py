#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
comendo_db.py — banco de dados único dos clientes (substitui grupos.csv + contas_ads.csv).

Usado como MÓDULO (import comendo_db) pelo painel.py e relatorios_automacao.py,
e como CLI pelo slash command /relatorios-ads (que só sabe rodar `bash`):

    python3 comendo_db.py listar [--fluxo dashgoo|meta_ads] [--status OK] [--csv]
    python3 comendo_db.py pendentes [--fluxo dashgoo|meta_ads]

`--csv` imprime no formato antigo do CSV (cabeçalho + linhas), pra scripts/instruções
que já sabem parsear isso continuarem funcionando sem reescrever o parser.

Schema:
  clientes            — um cliente por linha, com o fluxo (dashgoo ou meta_ads),
                         dados de roteamento (gestor/instância/grupo) e os campos
                         de estilo de mensagem editáveis pelo gestor.
  mensagens_pendentes — rascunhos gerados em "modo revisão", esperando o gestor
                         editar/aprovar antes do envio real pelo painel.
"""

import os
import re
import csv
import sys
import json
import sqlite3
import unicodedata
import datetime

import config

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Caminho do SQLite: configurável via DB_PATH (env). Se não definido, usa
# clientes.db ao lado deste módulo, como sempre foi.
# NOTA: na migração pra nuvem, este arquivo ganha um backend Postgres quando
# config.DATABASE_URL estiver definida (ver README, Fase 2). Por ora, SQLite.
DB_PATH = config.DB_PATH or os.path.join(BASE_DIR, "clientes.db")

FLUXOS = ("dashgoo", "meta_ads")


def _agora():
    return datetime.datetime.now().isoformat(timespec="seconds")


def conectar():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def inicializar():
    """Cria as tabelas se não existirem. Idempotente — seguro chamar sempre."""
    con = conectar()
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS clientes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            gestor TEXT NOT NULL,
            instancia TEXT NOT NULL,
            grupo_nome TEXT NOT NULL,
            grupo_id TEXT NOT NULL,
            fluxo TEXT NOT NULL CHECK(fluxo IN ('dashgoo','meta_ads')),
            ad_account_id TEXT,
            status TEXT NOT NULL DEFAULT 'OK',
            saudacao_padrao TEXT,
            estilo_mensagem TEXT,
            criado_em TEXT NOT NULL,
            atualizado_em TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS gestores (
            instancia TEXT PRIMARY KEY,
            nome TEXT NOT NULL,
            numero TEXT,
            criado_em TEXT NOT NULL,
            atualizado_em TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS envios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente_id INTEGER NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
            periodo TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('enviado','erro','sem_trafego','descartado')),
            detalhe TEXT,
            criado_em TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_envios_cliente ON envios(cliente_id, criado_em);

        CREATE TABLE IF NOT EXISTS mensagens_pendentes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente_id INTEGER NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
            periodo TEXT NOT NULL,
            saudacao TEXT NOT NULL,
            metricas TEXT NOT NULL,
            conclusao TEXT,
            pdf_path TEXT,
            status TEXT NOT NULL DEFAULT 'pendente',
            criado_em TEXT NOT NULL,
            atualizado_em TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_clientes_fluxo ON clientes(fluxo);
        CREATE INDEX IF NOT EXISTS idx_pendentes_status ON mensagens_pendentes(status);
        """
    )
    con.commit()
    con.close()


# =====================================================================
# Clientes — CRUD
# =====================================================================

def _norm(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def listar_clientes(fluxo=None, status=None, gestor=None):
    con = conectar()
    q = "SELECT * FROM clientes"
    cond, args = [], []
    if fluxo:
        cond.append("fluxo = ?")
        args.append(fluxo)
    if status:
        cond.append("status = ?")
        args.append(status)
    if gestor:
        cond.append("gestor = ?")
        args.append(gestor)
    if cond:
        q += " WHERE " + " AND ".join(cond)
    q += " ORDER BY gestor COLLATE NOCASE, nome COLLATE NOCASE"
    linhas = [dict(r) for r in con.execute(q, args).fetchall()]
    con.close()
    return linhas


def buscar_cliente(id_):
    con = conectar()
    r = con.execute("SELECT * FROM clientes WHERE id = ?", (id_,)).fetchone()
    con.close()
    return dict(r) if r else None


def buscar_por_nome(nome, fluxo=None):
    """Match por substring normalizada (mesma lógica do antigo achar_grupo)."""
    nb = _norm(nome)
    if not nb:
        return None
    candidatos = [c for c in listar_clientes(fluxo=fluxo) if _norm(c["nome"]) and _norm(c["nome"]) in nb]
    if not candidatos:
        return None
    return max(candidatos, key=lambda c: len(_norm(c["nome"])))


def inserir_cliente(nome, gestor, instancia, grupo_nome, grupo_id, fluxo,
                     ad_account_id=None, status="OK", saudacao_padrao=None, estilo_mensagem=None):
    if fluxo not in FLUXOS:
        raise ValueError(f"fluxo inválido: {fluxo}")
    con = conectar()
    agora = _agora()
    cur = con.execute(
        """INSERT INTO clientes
           (nome, gestor, instancia, grupo_nome, grupo_id, fluxo, ad_account_id,
            status, saudacao_padrao, estilo_mensagem, criado_em, atualizado_em)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (nome, gestor, instancia, grupo_nome, grupo_id, fluxo, ad_account_id,
         status, saudacao_padrao, estilo_mensagem, agora, agora),
    )
    con.commit()
    novo_id = cur.lastrowid
    con.close()
    return novo_id


def atualizar_cliente(id_, **campos):
    permitidos = {"nome", "gestor", "instancia", "grupo_nome", "grupo_id", "fluxo",
                  "ad_account_id", "status", "saudacao_padrao", "estilo_mensagem"}
    campos = {k: v for k, v in campos.items() if k in permitidos}
    if not campos:
        return
    campos["atualizado_em"] = _agora()
    sets = ", ".join(f"{k} = ?" for k in campos)
    con = conectar()
    con.execute(f"UPDATE clientes SET {sets} WHERE id = ?", (*campos.values(), id_))
    con.commit()
    con.close()


def excluir_cliente(id_):
    con = conectar()
    con.execute("DELETE FROM clientes WHERE id = ?", (id_,))
    con.commit()
    con.close()


# =====================================================================
# Envios — histórico de status por cliente (enviado/erro/sem_trafego/descartado)
# =====================================================================

def registrar_envio(cliente_id, periodo, status, detalhe=None):
    if status not in ("enviado", "erro", "sem_trafego", "descartado"):
        raise ValueError(f"status inválido: {status}")
    con = conectar()
    con.execute(
        "INSERT INTO envios (cliente_id, periodo, status, detalhe, criado_em) VALUES (?,?,?,?,?)",
        (cliente_id, periodo, status, detalhe, _agora()),
    )
    con.commit()
    con.close()


def listar_ultimos_envios():
    """Devolve {cliente_id: {periodo, status, detalhe, criado_em}} — só o
    envio mais recente de cada cliente (pro badge visual no painel)."""
    con = conectar()
    linhas = con.execute(
        """SELECT cliente_id, periodo, status, detalhe, criado_em FROM envios e
           WHERE criado_em = (SELECT MAX(criado_em) FROM envios WHERE cliente_id = e.cliente_id)"""
    ).fetchall()
    con.close()
    return {r["cliente_id"]: dict(r) for r in linhas}


def historico_envios(cliente_id, limite=10):
    con = conectar()
    linhas = [dict(r) for r in con.execute(
        "SELECT * FROM envios WHERE cliente_id = ? ORDER BY criado_em DESC LIMIT ?",
        (cliente_id, limite),
    ).fetchall()]
    con.close()
    return linhas


# =====================================================================
# Gestores — número de WhatsApp pessoal (pra receber envio de teste)
# =====================================================================

def upsert_gestor(instancia, nome, numero=None):
    """Cria ou atualiza o gestor dono de uma instância. `numero` só é
    sobrescrito se vier um valor não vazio — assim dá pra chamar isso de
    novo (ex: cadastro de cliente) sem apagar um número já salvo."""
    con = conectar()
    agora = _agora()
    existente = con.execute("SELECT numero FROM gestores WHERE instancia = ?", (instancia,)).fetchone()
    if existente:
        novo_numero = numero if numero else existente["numero"]
        con.execute(
            "UPDATE gestores SET nome = ?, numero = ?, atualizado_em = ? WHERE instancia = ?",
            (nome, novo_numero, agora, instancia),
        )
    else:
        con.execute(
            "INSERT INTO gestores (instancia, nome, numero, criado_em, atualizado_em) VALUES (?,?,?,?,?)",
            (instancia, nome, numero, agora, agora),
        )
    con.commit()
    con.close()


def definir_numero_gestor(instancia, nome, numero):
    """Como upsert_gestor, mas SEMPRE grava `numero` (mesmo vazio/None) — usado
    quando o usuário está explicitamente editando/limpando o número."""
    con = conectar()
    agora = _agora()
    existente = con.execute("SELECT 1 FROM gestores WHERE instancia = ?", (instancia,)).fetchone()
    if existente:
        con.execute(
            "UPDATE gestores SET nome = ?, numero = ?, atualizado_em = ? WHERE instancia = ?",
            (nome, numero, agora, instancia),
        )
    else:
        con.execute(
            "INSERT INTO gestores (instancia, nome, numero, criado_em, atualizado_em) VALUES (?,?,?,?,?)",
            (instancia, nome, numero, agora, agora),
        )
    con.commit()
    con.close()


def buscar_gestor(instancia):
    con = conectar()
    r = con.execute("SELECT * FROM gestores WHERE instancia = ?", (instancia,)).fetchone()
    con.close()
    return dict(r) if r else None


def listar_gestores():
    con = conectar()
    linhas = [dict(r) for r in con.execute("SELECT * FROM gestores ORDER BY nome COLLATE NOCASE").fetchall()]
    con.close()
    return linhas


# =====================================================================
# Mensagens pendentes (fila de revisão)
# =====================================================================

def inserir_pendente(cliente_id, periodo, saudacao, metricas, conclusao=None, pdf_path=None):
    con = conectar()
    agora = _agora()
    cur = con.execute(
        """INSERT INTO mensagens_pendentes
           (cliente_id, periodo, saudacao, metricas, conclusao, pdf_path, status, criado_em, atualizado_em)
           VALUES (?,?,?,?,?,?, 'pendente', ?, ?)""",
        (cliente_id, periodo, saudacao, metricas, conclusao, pdf_path, agora, agora),
    )
    con.commit()
    novo_id = cur.lastrowid
    con.close()
    return novo_id


def listar_pendentes(status="pendente", fluxo=None):
    con = conectar()
    q = """SELECT mp.*, c.nome AS cliente_nome, c.gestor, c.instancia, c.grupo_id, c.fluxo
           FROM mensagens_pendentes mp JOIN clientes c ON c.id = mp.cliente_id
           WHERE mp.status = ?"""
    args = [status]
    if fluxo:
        q += " AND c.fluxo = ?"
        args.append(fluxo)
    q += " ORDER BY mp.criado_em"
    linhas = [dict(r) for r in con.execute(q, args).fetchall()]
    con.close()
    return linhas


def atualizar_pendente(id_, **campos):
    """Atualiza só os campos passados. Valores None são ignorados (não viram
    NULL) — pra limpar a conclusão (nullable) mande "" em vez de None."""
    permitidos = {"saudacao", "metricas", "conclusao", "status"}
    campos = {k: v for k, v in campos.items() if k in permitidos and v is not None}
    if not campos:
        return
    campos["atualizado_em"] = _agora()
    sets = ", ".join(f"{k} = ?" for k in campos)
    con = conectar()
    con.execute(f"UPDATE mensagens_pendentes SET {sets} WHERE id = ?", (*campos.values(), id_))
    con.commit()
    con.close()


# =====================================================================
# Migração one-shot dos CSVs antigos
# =====================================================================

def _ler_csv(caminho):
    if not os.path.exists(caminho):
        return []
    with open(caminho, encoding="utf-8") as f:
        return list(csv.DictReader(f))


# instancia -> (nome, número). Antes vinha hardcoded aqui; agora é dado
# pessoal e vem de config (env NUMEROS_GESTORES, formato "Yago=55...,Joao=55...").
# A fonte da verdade é a tabela `gestores` — isto é só seed opcional.
# Nota: config.NUMEROS_GESTORES é {nome: numero}; aqui derivamos a instância
# pelo padrão comendo_<slug(nome)> só pra manter o seed legado funcionando.
def _seed_a_partir_de_config():
    saida = {}
    for nome, numero in (config.NUMEROS_GESTORES or {}).items():
        slug = _norm(nome).replace(" ", "_")
        saida[f"comendo_{slug}"] = (nome, numero)
    return saida

NUMEROS_GESTORES_CONHECIDOS = _seed_a_partir_de_config()


def seed_gestores_conhecidos():
    """Idempotente — só preenche número se a instância ainda não tiver um."""
    for instancia, (nome, numero) in NUMEROS_GESTORES_CONHECIDOS.items():
        upsert_gestor(instancia, nome, numero)


def migrar_de_csv(grupos_csv="grupos.csv", contas_ads_csv="contas_ads.csv"):
    """Popula `clientes` a partir dos CSVs antigos. Não apaga os CSVs originais.

    Idempotente por (nome, grupo_id, fluxo): se já existir, pula.
    Devolve (n_dashgoo, n_meta_ads, n_pulados).
    """
    inicializar()
    existentes = {(_norm(c["nome"]), c["grupo_id"], c["fluxo"]) for c in listar_clientes()}
    n_dashgoo = n_meta = n_pulados = 0

    for row in _ler_csv(os.path.join(BASE_DIR, grupos_csv)):
        nome = (row.get("cliente") or "").strip()
        gid = (row.get("id") or "").strip()
        if not nome or not gid:
            continue
        chave = (_norm(nome), gid, "dashgoo")
        if chave in existentes:
            n_pulados += 1
            continue
        inserir_cliente(
            nome=nome,
            gestor=(row.get("gestor") or "").strip() or "Lucas",
            instancia=(row.get("instancia") or "").strip() or "comendo",
            grupo_nome=(row.get("grupo") or "").strip(),
            grupo_id=gid,
            fluxo="dashgoo",
            status=(row.get("status") or "OK").strip() or "OK",
        )
        existentes.add(chave)
        n_dashgoo += 1

    for row in _ler_csv(os.path.join(BASE_DIR, contas_ads_csv)):
        nome = (row.get("cliente") or "").strip()
        gid = (row.get("id") or "").strip()
        if not nome or not gid:
            continue
        chave = (_norm(nome), gid, "meta_ads")
        if chave in existentes:
            n_pulados += 1
            continue
        inserir_cliente(
            nome=nome,
            gestor=(row.get("gestor") or "").strip() or "Lucas",
            instancia=(row.get("instancia") or "").strip() or "comendo",
            grupo_nome=(row.get("grupo") or "").strip(),
            grupo_id=gid,
            fluxo="meta_ads",
            ad_account_id=(row.get("ad_account_id") or "").strip() or None,
            status=(row.get("status") or "OK").strip() or "OK",
        )
        existentes.add(chave)
        n_meta += 1

    return n_dashgoo, n_meta, n_pulados


# =====================================================================
# CLI — pra ser chamado via Bash pelo slash command /relatorios-ads
# =====================================================================

def _imprimir_csv(linhas, colunas):
    w = csv.writer(sys.stdout)
    w.writerow(colunas)
    for l in linhas:
        w.writerow([l.get(c, "") for c in colunas])


def _cli():
    import argparse
    p = argparse.ArgumentParser(description="CLI do banco de clientes Comendo MKT")
    sub = p.add_subparsers(dest="comando", required=True)

    p_listar = sub.add_parser("listar", help="lista clientes")
    p_listar.add_argument("--fluxo", choices=FLUXOS)
    p_listar.add_argument("--status")
    p_listar.add_argument("--gestor", help="filtra só os clientes desse gestor (self-service por gestor)")
    p_listar.add_argument("--csv", action="store_true", help="imprime no formato CSV antigo")

    p_pend = sub.add_parser("pendentes", help="lista mensagens pendentes de revisão")
    p_pend.add_argument("--fluxo", choices=FLUXOS)

    p_env = sub.add_parser("registrar-envio", help="grava no histórico o resultado de um envio")
    p_env.add_argument("--cliente-id", type=int, required=True)
    p_env.add_argument("--periodo", required=True)
    p_env.add_argument("--status", required=True, choices=["enviado", "erro", "sem_trafego", "descartado"])
    p_env.add_argument("--detalhe", default=None)

    sub.add_parser("migrar", help="migra grupos.csv + contas_ads.csv pro banco")
    sub.add_parser("init", help="só cria as tabelas, sem migrar nada")
    sub.add_parser("gestores", help="lista os gestores cadastrados (nome, instância, número)")

    args = p.parse_args()

    if args.comando == "init":
        inicializar()
        print("OK: tabelas prontas em", DB_PATH)
    elif args.comando == "migrar":
        nd, nm, ns = migrar_de_csv()
        print(f"OK: {nd} clientes dashgoo, {nm} clientes meta_ads migrados, {ns} já existiam (pulados).")
    elif args.comando == "listar":
        linhas = listar_clientes(fluxo=args.fluxo, status=args.status, gestor=args.gestor)
        if args.csv:
            colunas = ["id", "nome", "gestor", "instancia", "grupo_nome", "grupo_id",
                       "ad_account_id", "status", "saudacao_padrao", "estilo_mensagem"]
            _imprimir_csv(linhas, colunas)
        else:
            print(json.dumps(linhas, ensure_ascii=False, indent=2))
    elif args.comando == "pendentes":
        linhas = listar_pendentes(fluxo=args.fluxo)
        print(json.dumps(linhas, ensure_ascii=False, indent=2))
    elif args.comando == "gestores":
        print(json.dumps(listar_gestores(), ensure_ascii=False, indent=2))
    elif args.comando == "registrar-envio":
        registrar_envio(args.cliente_id, args.periodo, args.status, args.detalhe)
        print(f"OK: envio registrado — cliente {args.cliente_id}, {args.periodo}, status={args.status}")


if __name__ == "__main__":
    _cli()
