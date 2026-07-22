#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Adiciona (ou atualiza) um cliente na base de envio dos relatórios (clientes.db).
Rode dentro da pasta Automacao-Relatorios:  python3 adicionar_cliente.py

Ele pergunta o nome do cliente, procura o grupo no seu WhatsApp,
você confirma, e ele grava no banco (fluxo dashgoo). A partir daí o envio é automático.

Pra cadastrar visualmente (com campos de saudação/estilo de mensagem e suporte
ao fluxo Meta Ads), use o painel.py — este script aqui é só o fallback de
terminal, pra quando não dá pra abrir o navegador.
"""

import re
import json
import unicodedata
import urllib.request

import comendo_db as db
import config

API = config.EVOLUTION_URL
KEY = config.EVOLUTION_API_KEY
INSTANCIA = config.EVOLUTION_INSTANCIA


def norm(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def fetch_grupos():
    req = urllib.request.Request(
        f"{API}/group/fetchAllGroups/{INSTANCIA}?getParticipants=false",
        headers={"apikey": KEY},
    )
    return json.loads(urllib.request.urlopen(req, timeout=120).read().decode())


print("=== Adicionar cliente à base de envio dos relatórios (Dashgoo) ===\n")
print("(Pra saudação/estilo de mensagem por cliente ou fluxo Meta Ads, use o painel.py)\n")

cliente = input("Nome do cliente (como aparece no e-mail, ex: Bar da Praia): ").strip()
if not cliente:
    print("Nome vazio. Saindo.")
    raise SystemExit

busca = input("Parte do nome do GRUPO pra procurar (Enter = usar o nome do cliente): ").strip()
if not busca:
    busca = cliente

print("\nProcurando grupos no seu WhatsApp...")
try:
    grupos = fetch_grupos()
except Exception as e:
    print("Erro ao buscar grupos (o Docker/Evolution está rodando?):", e)
    raise SystemExit

nb = norm(busca)
achados = [g for g in grupos if nb in norm(g.get("subject"))]

if not achados:
    print(f"Nenhum grupo com '{busca}' no nome. Tente outra parte do nome.")
    raise SystemExit

print("\nGrupos encontrados:")
for i, g in enumerate(achados, 1):
    print(f"  {i}) {g.get('subject')}  ->  {g.get('id')}")

if len(achados) == 1:
    escolha = 1
    print(f"\nUsando o único encontrado: {achados[0].get('subject')}")
else:
    try:
        escolha = int(input(f"\nQual é o grupo certo? (1-{len(achados)}): ").strip())
    except ValueError:
        print("Opção inválida. Saindo.")
        raise SystemExit
    if not (1 <= escolha <= len(achados)):
        print("Opção fora da faixa. Saindo.")
        raise SystemExit

g = achados[escolha - 1]
gid = g.get("id")
gnome = g.get("subject")

confirma = input(f"\nConfirma: cliente '{cliente}'  ->  grupo '{gnome}'? (s/n): ").strip().lower()
if confirma not in ("s", "sim", "y"):
    print("Cancelado, nada foi alterado.")
    raise SystemExit

existente = db.buscar_por_nome(cliente, fluxo="dashgoo")

if existente:
    resp = input(f"'{cliente}' já está na base. Atualizar pro novo grupo? (s/n): ").strip().lower()
    if resp not in ("s", "sim", "y"):
        print("Mantido como estava. Saindo.")
        raise SystemExit
    db.atualizar_cliente(existente["id"], grupo_nome=gnome, grupo_id=gid, status="OK (manual)")
    acao = "atualizado"
else:
    db.inserir_cliente(
        nome=cliente, gestor="Lucas", instancia="comendo",
        grupo_nome=gnome, grupo_id=gid, fluxo="dashgoo", status="OK (manual)",
    )
    acao = "adicionado"

print(f"\n✅ Pronto! Cliente '{cliente}' {acao} — envia pro grupo '{gnome}'.")
print("   A partir do próximo relatório dele, o envio é automático.")
