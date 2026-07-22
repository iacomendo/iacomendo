#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Faz APENAS o login no Google e gera um novo token.json.
Não processa nenhum e-mail — serve pra trocar a conta que a automação usa.

Como usar:
  1. Feche o navegador se estiver logado com a conta antiga.
  2. Rode:  python3 logar_google.py
  3. Vai abrir o navegador — escolha/entre com a conta desejada
     (ex.: relatorioscomendomkt@gmail.com).
  4. Autorize os escopos (Gmail + Drive).
  5. O token.json é gravado nesta pasta.
"""

import os
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

import config

SCOPES = config.GOOGLE_SCOPES
CREDENTIALS_PATH = config.GOOGLE_CREDENTIALS_PATH
TOKEN_PATH = config.GOOGLE_TOKEN_PATH

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)


def main():
    if os.path.exists(TOKEN_PATH):
        print(f"⚠️  Já existe {TOKEN_PATH} nesta pasta.")
        print("   Se quiser gerar um novo (com outra conta), apague ou renomeie o atual antes.")
        return

    if not os.path.exists(CREDENTIALS_PATH):
        print(f"❌ Não achei {CREDENTIALS_PATH} nesta pasta.")
        print("   Esse arquivo é o segredo do app OAuth (Google Cloud Console).")
        return

    flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
    creds = flow.run_local_server(port=0)
    with open(TOKEN_PATH, "w") as f:
        f.write(creds.to_json())

    # Sanidade: quem foi logado?
    from googleapiclient.discovery import build
    gmail = build("gmail", "v1", credentials=creds)
    perfil = gmail.users().getProfile(userId="me").execute()
    print("\n✅ Login concluído.")
    print(f"   Conta autenticada: {perfil.get('emailAddress')}")
    print("   Token salvo em: token.json")


if __name__ == "__main__":
    main()
