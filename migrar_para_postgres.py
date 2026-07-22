#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
migrar_para_postgres.py — migra os dados do clientes.db (SQLite, fonte da
verdade local) para o Postgres apontado por DATABASE_URL.

Uso:
    export DATABASE_URL=postgresql://usuario:senha@host:5432/banco
    python3 migrar_para_postgres.py [--sqlite-path clientes.db] [--dry-run]

O que faz:
  1. Cria as tabelas no Postgres, se ainda não existirem (comendo_db.inicializar()).
  2. Lê clientes, gestores, envios e mensagens_pendentes do SQLite.
  3. Insere no Postgres PRESERVANDO os ids originais de clientes/envios/
     mensagens_pendentes — essencial pra não quebrar as referências
     `cliente_id` que ligam envios/mensagens_pendentes a clientes.
  4. Ajusta as sequences (SERIAL) de cada tabela pro próximo id automático
     não colidir com os ids que acabaram de ser inseridos manualmente.
  5. Idempotente por PK: se já existir uma linha com aquele id (ou aquela
     instância, no caso de gestores), pula — seguro rodar mais de uma vez.

Pré-requisito: DATABASE_URL precisa apontar pro Postgres de DESTINO antes de
rodar. Se não estiver definida, o script se recusa a rodar (senão
comendo_db usaria SQLite e a "migração" escreveria nele mesmo).
"""

import argparse
import os
import sqlite3
import sys

import config

if not config.DATABASE_URL:
    print("ERRO: defina DATABASE_URL (Postgres de destino) antes de rodar este script.")
    print("Ex.: export DATABASE_URL=postgresql://usuario:senha@host:5432/banco")
    sys.exit(1)

import comendo_db as db  # com DATABASE_URL setada, já usa o backend Postgres


def _abrir_sqlite(caminho):
    con = sqlite3.connect(caminho)
    con.row_factory = sqlite3.Row
    return con


def _linhas(con, tabela):
    return [dict(r) for r in con.execute(f"SELECT * FROM {tabela}").fetchall()]


def _copiar_com_id(pg_con, tabela, linhas, colunas, dry_run):
    """Insere linhas preservando o id original (clientes/envios/mensagens_pendentes,
    todas com PK serial `id`). Pula quem já existe (idempotente)."""
    inseridos = pulados = 0
    for linha in linhas:
        existe = pg_con.execute(f"SELECT 1 FROM {tabela} WHERE id = %s", (linha["id"],)).fetchone()
        if existe:
            pulados += 1
            continue
        if not dry_run:
            placeholders = ", ".join(["%s"] * len(colunas))
            cols_sql = ", ".join(colunas)
            valores = [linha.get(c) for c in colunas]
            pg_con.execute(
                f"INSERT INTO {tabela} (id, {cols_sql}) VALUES (%s, {placeholders})",
                [linha["id"], *valores],
            )
        inseridos += 1
    if not dry_run:
        pg_con.commit()
    return inseridos, pulados


def _resetar_sequence(pg_con, tabela):
    """Depois de inserir ids manualmente, a sequence do SERIAL fica
    desatualizada — sem isso, o próximo INSERT automático (sem id explícito)
    pode colidir com um id migrado. Ajusta pro próximo valor livre."""
    pg_con.execute(
        f"SELECT setval(pg_get_serial_sequence('{tabela}', 'id'), "
        f"COALESCE((SELECT MAX(id) FROM {tabela}), 1))"
    )
    pg_con.commit()


def _copiar_gestores(sqlite_con, pg_con, dry_run):
    """gestores tem PK = instancia (texto), não id serial — upsert simples."""
    inseridos = pulados = 0
    for g in _linhas(sqlite_con, "gestores"):
        existe = pg_con.execute("SELECT 1 FROM gestores WHERE instancia = %s", (g["instancia"],)).fetchone()
        if existe:
            pulados += 1
            continue
        if not dry_run:
            pg_con.execute(
                "INSERT INTO gestores (instancia, nome, numero, criado_em, atualizado_em) "
                "VALUES (%s,%s,%s,%s,%s)",
                (g["instancia"], g["nome"], g["numero"], g["criado_em"], g["atualizado_em"]),
            )
        inseridos += 1
    if not dry_run:
        pg_con.commit()
    return inseridos, pulados


# Ordem importa: clientes primeiro (envios/mensagens_pendentes referenciam
# cliente_id via FK ON DELETE CASCADE).
_TABELAS_COM_ID = [
    ("clientes", ["nome", "gestor", "instancia", "grupo_nome", "grupo_id", "fluxo",
                  "ad_account_id", "status", "saudacao_padrao", "estilo_mensagem",
                  "criado_em", "atualizado_em"]),
    ("envios", ["cliente_id", "periodo", "status", "detalhe", "criado_em"]),
    ("mensagens_pendentes", ["cliente_id", "periodo", "saudacao", "metricas",
                             "conclusao", "pdf_path", "status", "criado_em", "atualizado_em"]),
]


def migrar(caminho_sqlite, dry_run=False):
    if not os.path.exists(caminho_sqlite):
        print(f"ERRO: não achei {caminho_sqlite}.")
        sys.exit(1)

    print(f"Origem: {caminho_sqlite} (SQLite)")
    print(f"Destino: Postgres via DATABASE_URL")
    if dry_run:
        print("🧪 --dry-run: nada será gravado, só contado.\n")
    else:
        print()

    sqlite_con = _abrir_sqlite(caminho_sqlite)
    db.inicializar()  # garante schema no Postgres (idempotente)
    pg_con = db.conectar()

    for tabela, colunas in _TABELAS_COM_ID:
        linhas = _linhas(sqlite_con, tabela)
        ins, pul = _copiar_com_id(pg_con, tabela, linhas, colunas, dry_run)
        print(f"{tabela}: {ins} inserido(s), {pul} já existiam (pulado(s))")
        if not dry_run and ins:
            _resetar_sequence(pg_con, tabela)

    ins, pul = _copiar_gestores(sqlite_con, pg_con, dry_run)
    print(f"gestores: {ins} inserido(s), {pul} já existiam (pulado(s))")

    pg_con.close()
    sqlite_con.close()

    if dry_run:
        print("\n🧪 --dry-run concluído: nada foi gravado no Postgres.")
    else:
        print("\n✅ Migração concluída.")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sqlite-path", default="clientes.db", help="caminho do clientes.db de origem")
    ap.add_argument("--dry-run", action="store_true", help="só conta o que faria, não grava nada")
    args = ap.parse_args()
    migrar(args.sqlite_path, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
