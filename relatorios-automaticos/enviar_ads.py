#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
enviar_ads.py — helper de envio pra Evolution API (WhatsApp) do fluxo Meta Ads.

Uso (chamado pelo slash command /relatorios-ads):

    python3 enviar_ads.py <caminho_payload.json>

O JSON de payload tem o formato:

    {
      "cliente": "Zen Burger",
      "cliente_id": 15,                        # id do cliente no clientes.db (comendo_db)
      "instancia": "comendo_yago",
      "numero": "120363325837990934@g.us",   # grupo OU numero pessoal em teste
      "periodo": "02/07 a 08/07",
      "mensagem_metricas": "...texto pronto...",
      "mensagem_conclusao": "...texto pronto...",   # opcional
      "modo_simulacao": false,                 # se true, so imprime, nao envia
      "modo": "enviar",                        # "enviar" (default) ou "rascunho"
      "teste": false,                          # true = indo pro privado do gestor (argumento 'teste'), não conta como envio real no histórico
      "saudacao": "Bom dia pessoal, tudo bem?" # opcional, default abaixo
    }

modo="rascunho": não manda nada no WhatsApp — grava a mensagem em
`mensagens_pendentes` (clientes.db) pro gestor revisar/editar/enviar pelo
painel.py. Precisa de "cliente_id" (vem do `comendo_db.py listar --fluxo
meta_ads`, coluna id — peça em --json se precisar do id).

Compartilha URL/api key da Evolution com o relatorios_automacao.py.
"""

import json
import os
import sys
import time
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import comendo_db as db
import config


EVOLUTION_URL = config.EVOLUTION_URL
EVOLUTION_API_KEY = config.EVOLUTION_API_KEY
PAUSA_ENTRE_MENSAGENS = 2
SAUDACAO_PADRAO = "Bom dia pessoal, tudo bem?"


def enviar_texto(numero, mensagem, instancia):
    resp = requests.post(
        f"{EVOLUTION_URL}/message/sendText/{instancia}",
        headers={"apikey": EVOLUTION_API_KEY, "Content-Type": "application/json"},
        json={"number": numero, "text": mensagem},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()


def main():
    if len(sys.argv) < 2:
        print("ERRO: passe o caminho do payload JSON", file=sys.stderr)
        sys.exit(2)

    with open(sys.argv[1], encoding="utf-8") as f:
        payload = json.load(f)

    cliente = payload["cliente"]
    cliente_id = payload.get("cliente_id")
    periodo = payload.get("periodo", "")
    saudacao = payload.get("saudacao", SAUDACAO_PADRAO)
    metricas = payload["mensagem_metricas"]
    conclusao = payload.get("mensagem_conclusao", "").strip()
    modo_simulacao = bool(payload.get("modo_simulacao", False))
    teste = bool(payload.get("teste", False))
    modo = payload.get("modo", "enviar")

    if modo == "rascunho":
        if not cliente_id:
            print("ERRO: modo=rascunho precisa de \"cliente_id\" no payload", file=sys.stderr)
            sys.exit(2)
        db.inserir_pendente(
            cliente_id=cliente_id,
            periodo=periodo,
            saudacao=saudacao,
            metricas=metricas,
            conclusao=conclusao or None,
            pdf_path=None,
        )
        print(f"[RASCUNHO] {cliente} salvo na fila de revisão (painel.py). Não enviei nada.")
        return

    instancia = payload["instancia"]
    numero = payload["numero"]

    if modo_simulacao:
        print(f"[SIMULACAO] {cliente} -> {instancia}:{numero}")
        print("--- SAUDACAO ---")
        print(saudacao)
        print("--- METRICAS ---")
        print(metricas)
        if conclusao:
            print("--- CONCLUSAO ---")
            print(conclusao)
        return

    enviar_texto(numero, saudacao, instancia)
    time.sleep(PAUSA_ENTRE_MENSAGENS)

    enviar_texto(numero, metricas, instancia)

    if conclusao:
        time.sleep(PAUSA_ENTRE_MENSAGENS)
        enviar_texto(numero, conclusao, instancia)

    if cliente_id and not teste:
        db.registrar_envio(cliente_id, periodo, "enviado")

    print(f"[OK] {cliente} enviado para {instancia}:{numero}")


if __name__ == "__main__":
    main()
