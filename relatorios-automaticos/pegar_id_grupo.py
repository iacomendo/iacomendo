#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Acha o ID de um grupo pelo nome (ou parte dele).
Roda:  python3 pegar_id_grupo.py
"""

import re
import json
import unicodedata
import urllib.request

import config

API = config.EVOLUTION_URL
KEY = config.EVOLUTION_API_KEY
INSTANCIA = config.EVOLUTION_INSTANCIA

# Parte do nome do grupo que você quer achar:
BUSCA = "automacao"


def norm(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


req = urllib.request.Request(
    f"{API}/group/fetchAllGroups/{INSTANCIA}?getParticipants=false",
    headers={"apikey": KEY},
)
grupos = json.loads(urllib.request.urlopen(req, timeout=120).read().decode())

achou = [g for g in grupos if norm(BUSCA) in norm(g.get("subject"))]
if achou:
    print("Grupos encontrados:")
    for g in achou:
        print(f"   {g.get('subject')}  ->  {g.get('id')}")
else:
    print(f"Não achei grupo com '{BUSCA}' no nome.")
