#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Lista os grupos do gestor Yago e tenta casar com a lista de clientes dele.
Roda:  python3 listar_grupos_yago.py
"""

import re
import csv
import json
import difflib
import unicodedata
import urllib.request
import urllib.error

import config

API = config.EVOLUTION_URL
KEY = config.EVOLUTION_API_KEY
INSTANCIA = "comendo_yago"
GESTOR = "Yago Greguer"

CLIENTES = [
    "Taz Burguer",
    "Nico Paneteria",
    "Balla Bila",
    "GPS do restaurante",
    "Loja Do Lanchero",
    "Padaria Oliveira",
    "Ricks Dog Burguer",
    "Seo Mogi Lanches",
    "Let's Fritas",
    "Casa da Broa",
    "Confraria da Carne",
    "Smeat",
]

OVERRIDES = {}

PALAVRAS_INTERNAS = ["interno", "reversao"]


def norm(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return s.strip()


def eh_interno(nome):
    n = norm(nome)
    return any(p in n for p in PALAVRAS_INTERNAS)


def call(path):
    req = urllib.request.Request(f"{API}{path}", headers={"apikey": KEY})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode())


print(f"Buscando grupos da instância {INSTANCIA}... (pode demorar)")
try:
    grupos = call(f"/group/fetchAllGroups/{INSTANCIA}?getParticipants=false")
except urllib.error.HTTPError as e:
    print("Erro HTTP:", e.code, e.read().decode())
    raise SystemExit
except Exception as e:
    print("Erro ao buscar grupos:", e)
    raise SystemExit

if not isinstance(grupos, list):
    print("Resposta inesperada da API:")
    print(json.dumps(grupos, indent=2, ensure_ascii=False))
    raise SystemExit

todos = [(g.get("subject", ""), g.get("id", "")) for g in grupos]
id_para_nome = {gid: nome for nome, gid in todos}

candidatos = [(nome, gid) for nome, gid in todos if not eh_interno(nome)]
qtd_internos = len(todos) - len(candidatos)

linhas = []

for cliente in CLIENTES:
    if cliente in OVERRIDES:
        gid = OVERRIDES[cliente]
        linhas.append((cliente, GESTOR, INSTANCIA, id_para_nome.get(gid, ""), gid, "OK (fixo)"))
        continue

    nc = norm(cliente)
    achados = [(nome, gid) for nome, gid in candidatos if nc in norm(nome)]

    if len(achados) == 1:
        nome, gid = achados[0]
        linhas.append((cliente, GESTOR, INSTANCIA, nome, gid, "OK"))
    elif len(achados) > 1:
        for nome, gid in achados:
            linhas.append((cliente, GESTOR, INSTANCIA, nome, gid, "VARIOS - escolha 1"))
    else:
        nomes_norm = {norm(nome): (nome, gid) for nome, gid in candidatos}
        prox = difflib.get_close_matches(nc, list(nomes_norm.keys()), n=1, cutoff=0.6)
        if prox:
            nome, gid = nomes_norm[prox[0]]
            linhas.append((cliente, GESTOR, INSTANCIA, nome, gid, "VERIFICAR (parecido)"))
        else:
            linhas.append((cliente, GESTOR, INSTANCIA, "", "", "NAO ENCONTRADO"))

clientes_por_id = {}
for cliente, gestor, instancia, grupo, gid, status in linhas:
    if gid:
        clientes_por_id.setdefault(gid, set()).add(cliente)
linhas = [
    (c, g, i, gr, gid, (s + " / DUPLICADO") if (gid and len(clientes_por_id.get(gid, ())) > 1) else s)
    for (c, g, i, gr, gid, s) in linhas
]

print(f"\n{len(todos)} grupos no total ({qtd_internos} internos ignorados).\n")
for cliente, gestor, instancia, grupo, gid, status in linhas:
    marca = "OK " if status.startswith("OK") else "!! "
    print(f"  {marca}{cliente}  |  {grupo or '(sem grupo)'}  |  {gid}  |  {status}")

with open("grupos_yago.csv", "w", encoding="utf-8", newline="") as f:
    w = csv.writer(f)
    w.writerow(["cliente", "gestor", "instancia", "grupo", "id", "status"])
    for linha in linhas:
        w.writerow(linha)

print("\n📄 'grupos_yago.csv' gerado. Confira os marcados com !!")
