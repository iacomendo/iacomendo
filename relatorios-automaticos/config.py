#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
config.py — configuração central da automação Comendo MKT.

TODA configuração que antes vivia hardcoded nos scripts (chaves de API,
URL da Evolution, caminhos, números de gestor) agora vem daqui, e este
módulo lê de variáveis de ambiente. Nenhum segredo fica no código.

Uso:
    import config
    config.EVOLUTION_URL          # URL da Evolution (local ou nuvem)
    config.anthropic_api_key()    # chave do Claude (erro claro se faltar)

Como carregar as variáveis:
  - Local (dev): copie `.env.example` para `.env`, preencha, e rode com um
    carregador de env (python-dotenv já é importado aqui se estiver instalado).
  - Nuvem: defina as variáveis no painel do provedor / secret store. Nada
    de arquivo `.env` em produção.

Migração do stack local → nuvem (o que muda, na prática):
  - EVOLUTION_URL: de http://localhost:8080 para a URL pública do servidor.
  - ANTHROPIC_API_KEY / EVOLUTION_API_KEY: de string no .py para env var.
  - Google (Gmail/Drive): de token.json/credentials.json no disco para
    o CONTEÚDO desses JSON em env vars (GOOGLE_TOKEN_JSON / GOOGLE_CREDENTIALS_JSON).
  - Banco: DB_PATH (SQLite, hoje) → DATABASE_URL (Postgres, na nuvem). Ver comendo_db.py.
"""

import os

# Carrega .env automaticamente se python-dotenv estiver disponível (dev local).
# Em produção na nuvem as variáveis já vêm do ambiente — o import é opcional.
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()
except Exception:
    pass


# =====================================================================
# Helpers
# =====================================================================

def _get(nome, default=None):
    v = os.environ.get(nome)
    return v if (v is not None and v != "") else default


def _req(nome):
    """Variável obrigatória — levanta erro claro se faltar, em vez de
    mandar uma requisição com credencial vazia e falhar de forma obscura."""
    v = os.environ.get(nome)
    if not v:
        raise RuntimeError(
            f"Variável de ambiente obrigatória ausente: {nome}. "
            f"Defina no .env (dev) ou no secret store do provedor (nuvem). "
            f"Ver .env.example."
        )
    return v


def _bool(nome, default=False):
    v = os.environ.get(nome)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "sim", "yes", "on")


# =====================================================================
# Claude (Anthropic)
# =====================================================================

# Chave lida sob demanda (função) pra não quebrar o import de scripts que
# nem usam o Claude (ex.: utilitários de grupo).
def anthropic_api_key():
    return _req("ANTHROPIC_API_KEY")

# Modelo do resumo. Default configurável; para o rebuild vale avaliar migrar
# para um modelo atual (ex.: claude-sonnet-5) — ver HANDOFF §8.6.
CLAUDE_MODEL = _get("CLAUDE_MODEL", "claude-sonnet-4-6")


# =====================================================================
# Evolution API (WhatsApp)
# =====================================================================

# Local (dev): http://localhost:8080. Nuvem: URL pública do servidor Evolution.
EVOLUTION_URL = _get("EVOLUTION_URL", "http://localhost:8080").rstrip("/")

# Chave da Evolution. Default aponta pro valor legado só pra dev local não
# quebrar de imediato; em produção DEFINA a env var (e rotacione o valor).
EVOLUTION_API_KEY = _get("EVOLUTION_API_KEY", "comendo-evolution-2026")

# Instância padrão (fallback) quando um cliente não tem instância própria.
EVOLUTION_INSTANCIA = _get("EVOLUTION_INSTANCIA", "comendo")


# =====================================================================
# Google (Gmail + Drive) — fluxo Dashgoo
# =====================================================================

# Dois modos de fornecer as credenciais:
#   1. Arquivo (dev local, como sempre foi): caminhos abaixo.
#   2. Conteúdo em env var (nuvem): GOOGLE_CREDENTIALS_JSON / GOOGLE_TOKEN_JSON
#      guardam o JSON inteiro como string. autenticar_google() usa isso quando
#      presente, sem depender de arquivo no disco.
GOOGLE_CREDENTIALS_PATH = _get("GOOGLE_CREDENTIALS_PATH", "credentials.json")
GOOGLE_TOKEN_PATH = _get("GOOGLE_TOKEN_PATH", "token.json")
GOOGLE_CREDENTIALS_JSON = _get("GOOGLE_CREDENTIALS_JSON")  # conteúdo (nuvem)
GOOGLE_TOKEN_JSON = _get("GOOGLE_TOKEN_JSON")              # conteúdo (nuvem)

GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/drive",
]

# Remetente dos relatórios Dashgoo e janela de busca no Gmail.
REMETENTE_RELATORIO = _get("REMETENTE_RELATORIO", "no-reply@mg.dashgoo.com")
DIAS_RECENTES = int(_get("DIAS_RECENTES", "7"))

# Pasta "mãe" no Google Drive.
PASTA_MAE_DRIVE = _get("PASTA_MAE_DRIVE", "Relatórios MLabs")


# =====================================================================
# Banco de dados
# =====================================================================

# Hoje: SQLite (DB_PATH). Na nuvem: DATABASE_URL (Postgres). comendo_db.py
# escolhe o backend olhando qual das duas está definida.
DB_PATH = _get("DB_PATH")  # se None, comendo_db usa clientes.db ao lado do módulo
DATABASE_URL = _get("DATABASE_URL")  # ex.: postgresql://user:pass@host:5432/db


# =====================================================================
# Saída local (mensagens .txt/.pdf por semana)
# =====================================================================

# No Mac era /Users/franca/Comendo/Relatorios. Na nuvem vira um diretório
# efêmero (ou storage). Configurável; default relativo ao projeto.
PASTA_SAIDA_MENSAGENS = _get(
    "PASTA_SAIDA_MENSAGENS",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "relatorios_saida"),
)


# =====================================================================
# Painel web
# =====================================================================

# Local: 127.0.0.1 (só a máquina). Nuvem: 0.0.0.0 pra aceitar conexões
# externas atrás do proxy/HTTPS do provedor. Porta configurável (PORT é o
# nome padrão que a maioria dos PaaS injeta).
PAINEL_HOST = _get("PAINEL_HOST", "127.0.0.1")
PAINEL_PORT = int(_get("PORT", _get("PAINEL_PORT", "8077")))


# =====================================================================
# Números de gestor (fallback legado)
# =====================================================================
# Fonte da verdade é a tabela `gestores` no banco. Isto é só seed/fallback,
# agora configurável por env em vez de hardcoded. Formato:
#   NUMEROS_GESTORES="Yago=5519999167515,Joao=5519995336044"
def _parse_numeros_gestores(raw):
    saida = {}
    for par in (raw or "").split(","):
        par = par.strip()
        if not par or "=" not in par:
            continue
        nome, numero = par.split("=", 1)
        nome, numero = nome.strip(), numero.strip()
        if nome and numero:
            saida[nome] = numero
    return saida

NUMEROS_GESTORES = _parse_numeros_gestores(_get("NUMEROS_GESTORES", ""))

# Número usado em MODO_TESTE (envio só pra você).
MEU_NUMERO = _get("MEU_NUMERO", "")
