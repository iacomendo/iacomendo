#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
backfill_envios_gmail.py — reconstrói o histórico de envio (tabela `envios`)
a partir do Gmail, pra clientes que ainda não têm nenhum registro (badge
"nunca enviado" no painel mas que na real já receberam relatório antes).

Como funciona: usa a MESMA regra que o relatorios_automacao.py já usa pra
marcar e-mail como lido — só marca como lido um e-mail do Dashgoo quando as
4 mensagens do WhatsApp foram enviadas com sucesso. Ou seja:

    e-mail do Dashgoo LIDO      -> aquele relatório foi enviado de verdade
    e-mail do Dashgoo NÃO LIDO  -> nunca foi confirmado como enviado

Pra cada cliente do fluxo dashgoo SEM registro em `envios`, procura o e-mail
lido mais recente que bate o nome (mesma lógica de casamento do achar_grupo),
calcula o período correspondente e grava 1 linha 'enviado' no histórico.
Não sobrescreve clientes que já têm histórico (esses já são mantidos pelo
fluxo normal, ao vivo).

Rode: python3 backfill_envios_gmail.py [--dias 120] [--dry-run]
"""

import argparse
import datetime

import comendo_db as db
from relatorios_automacao import autenticar_google, carregar_grupos, achar_grupo
from googleapiclient.discovery import build


def periodo_da_data(data):
    """Mesma lógica do periodo_da_semana(), mas relativa a uma data do
    e-mail em vez de 'hoje' — segunda a domingo da semana ANTERIOR à data."""
    segunda_desta = data - datetime.timedelta(days=data.weekday())
    segunda = segunda_desta - datetime.timedelta(days=7)
    domingo = segunda + datetime.timedelta(days=6)
    fmt = lambda d: f"{d.day:02d}/{d.month:02d}"
    return f"{fmt(segunda)} a {fmt(domingo)}"


def listar_emails_dashgoo(gmail, dias):
    query = f"from:no-reply@mg.dashgoo.com newer_than:{dias}d"
    msgs = []
    pagina = None
    while True:
        resp = gmail.users().messages().list(
            userId="me", q=query, maxResults=100, pageToken=pagina
        ).execute()
        msgs.extend(resp.get("messages", []))
        pagina = resp.get("nextPageToken")
        if not pagina:
            break
    return msgs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dias", type=int, default=120, help="janela de busca no Gmail (padrão 120 dias)")
    ap.add_argument("--dry-run", action="store_true", help="só mostra o que faria, não grava nada")
    args = ap.parse_args()

    print("🔑 Autenticando no Google...")
    creds = autenticar_google()
    gmail = build("gmail", "v1", credentials=creds)

    mapa_grupos = carregar_grupos()
    if not mapa_grupos:
        print("Nenhum cliente dashgoo no banco. Nada a fazer.")
        return

    ja_tem_historico = set(db.listar_ultimos_envios().keys())
    print(f"📋 {len(ja_tem_historico)} cliente(s) já têm histórico — não vou mexer neles.\n")

    print(f"✉️  Buscando e-mails do Dashgoo (últimos {args.dias} dias)...")
    msgs = listar_emails_dashgoo(gmail, args.dias)
    print(f"   {len(msgs)} e-mail(s) encontrado(s).\n")

    # cliente_id -> (data mais recente lida, periodo)
    mais_recente = {}

    for i, item in enumerate(msgs, 1):
        msg = gmail.users().messages().get(
            userId="me", id=item["id"], format="metadata",
            metadataHeaders=["Subject"],
        ).execute()
        label_ids = msg.get("labelIds", [])
        lido = "UNREAD" not in label_ids
        if not lido:
            continue  # só nos importa o que foi CONFIRMADO como enviado

        assunto = ""
        for h in msg["payload"].get("headers", []):
            if h["name"].lower() == "subject":
                assunto = h["value"]
                break
        if not assunto:
            continue

        gid, cliente_casado, instancia = achar_grupo(assunto, mapa_grupos)
        if not cliente_casado:
            continue

        cliente_row = db.buscar_por_nome(cliente_casado, fluxo="dashgoo")
        if not cliente_row:
            continue
        cid = cliente_row["id"]
        if cid in ja_tem_historico:
            continue  # já rastreado ao vivo, não sobrescreve

        data_email = datetime.datetime.fromtimestamp(int(msg["internalDate"]) / 1000)
        anterior = mais_recente.get(cid)
        if not anterior or data_email > anterior[0]:
            mais_recente[cid] = (data_email, cliente_row["nome"], assunto)

        if i % 50 == 0:
            print(f"   ...{i}/{len(msgs)} processados")

    print(f"\n📬 {len(mais_recente)} cliente(s) sem histórico têm e-mail lido (= enviado de verdade) no Gmail:\n")

    for cid, (data_email, nome, assunto) in sorted(mais_recente.items(), key=lambda item: item[1][1]):
        periodo = periodo_da_data(data_email.date())
        print(f"   • {nome} — período {periodo} (e-mail de {data_email.strftime('%d/%m/%Y')}, assunto: '{assunto}')")
        if not args.dry_run:
            db.registrar_envio(cid, periodo, "enviado",
                                detalhe="reconstruído do Gmail (e-mail do Dashgoo já lido)")

    if args.dry_run:
        print("\n🧪 --dry-run: nada foi gravado.")
    else:
        print(f"\n✅ Histórico reconstruído pra {len(mais_recente)} cliente(s).")

    # Aviso informativo: clientes que continuam sem NENHUM sinal de envio confirmado
    sem_nada = [c["nome"] for c in db.listar_clientes(fluxo="dashgoo")
                if c["id"] not in ja_tem_historico and c["id"] not in mais_recente]
    if sem_nada:
        print(f"\n⚠️  {len(sem_nada)} cliente(s) continuam sem NENHUM envio confirmado "
              f"(nem no histórico ao vivo, nem no Gmail dos últimos {args.dias} dias):")
        for n in sem_nada:
            print(f"   - {n}")
        print("   (pode ser cliente novo, ou que nunca recebeu relatório de fato — vale conferir)")


if __name__ == "__main__":
    main()
