#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Automação de Relatórios — Dashgoo/MLabs → Claude → Google Drive → WhatsApp
==========================================================================

O que este script faz, toda vez que roda:
 1. Lê o Gmail e busca os e-mails NÃO LIDOS e RECENTES do Dashgoo
 2. Para cada e-mail: extrai o LINK do relatório e o NOME DO CLIENTE (do assunto)
 3. ABRE o relatório num navegador invisível, fecha o pop-up, captura o texto
    e BAIXA o PDF oficial (botão "Download PDF" do Dashgoo)
 4. Envia o texto para o Claude resumir no seu modelo de mensagem
 5. Cria a pasta da semana no Google Drive (ex: "25/05 a 31/05")
 6. Salva o PDF oficial lá dentro com o nome "Cliente - 25/05 a 31/05"
 7. Salva a mensagem pronta num .txt, numa subpasta por semana no seu Mac
 8. ENVIA no WhatsApp, via Evolution API local, em 4 mensagens:
      (1) saudação  (2) PDF com legenda  (3) métricas  (4) conclusão
 9. Marca o e-mail como lido

MODO DE TESTE: enquanto MODO_TESTE = True, manda tudo só pro SEU número.
"""

import os
import re
import json
import time
import base64
import datetime
import unicodedata

import comendo_db as db
import config
import requests
from playwright.sync_api import sync_playwright
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaInMemoryUpload

# =====================================================================
# CONFIGURAÇÕES — agora vêm de config.py (variáveis de ambiente).
# Nenhum segredo fica neste arquivo. Ver config.py / .env.example.
# =====================================================================

# Chave da API do Claude (lida sob demanda no gerar_mensagem()).
CLAUDE_MODEL = config.CLAUDE_MODEL

# Remetente dos relatórios e janela de busca no Gmail.
REMETENTE_RELATORIO = config.REMETENTE_RELATORIO
DIAS_RECENTES = config.DIAS_RECENTES

# Nome da pasta "mãe" no Google Drive onde ficam as pastas das semanas.
PASTA_MAE_DRIVE = config.PASTA_MAE_DRIVE

# Pasta onde as mensagens (.txt) são salvas, em subpasta por semana.
# Local no Mac era /Users/franca/Comendo/Relatorios; na nuvem vira diretório
# configurável (efêmero ou storage).
PASTA_SAIDA_MENSAGENS = config.PASTA_SAIDA_MENSAGENS

# ---------------------------------------------------------------------
# WHATSAPP (Evolution API) — local via Docker OU servidor na nuvem
# ---------------------------------------------------------------------

EVOLUTION_URL = config.EVOLUTION_URL
EVOLUTION_API_KEY = config.EVOLUTION_API_KEY
EVOLUTION_INSTANCIA = config.EVOLUTION_INSTANCIA

# COMO ENVIAR:
#   MODO_TESTE = True   -> manda TODAS as mensagens só pro SEU número (MEU_NUMERO)
#   MODO_TESTE = False  -> manda nos GRUPOS dos clientes (lidos do grupos.csv)
MODO_TESTE = False

# Trava de segurança (vale quando MODO_TESTE = False):
#   MODO_SIMULACAO = True  -> só MOSTRA pra onde cada relatório iria, SEM enviar
#   MODO_SIMULACAO = False -> envia pra valer nos grupos
# Deixe True na primeira vez pra conferir o roteamento com segurança.
MODO_SIMULACAO = False

# Fonte da verdade dos clientes: clientes.db (SQLite, tabela `clientes`,
# fluxo="dashgoo"). grupos.csv não é mais lido — fica só como histórico.
# Cadastro/edição de cliente agora é pelo painel.py (visual).

# MODO_REVISAO: quando ligado (via env var COMENDO_MODO_REVISAO=1, setada pelo
# botão "Gerar rascunhos p/ revisão" do painel.py), a automação processa tudo
# normalmente (Gmail, Drive, geração da mensagem) mas NÃO manda nada no
# WhatsApp — em vez disso grava um rascunho em `mensagens_pendentes` pro
# gestor revisar/editar/enviar pelo painel. Fica False por padrão, senão o
# run agendado de segunda 10h (launchd) pararia de enviar sozinho.
MODO_REVISAO = os.environ.get("COMENDO_MODO_REVISAO") == "1"

# CLIENTES_FILTRO: quando setada (via env var COMENDO_CLIENTES_FILTRO,
# separada por "|", setada pelo painel.py quando o gestor marca o checkbox de
# clientes específicos e roda manualmente), a automação só processa e-mails
# desses clientes — os demais ficam intocados (continuam UNREAD, prontos pra
# um próximo run). Vazia/ausente = processa todos, exatamente como antes
# (comportamento do run agendado de segunda 10h nunca muda).
# (normalizada com _norm_nome só dentro do main(), já que a função é definida
# mais abaixo no arquivo)
_CLIENTES_FILTRO_RAW = [n.strip() for n in os.environ.get("COMENDO_CLIENTES_FILTRO", "").split("|") if n.strip()]

# TESTE SEGURO EM GRUPO:
#   Preencha com o ID de um grupo de teste (só seu) pra que TODOS os envios
#   em modo grupo vão SÓ pra ele, ignorando o de-para.
#   Deixe "" (vazio) quando for pra produção (enviar pros clientes de verdade).
GRUPO_TESTE_ID = ""

# Seu número de WhatsApp (usado só no MODO_TESTE) — vem de config (env MEU_NUMERO).
MEU_NUMERO = config.MEU_NUMERO

# Números WhatsApp dos gestores — fallback legado. Fonte da verdade é a tabela
# `gestores`. Agora vem de config (env NUMEROS_GESTORES) em vez de hardcoded.
NUMEROS_GESTORES = config.NUMEROS_GESTORES

# (Descontinuado 2026-07-13.) Antes o resumo ia todo pro grupo interno; agora
# vai no privado de cada gestor. Deixe vazio pra não enviar no grupo.
GRUPO_RESUMO_ID = ""
GRUPO_RESUMO_INSTANCIA = ""

# Pausa (em segundos) entre um envio e outro, pra não parecer disparo em massa.
INTERVALO_ENTRE_ENVIOS = 5

# Pausa (em segundos) entre as 4 mensagens de um mesmo cliente.
PAUSA_ENTRE_MENSAGENS = 2

# 1ª mensagem (saudação fixa). Pode editar à vontade.
SAUDACAO = "Bom dia pessoal, tudo bem?"

# Legenda que vai JUNTO com o PDF (2ª mensagem). O {periodo} é preenchido sozinho.
LEGENDA_PDF = "Segue relatório de performance dos anúncios de {periodo}"

# =====================================================================
# TEMPLATE DA MENSAGEM (o seu modelo)
# =====================================================================

SYSTEM_PROMPT = """Você é um assistente especializado em marketing digital para gestores de tráfego pago. Sua função é ler relatórios do Dashgoo/MLabs e transformar os dados em mensagens claras, objetivas e fáceis de entender para donos de estabelecimentos (restaurantes, hamburguerias, pizzarias, etc.).

Regras obrigatórias:
- ANTES DE TUDO: se o relatório NÃO apresentar tráfego pago na semana — ou seja, investimento/gasto igual a R$ 0,00, nenhuma campanha de anúncios ativa, ou ausência total de dados de anúncios pagos — responda EXATAMENTE com a palavra SEM_TRAFEGO_PAGO (em letras maiúsculas, sozinha, sem mais nada). NÃO responda isso se houver qualquer gasto, por menor que seja.
- Responda APENAS com a mensagem final formatada, sem explicações, sem introduções, sem comentários extras.
- Use exatamente a estrutura do template fornecido.
- Adapte o emoji principal ao nicho do cliente (🍔 hamburgueria, 🍕 pizzaria, 🍺 bar, ☕ cafeteria, 🍣 japonês, 🥩 churrascaria, etc.). Se não identificar o nicho, use 📊.
- Adicione blocos extras (💰 Vendas no Delivery, 💬 Reservas e Contatos, 📣 Visibilidade da Marca) SOMENTE se esses dados existirem no relatório.
- Se um valor não estiver disponível no relatório, omita o campo — NUNCA invente dados.
- Formate os números exatamente como aparecem no relatório."""

USER_TEMPLATE = """Leia o relatório abaixo e preencha o template. Retorne somente a mensagem final, sem nenhum texto adicional.

NOME DO CLIENTE: {client_name}
PERÍODO: {week_period}

CONTEÚDO DO RELATÓRIO:
{report_content}

TEMPLATE:

*[Emoji] {client_name}*

*Resumo da semana ({week_period}) 📊*

*🎯 Atração de Clientes (Captação / Tráfego)*
- Pessoas alcançadas: [X] pessoas
- Visitas ao perfil/site: [X] cliques diretos
- Taxa de atração (CTR): [X]%
- Custo por visita (CPC): R$ [X]

[Se existir no relatório, inclua um ou mais blocos: *💰 Vendas no Delivery*, *💬 Reservas e Contatos*, *📣 Visibilidade da Marca*]

*👥 Movimento da Marca (Orgânico)*
- Visibilidade total: [X] visualizações da marca
- Novos seguidores: [X]

*Conclusão da semana ✅*
[Parágrafo curto e factual: 2 a 3 frases, no máximo 60 palavras. Apenas um resumo dos principais números da semana. Tom neutro, como um operador reportando dados. NÃO use adjetivos elogiosos ("incrível", "excelente", "forte", "explosão", "ótimo"), NÃO use exclamações, NÃO use emojis dentro do texto, NÃO faça projeções nem recomendações. Só os fatos da semana em prosa enxuta.]"""

# =====================================================================
# AUTENTICAÇÃO GOOGLE (Gmail + Drive)
# =====================================================================

SCOPES = config.GOOGLE_SCOPES


def _carregar_creds_iniciais():
    """Carrega as credenciais Google de onde estiverem:
      1. Env var com o CONTEÚDO do token (GOOGLE_TOKEN_JSON) — modo nuvem.
      2. Arquivo token.json no disco — modo local.
    Devolve Credentials ou None."""
    if config.GOOGLE_TOKEN_JSON:
        return Credentials.from_authorized_user_info(
            json.loads(config.GOOGLE_TOKEN_JSON), SCOPES
        )
    if os.path.exists(config.GOOGLE_TOKEN_PATH):
        return Credentials.from_authorized_user_file(config.GOOGLE_TOKEN_PATH, SCOPES)
    return None


def autenticar_google():
    """Autentica no Google (Gmail + Drive).

    - Nuvem: usa o conteúdo em GOOGLE_TOKEN_JSON (env). Se o token expirou mas
      tem refresh_token, renova em memória. NÃO abre navegador (headless).
    - Local: usa token.json; se faltar/expirar sem refresh, abre o fluxo OAuth
      no navegador (rode `logar_google.py` pra gerar o token na primeira vez).
    """
    creds = _carregar_creds_iniciais()

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        _persistir_token(creds)
        return creds

    # Sem token válido e sem refresh. Em ambiente headless (nuvem) não dá pra
    # abrir navegador — falha com mensagem clara. Local: abre o fluxo OAuth.
    if config.GOOGLE_TOKEN_JSON or not os.path.exists(config.GOOGLE_CREDENTIALS_PATH):
        raise RuntimeError(
            "Credenciais Google inválidas/ausentes e sem refresh_token utilizável. "
            "Na nuvem, gere um token novo localmente (logar_google.py) e coloque o "
            "conteúdo em GOOGLE_TOKEN_JSON. Ver README."
        )
    flow = InstalledAppFlow.from_client_secrets_file(config.GOOGLE_CREDENTIALS_PATH, SCOPES)
    creds = flow.run_local_server(port=0)
    _persistir_token(creds)
    return creds


def _persistir_token(creds):
    """Salva o token renovado em disco (modo local). Na nuvem, onde o token
    vem de env var, não há arquivo pra escrever — apenas ignora."""
    if config.GOOGLE_TOKEN_JSON:
        return
    try:
        with open(config.GOOGLE_TOKEN_PATH, "w") as token:
            token.write(creds.to_json())
    except OSError:
        pass


# =====================================================================
# PASSO 1 e 2 — Ler Gmail e extrair link + nome do cliente
# =====================================================================


def buscar_emails_relatorios(gmail):
    """Retorna a lista de e-mails não lidos e recentes do Dashgoo."""
    query = f"from:{REMETENTE_RELATORIO} is:unread newer_than:{DIAS_RECENTES}d"
    resultado = gmail.users().messages().list(userId="me", q=query).execute()
    return resultado.get("messages", [])


def extrair_corpo_html(payload):
    """Percorre o e-mail e devolve o corpo em HTML/texto."""
    if "parts" in payload:
        for part in payload["parts"]:
            texto = extrair_corpo_html(part)
            if texto:
                return texto
    else:
        data = payload.get("body", {}).get("data")
        if data:
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
    return ""


def processar_email(gmail, msg_id):
    """Lê um e-mail e devolve (nome_cliente, assunto, link_relatorio)."""
    msg = gmail.users().messages().get(userId="me", id=msg_id, format="full").execute()
    payload = msg["payload"]

    assunto = ""
    for header in payload.get("headers", []):
        if header["name"].lower() == "subject":
            assunto = header["value"]
            break

    # Nome do cliente: o que vem depois de "PF-" no assunto
    m_cliente = re.search(r"PF-\s*(.+)$", assunto)
    nome_cliente = m_cliente.group(1).strip() if m_cliente else assunto.strip()

    # Link do relatório no corpo
    corpo = extrair_corpo_html(payload)
    m_link = re.search(r"https://relatorio\.digital/[^\s\"'<>\]]+", corpo)
    link = m_link.group(0) if m_link else None

    return nome_cliente, assunto, link


# =====================================================================
# Cálculo do período da semana (segunda a domingo anterior)
# =====================================================================


def periodo_da_semana():
    hoje = datetime.date.today()
    segunda_desta = hoje - datetime.timedelta(days=hoje.weekday())
    segunda = segunda_desta - datetime.timedelta(days=7)
    domingo = segunda + datetime.timedelta(days=6)
    fmt = lambda d: f"{d.day:02d}/{d.month:02d}"
    return f"{fmt(segunda)} a {fmt(domingo)}"


# =====================================================================
# PASSO 3 — Abrir o relatório, capturar texto e BAIXAR o PDF oficial
# =====================================================================


def render_relatorio(link):
    """Abre a página, fecha o pop-up, captura o texto e baixa o PDF oficial.

    Devolve (texto_visivel, pdf_em_bytes).
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()
        try:
            page.goto(link, wait_until="networkidle", timeout=60000)
        except Exception:
            page.goto(link, wait_until="load", timeout=60000)

        # Espera os números carregarem via JavaScript
        page.wait_for_timeout(6000)

        # Fecha o pop-up "COMO VISUALIZAR O SEU RELATÓRIO", se aparecer.
        for texto_botao in ["COMEÇAR", "Começar", "COMECAR"]:
            try:
                page.locator(f"text=/{texto_botao}/i").first.click(timeout=3000)
                page.wait_for_timeout(1500)
                break
            except Exception:
                continue

        # Texto visível (para o Claude ler os números)
        texto = page.inner_text("body")

        # Baixa o PDF OFICIAL clicando no botão "Download PDF" do Dashgoo.
        pdf_bytes = None
        try:
            with page.expect_download(timeout=90000) as dl_info:
                page.locator("text=/Download PDF/i").first.click(timeout=15000)
            download = dl_info.value
            with open(download.path(), "rb") as f:
                pdf_bytes = f.read()
        except Exception:
            # Plano B: se o botão falhar, gera um PDF da página em paisagem.
            pdf_bytes = page.pdf(format="A4", landscape=True, print_background=True)

        context.close()
        browser.close()
    return texto, pdf_bytes


# =====================================================================
# PASSO 4 — Claude resume o relatório
# =====================================================================


def gerar_mensagem(nome_cliente, periodo, conteudo_relatorio, estilo_mensagem=None):
    """Gera a mensagem via Claude. `estilo_mensagem` vem do cadastro do cliente
    no banco (campo livre que o gestor preenche) — quando presente, pede pro
    Claude escrever nesse estilo em vez do tom padrão único do sistema."""
    user_msg = USER_TEMPLATE.format(
        client_name=nome_cliente,
        week_period=periodo,
        report_content=conteudo_relatorio,
    )
    if estilo_mensagem:
        user_msg += (
            "\n\nESTILO PEDIDO PELO GESTOR PARA ESTE CLIENTE (siga à risca, mas "
            "sem nunca inventar dado nem quebrar as regras obrigatórias acima):\n"
            f"{estilo_mensagem}"
        )
    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": config.anthropic_api_key(),
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": CLAUDE_MODEL,
            "max_tokens": 1024,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": user_msg}],
        },
        timeout=120,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["content"][0]["text"]


# =====================================================================
# PASSO 5 e 6 — Google Drive: criar pasta e salvar arquivo
# =====================================================================


def get_or_create_folder(drive, nome, parent_id=None):
    """Busca a pasta pelo nome; se não existir, cria. Devolve o id."""
    nome_escapado = nome.replace("'", "\\'")
    query = (
        "mimeType='application/vnd.google-apps.folder' "
        f"and name='{nome_escapado}' and trashed=false"
    )
    if parent_id:
        query += f" and '{parent_id}' in parents"
    res = drive.files().list(q=query, fields="files(id, name)").execute()
    arquivos = res.get("files", [])
    if arquivos:
        return arquivos[0]["id"]
    metadata = {"name": nome, "mimeType": "application/vnd.google-apps.folder"}
    if parent_id:
        metadata["parents"] = [parent_id]
    pasta = drive.files().create(body=metadata, fields="id").execute()
    return pasta["id"]


def salvar_no_drive(drive, dados_bytes, nome_arquivo, pasta_id, mimetype="application/pdf"):
    media = MediaInMemoryUpload(dados_bytes, mimetype=mimetype)
    metadata = {"name": nome_arquivo, "parents": [pasta_id]}
    drive.files().create(body=metadata, media_body=media, fields="id").execute()


# =====================================================================
# PASSO 8 — Enviar pelo WhatsApp (Evolution API)
# =====================================================================


def enviar_whatsapp_texto(numero, mensagem, instancia=None):
    """Envia uma mensagem de texto pelo WhatsApp via Evolution API local."""
    inst = instancia or EVOLUTION_INSTANCIA
    url = f"{EVOLUTION_URL}/message/sendText/{inst}"
    resp = requests.post(
        url,
        headers={
            "apikey": EVOLUTION_API_KEY,
            "Content-Type": "application/json",
        },
        json={"number": numero, "text": mensagem},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()


def enviar_whatsapp_documento(numero, pdf_bytes, nome_arquivo, legenda, instancia=None):
    """Envia um PDF (com legenda) pelo WhatsApp via Evolution API local."""
    inst = instancia or EVOLUTION_INSTANCIA
    url = f"{EVOLUTION_URL}/message/sendMedia/{inst}"
    midia_b64 = base64.b64encode(pdf_bytes).decode()
    resp = requests.post(
        url,
        headers={
            "apikey": EVOLUTION_API_KEY,
            "Content-Type": "application/json",
        },
        json={
            "number": numero,
            "mediatype": "document",
            "mimetype": "application/pdf",
            "media": midia_b64,
            "fileName": nome_arquivo,
            "caption": legenda,
        },
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()


def dividir_metricas_conclusao(mensagem):
    """Quebra a mensagem do Claude em (métricas, conclusão).

    Corta no marcador "Conclusão da semana". O que vem antes são as métricas;
    o que vem a partir dali é a conclusão.
    """
    m = re.search(r"\*?\s*Conclus[ãa]o da semana.*", mensagem,
                  re.IGNORECASE | re.DOTALL)
    if m:
        conclusao = m.group(0).strip()
        metricas = mensagem[:m.start()].strip()
        return metricas, conclusao
    return mensagem.strip(), ""


def enviar_sequencia(numero, periodo, pdf_bytes, nome_pdf, metricas, conclusao, instancia=None, saudacao=None):
    """Manda as 4 mensagens na ordem: saudação, PDF+legenda, métricas, conclusão.

    `saudacao` vem do cadastro do cliente (saudacao_padrao); se vazio, usa a
    saudação global SAUDACAO.
    """
    enviar_whatsapp_texto(numero, saudacao or SAUDACAO, instancia=instancia)
    time.sleep(PAUSA_ENTRE_MENSAGENS)

    legenda = LEGENDA_PDF.format(periodo=periodo)
    enviar_whatsapp_documento(numero, pdf_bytes, nome_pdf, legenda, instancia=instancia)
    time.sleep(PAUSA_ENTRE_MENSAGENS)

    enviar_whatsapp_texto(numero, metricas, instancia=instancia)

    if conclusao:
        time.sleep(PAUSA_ENTRE_MENSAGENS)
        enviar_whatsapp_texto(numero, conclusao, instancia=instancia)


def _norm_nome(s):
    """minúsculo, sem acento, e troca tudo que não é letra/número por espaço."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return s.strip()


def carregar_grupos():
    """Lê os clientes do fluxo dashgoo no banco; devolve lista de (cliente_norm, cliente, id, instancia)."""
    mapa = []
    for row in db.listar_clientes(fluxo="dashgoo"):
        cliente = (row.get("nome") or "").strip()
        gid = (row.get("grupo_id") or "").strip()
        instancia = (row.get("instancia") or "").strip() or EVOLUTION_INSTANCIA
        if cliente and gid:
            mapa.append((_norm_nome(cliente), cliente, gid, instancia))
    return mapa


def buscar_cliente_dashgoo(nome):
    """Busca o registro completo do cliente no banco (fluxo dashgoo) por nome
    aproximado — usado pra puxar saudacao_padrao/estilo_mensagem e o id
    (necessário pra gravar rascunho em MODO_REVISAO)."""
    return db.buscar_por_nome(nome, fluxo="dashgoo")


def achar_grupo(nome_email, mapa):
    """Acha o grupo cujo cliente do de-para 'cabe' no nome vindo do e-mail.

    Devolve (gid, cliente, instancia). Se mais de um casar, escolhe o nome
    de cliente mais específico (o maior, em caracteres normalizados).
    """
    ne = _norm_nome(nome_email)
    candidatos = [(cn, cli, gid, inst) for (cn, cli, gid, inst) in mapa if cn and cn in ne]
    if not candidatos:
        return None, None, None
    cn, cli, gid, inst = max(candidatos, key=lambda x: len(x[0]))
    return gid, cli, inst


def nome_para_exibir(assunto, cliente_casado):
    """Nome bonito do cliente pro título/arquivo.

    Usa o nome canônico do de-para e acrescenta o que vier depois dele no
    assunto (ex.: 'RR Lanches' + 'Zona Sul' -> 'RR Lanches Zona Sul').
    """
    if not cliente_casado:
        return assunto.strip()
    m = re.search(re.escape(cliente_casado), assunto, re.IGNORECASE)
    if not m:
        return cliente_casado
    sufixo = assunto[m.end():]
    sufixo = re.sub(r"^[\s\-|:,.]+", "", sufixo).strip()
    return (cliente_casado + (" " + sufixo if sufixo else "")).strip()


# =====================================================================
# Auto-onboarding de cliente órfão
# =====================================================================
# Se um e-mail do Dashgoo cai na caixa mas o cliente não está no grupos.csv,
# tenta descobrir sozinho qual grupo do WhatsApp corresponde e adiciona a linha.
# Só age se o match for único entre TODAS as instâncias conectadas — se ficar
# ambíguo, deixa pra ser cadastrado à mão (é reportado no resumo semanal).

_CACHE_GRUPOS_POR_INST = {}


def _fetch_instancias_conectadas():
    """Devolve lista de nomes de instâncias Evolution com state=open."""
    try:
        r = requests.get(
            f"{EVOLUTION_URL}/instance/fetchInstances",
            headers={"apikey": EVOLUTION_API_KEY},
            timeout=60,
        )
        r.raise_for_status()
        data = r.json()
    except Exception:
        return []
    saida = []
    if isinstance(data, list):
        for it in data:
            nome = it.get("name") or it.get("instanceName") or ""
            estado = it.get("connectionStatus") or it.get("state") or ""
            if nome and estado == "open":
                saida.append(nome)
    return saida


def _fetch_grupos_instancia(inst):
    """Grupos de uma instância, com cache por execução."""
    if inst in _CACHE_GRUPOS_POR_INST:
        return _CACHE_GRUPOS_POR_INST[inst]
    try:
        r = requests.get(
            f"{EVOLUTION_URL}/group/fetchAllGroups/{inst}",
            params={"getParticipants": "false"},
            headers={"apikey": EVOLUTION_API_KEY},
            timeout=180,
        )
        r.raise_for_status()
        data = r.json()
    except Exception:
        data = []
    grupos = []
    if isinstance(data, list):
        for g in data:
            grupos.append({
                "subject": g.get("subject") or "",
                "id": g.get("id") or "",
            })
    _CACHE_GRUPOS_POR_INST[inst] = grupos
    return grupos


def extrair_nome_do_assunto(assunto):
    """Tira prefixos de estratégia do assunto pra ficar só o nome do cliente.

    Ex.: 'Relatórios | T, V- Seo Mogi' -> 'Seo Mogi'
         'Relatório | T - Bar da Praia' -> 'Bar da Praia'
         'Relatorio | V - RR Lanches Taquaral' -> 'RR Lanches Taquaral'
         'Zen Burger' -> 'Zen Burger'

    Só faz o split em ` | ` e ` - ` — não tenta remover códigos de estratégia
    à parte, pra não confundir com iniciais reais de cliente (ex.: "RR Lanches").
    """
    s = (assunto or "").strip()
    if not s:
        return ""
    # Divide em ` | ` e ` - ` e pega o último pedaço não-vazio.
    partes = [p.strip() for p in re.split(r"\s*[|–\-]\s*", s) if p.strip()]
    return partes[-1] if partes else s


PALAVRAS_GRUPO_INTERNO = ["interno", "reversao", "reversão"]


def _grupo_e_interno(nome_grupo):
    n = _norm_nome(nome_grupo)
    return any(p in n for p in PALAVRAS_GRUPO_INTERNO)


def _gestor_por_instancia():
    """A partir do banco, deriva o mapa instância -> nome do gestor."""
    saida = {}
    for row in db.listar_clientes(fluxo="dashgoo"):
        inst = (row.get("instancia") or "").strip()
        gestor = (row.get("gestor") or "").strip()
        if inst and gestor and inst not in saida:
            saida[inst] = gestor
    return saida


def _resolver_nome_gestor(inst, mapa_gestores):
    """Nome humano do gestor a partir da instância, sem nunca cair no nome técnico.

    Ordem: (1) mapa dos clientes dashgoo já cadastrados; (2) tabela `gestores`
    (autoritativa — instancia -> nome); (3) último recurso, tira o prefixo
    'comendo_' e capitaliza. Nunca devolve a instância crua tipo 'comendo_joao'.
    """
    if inst in mapa_gestores and mapa_gestores[inst]:
        return mapa_gestores[inst]
    try:
        g = db.buscar_gestor(inst)
        if g and (g.get("nome") or "").strip():
            return g["nome"].strip()
    except Exception:
        pass
    if inst.startswith("comendo_"):
        return inst[len("comendo_"):].replace("_", " ").strip().title()
    return inst


def sugerir_grupo_orfao(nome_extraido, mapa_gestores, filtrar_instancias=None):
    """Procura o grupo mais provável em instâncias Evolution conectadas.

    Se `filtrar_instancias` for passado, busca só nessas (usado quando o assunto
    do e-mail explicita o gestor). Senão, varre todas as conectadas.

    Devolve dict {instancia, gestor, subject, jid} se e só se houver match
    ÚNICO. Se acha 0 ou >1, devolve None (fica pra cadastro manual).
    """
    nc = _norm_nome(nome_extraido)
    if not nc:
        return None
    matches = []
    instancias = filtrar_instancias if filtrar_instancias else _fetch_instancias_conectadas()
    for inst in instancias:
        for g in _fetch_grupos_instancia(inst):
            subj = g.get("subject") or ""
            if not subj or _grupo_e_interno(subj):
                continue
            if nc in _norm_nome(subj):
                matches.append({
                    "instancia": inst,
                    "gestor": _resolver_nome_gestor(inst, mapa_gestores),
                    "subject": subj,
                    "jid": g.get("id") or "",
                })
    if len(matches) == 1:
        return matches[0]
    return None


def _nome_canonico_gestor(inst, gestor_do_assunto):
    """Nome estável do gestor pra uma instância — nunca o texto cru do assunto.

    O mesmo gestor pode escrever o nome diferente em cada e-mail (JOAO, Joao,
    João...). Sem isso, cada variação vira um "gestor" distinto no banco e
    quebra o resumo privado. Ordem: (1) tabela `gestores` (autoritativa);
    (2) reaproveita_resolver_nome_gestor via mapa vazio -> cai no (3);
    (3) capitaliza o texto do assunto de forma consistente (title case).
    """
    try:
        g = db.buscar_gestor(inst)
        if g and (g.get("nome") or "").strip():
            return g["nome"].strip()
    except Exception:
        pass
    return (gestor_do_assunto or inst).strip().title()


def parse_assunto_estruturado(assunto, gestores_conhecidos):
    """Detecta o padrão 'Gestor | Nome do Grupo' e devolve (gestor, instancia, nome_grupo).

    `gestores_conhecidos` é dict {nome_gestor: instancia} — vem do CSV. Considera
    o padrão válido em duas rotas:
      1. O gestor está no CSV (rota preferencial).
      2. Fallback: existe uma instância Evolution `comendo_<slug_do_gestor>`
         mesmo sem clientes no CSV ainda — cobre gestor recém-onboardado.

    Sempre exige que o gestor seja reconhecido, pra não confundir com assuntos
    antigos tipo 'Relatórios | T - Foo' (aí "Relatórios" não bate com nada).
    """
    if not assunto or "|" not in assunto:
        return None
    partes = [p.strip() for p in assunto.split("|", 1)]
    if len(partes) != 2 or not all(partes):
        return None
    gestor_str, nome_grupo = partes
    gestor_norm = _norm_nome(gestor_str)
    # Rota 1: bate com gestor já presente no CSV.
    for nome_gestor, instancia in gestores_conhecidos.items():
        if _norm_nome(nome_gestor) == gestor_norm:
            return {"gestor": nome_gestor, "instancia": instancia, "grupo_nome": nome_grupo}
    # Rota 2: bate com uma instância Evolution `comendo_<slug>`.
    # O assunto pode trazer o nome completo ("JULIO ROSSI") enquanto a instância
    # usa só o primeiro nome (`comendo_julio`). Por isso tentamos, em ordem:
    #   1) nome inteiro  -> comendo_julio_rossi
    #   2) primeiro nome -> comendo_julio
    # Só aceitamos o primeiro nome se ele casar com UMA única instância, pra não
    # confundir dois gestores que compartilham o primeiro nome.
    slug_completo = re.sub(r"\s+", "_", gestor_norm)
    primeiro_nome = gestor_norm.split(" ")[0] if gestor_norm else ""
    instancias = [i for i in _fetch_instancias_conectadas() if i.startswith("comendo_")]

    for inst in instancias:
        if inst[len("comendo_"):] == slug_completo:
            return {"gestor": _nome_canonico_gestor(inst, gestor_str), "instancia": inst, "grupo_nome": nome_grupo}

    if primeiro_nome and primeiro_nome != slug_completo:
        candidatos = [i for i in instancias if i[len("comendo_"):] == primeiro_nome]
        if len(candidatos) == 1:
            inst = candidatos[0]
            return {"gestor": _nome_canonico_gestor(inst, gestor_str), "instancia": inst, "grupo_nome": nome_grupo}
    return None


def adicionar_cliente_db(nova):
    """Insere um cliente auto-onboardado no banco (fluxo dashgoo).

    `nova` é o mesmo dict de sempre: cliente, gestor, instancia, grupo, id, status.
    """
    db.inserir_cliente(
        nome=nova["cliente"],
        gestor=nova["gestor"],
        instancia=nova["instancia"],
        grupo_nome=nova["grupo"],
        grupo_id=nova["id"],
        fluxo="dashgoo",
        status=nova.get("status") or "OK",
    )


# =====================================================================
# PASSO 9 — Marcar e-mail como lido
# =====================================================================


def marcar_como_lido(gmail, msg_id):
    gmail.users().messages().modify(
        userId="me", id=msg_id, body={"removeLabelIds": ["UNREAD"]}
    ).execute()


def montar_texto_resumo(periodo, enviados, zerados, auto_cadastrados=None, pendentes=None):
    """Monta a mensagem do grupo interno.

    Seções (as opcionais só aparecem se tiverem conteúdo):
      ✅ Enviados
      ⏭️ Zerados
      🆕 Auto-cadastrados (novo cliente detectado sozinho)
      ⚠️ Cadastro pendente (chegou e-mail, mas nome não bateu com nenhum grupo)
    """
    auto_cadastrados = auto_cadastrados or []
    pendentes = pendentes or []
    linhas = [f"📋 *Resumo semanal — {periodo}*", ""]
    linhas.append(f"✅ *Clientes enviados ({len(enviados)}):*")
    if enviados:
        for n in enviados:
            linhas.append(f"• {n}")
    else:
        linhas.append("• (nenhum)")
    linhas.append("")
    linhas.append(f"⏭️ *Clientes sem envio — tráfego pago zerado ({len(zerados)}):*")
    if zerados:
        for n in zerados:
            linhas.append(f"• {n}")
    else:
        linhas.append("• (nenhum)")
    if auto_cadastrados:
        linhas.append("")
        linhas.append(f"🆕 *Cadastrados automaticamente ({len(auto_cadastrados)}):*")
        for item in auto_cadastrados:
            linhas.append(f"• {item}")
    if pendentes:
        linhas.append("")
        linhas.append(f"⚠️ *Cadastro pendente — não enviei ({len(pendentes)}):*")
        for item in pendentes:
            linhas.append(f"• {item}")
    return "\n".join(linhas)


def enviar_resumos_privados(periodo, resumo_por_gestor):
    """Manda pra CADA gestor, no privado dele, o resumo dos clientes dele.

    - Em MODO_TESTE: manda o consolidado pro MEU_NUMERO (não spam pros gestores).
    - Em MODO_SIMULACAO: não envia, só imprime pra onde iria.
    - Se um gestor não estiver em NUMEROS_GESTORES, pula com aviso no log.
    """
    if not resumo_por_gestor:
        return
    if MODO_SIMULACAO and not MODO_TESTE:
        print("🧪 SIMULAÇÃO: pularia o envio de resumos privados.")
        for gestor, dados in resumo_por_gestor.items():
            print(f"   → {gestor}: {len(dados['enviados'])} enviados, "
                  f"{len(dados['zerados'])} zerados, {len(dados['auto'])} auto, "
                  f"{len(dados['pendentes'])} pendentes")
        return

    if MODO_TESTE:
        # Consolida tudo numa mensagem só e manda pro MEU_NUMERO.
        enviados_all, zerados_all, auto_all, pend_all = [], [], [], []
        for gestor, dados in resumo_por_gestor.items():
            enviados_all += [f"{n} ({gestor})" for n in dados["enviados"]]
            zerados_all += [f"{n} ({gestor})" for n in dados["zerados"]]
            auto_all += [f"{n} ({gestor})" for n in dados["auto"]]
            pend_all += [f"{n} ({gestor})" for n in dados["pendentes"]]
        texto = montar_texto_resumo(periodo, enviados_all, zerados_all, auto_all, pend_all)
        try:
            # Em modo teste usa a instância comendo_yago (Yago é o MEU_NUMERO).
            enviar_whatsapp_texto(MEU_NUMERO, texto, instancia="comendo_yago")
            print(f"📬 Resumo consolidado enviado — MEU_NUMERO (teste).")
        except Exception as e:
            print(f"⚠️  Falha ao enviar resumo em MODO_TESTE: {e}")
        return

    # Produção: 1 mensagem por gestor, no privado dele, pela instância dele.
    for gestor, dados in resumo_por_gestor.items():
        # Instância real (rastreada durante o processamento) — nunca reconstruir
        # a partir do nome do gestor, porque "Julio Rossi" -> "comendo_julio_rossi"
        # não existe (a instância de verdade é "comendo_julio").
        instancia = dados.get("instancia")
        if not instancia:
            print(f"⚠️  Gestor '{gestor}' sem instância conhecida — pulei resumo privado.")
            continue
        # Número: tabela `gestores` (cadastrado pelo painel) primeiro,
        # NUMEROS_GESTORES hardcoded como fallback legado.
        numero = None
        try:
            g = db.buscar_gestor(instancia)
            numero = (g.get("numero") or "").strip() if g else None
        except Exception:
            pass
        numero = numero or NUMEROS_GESTORES.get(gestor)
        if not numero:
            print(f"⚠️  Gestor '{gestor}' sem número cadastrado (painel ou NUMEROS_GESTORES) — pulei resumo privado.")
            continue
        texto = montar_texto_resumo(
            periodo, dados["enviados"], dados["zerados"], dados["auto"], dados["pendentes"]
        )
        try:
            enviar_whatsapp_texto(numero, texto, instancia=instancia)
            print(f"📬 Resumo privado enviado — {gestor} ({numero}) via {instancia}.")
        except Exception as e:
            print(f"⚠️  Falha ao enviar resumo pro {gestor}: {e}")


def enviar_resumo_grupo(periodo, enviados, zerados, auto_cadastrados=None, pendentes=None):
    """(Legado) Manda um resumo consolidado num grupo interno.

    Só age se GRUPO_RESUMO_ID estiver setado (hoje está vazio — usamos os
    resumos privados por gestor via enviar_resumos_privados).
    """
    if MODO_SIMULACAO and not MODO_TESTE:
        print("🧪 SIMULAÇÃO: pularia o envio do resumo no grupo.")
        return
    if not GRUPO_RESUMO_ID or not GRUPO_RESUMO_INSTANCIA:
        return
    texto = montar_texto_resumo(periodo, enviados, zerados, auto_cadastrados, pendentes)
    destino = MEU_NUMERO if MODO_TESTE else GRUPO_RESUMO_ID
    if not destino:
        print("⚠️  Resumo do grupo: destino vazio. Não enviei.")
        return
    try:
        enviar_whatsapp_texto(destino, texto, instancia=GRUPO_RESUMO_INSTANCIA)
        etiqueta = "MEU_NUMERO (teste)" if MODO_TESTE else "grupo Performance - Sem Relatório"
        print(f"📬 Resumo enviado — {etiqueta}.")
    except Exception as e:
        print(f"⚠️  Falha ao enviar o resumo no grupo: {e}")


# =====================================================================
# FLUXO PRINCIPAL
# =====================================================================


def main():
    print("🔑 Autenticando no Google...")
    creds = autenticar_google()
    gmail = build("gmail", "v1", credentials=creds)
    drive = build("drive", "v3", credentials=creds)

    if MODO_TESTE:
        print("🧪 MODO DE TESTE ligado: as mensagens vão só pro SEU número.\n")

    clientes_filtro = set(_norm_nome(n) for n in _CLIENTES_FILTRO_RAW) if _CLIENTES_FILTRO_RAW else None
    if clientes_filtro:
        print(f"🎯 Rodando só pros cliente(s) selecionado(s): {', '.join(_CLIENTES_FILTRO_RAW)}\n")

    # Carrega o de-para sempre (serve pra achar o grupo e o nome bonito do cliente)
    mapa_grupos = carregar_grupos()
    if not MODO_TESTE:
        if not mapa_grupos:
            print("⚠️  Nenhum cliente dashgoo cadastrado no banco (clientes.db). Cadastre pelo painel.py.")
            return
        if MODO_SIMULACAO:
            print("🧪 SIMULAÇÃO: vou só MOSTRAR pra onde cada relatório iria, sem enviar.\n")
        else:
            print("📣 ENVIO REAL nos grupos dos clientes.\n")

    periodo = periodo_da_semana()
    print(f"📅 Período da semana: {periodo}\n")

    pasta_mae_id = None
    if PASTA_MAE_DRIVE:
        pasta_mae_id = get_or_create_folder(drive, PASTA_MAE_DRIVE)
    pasta_semana_id = get_or_create_folder(drive, periodo, pasta_mae_id)
    print(f"📁 Pasta da semana pronta no Drive: {periodo}\n")

    # Subpasta por semana no Mac (ex: ".../Relatórios/25-05 a 31-05")
    pasta_semana_local = os.path.join(PASTA_SAIDA_MENSAGENS, periodo.replace("/", "-"))
    os.makedirs(pasta_semana_local, exist_ok=True)

    emails = buscar_emails_relatorios(gmail)
    if not emails:
        print("Nenhum e-mail novo do Dashgoo encontrado. Nada a fazer.")
        return

    print(f"✉️  {len(emails)} e-mail(s) encontrado(s).\n")

    enviados = []
    pulados = []
    zerados = []            # subconjunto de pulados: só os SEM_TRAFEGO_PAGO (vira o resumo do grupo)
    auto_cadastrados = []   # clientes que apareceram órfãos e foram cadastrados sozinhos
    pendentes_cadastro = [] # órfãos que não conseguimos casar sozinhos (ficam pra manual)
    rascunhos = []          # MODO_REVISAO: mensagens geradas mas não enviadas, na fila pro gestor revisar
    erros = []

    if MODO_REVISAO:
        print("🗒️  MODO_REVISAO ligado: vou gerar as mensagens mas NÃO vou enviar nada no "
              "WhatsApp — elas ficam na fila de revisão do painel.py.\n")

    # Espelho do que vai por cada gestor (usado pra montar os resumos privados).
    resumo_por_gestor = {}
    def _add_por_gestor(gestor, secao, item, instancia=None):
        if not gestor:
            return
        if gestor not in resumo_por_gestor:
            resumo_por_gestor[gestor] = {
                "enviados": [], "zerados": [], "auto": [], "pendentes": [], "instancia": instancia,
            }
        if instancia and not resumo_por_gestor[gestor].get("instancia"):
            resumo_por_gestor[gestor]["instancia"] = instancia
        resumo_por_gestor[gestor][secao].append(item)

    # Cache instância -> gestor, derivado do banco atual (pra usar no auto-onboarding).
    mapa_gestores = _gestor_por_instancia()
    # Mapa inverso: nome do gestor -> instância. Usado pelo parser de assunto
    # estruturado "Gestor | Grupo".
    gestor_para_instancia = {g: i for i, g in mapa_gestores.items()}

    for item in emails:
        msg_id = item["id"]
        nome_cliente = "(desconhecido)"
        cliente_row = None  # setado assim que achamos o cliente no banco — usado pro histórico de envios
        try:
            nome_cliente, assunto, link = processar_email(gmail, msg_id)

            if not link:
                print(f"⚠️  {nome_cliente}: link do relatório não encontrado. Pulando.")
                pulados.append(nome_cliente)
                continue

            # Acha o grupo, o nome bonito e a instância do gestor dono do cliente
            gid_grupo, cliente_casado, instancia_cliente = achar_grupo(assunto, mapa_grupos)
            nome_exibicao = nome_para_exibir(assunto, cliente_casado) if cliente_casado else nome_cliente

            # Modo simulação: só confere pra onde iria, sem processar nem enviar nada
            if not MODO_TESTE and MODO_SIMULACAO:
                if gid_grupo:
                    print(f"🧪 '{nome_exibicao}'  ->  grupo de '{cliente_casado}'  (id {gid_grupo})")
                else:
                    print(f"⚠️  '{nome_cliente}'  ->  SEM grupo no de-para!")
                continue

            # Cliente órfão (não está no CSV). Duas rotas:
            #   - Em produção: tenta auto-onboarding — se acha match único entre
            #     todas as instâncias conectadas, adiciona ao CSV e envia. Senão,
            #     lista em "cadastro pendente" e pula.
            #   - Em MODO_TESTE: só loga a sugestão (não muda o CSV) e segue
            #     pelo fluxo antigo (instância default).
            if not gid_grupo:
                # Se o assunto tem o formato "Gestor | Grupo" e o gestor é
                # conhecido, restringe a busca à instância dele (mais confiável).
                estruturado = parse_assunto_estruturado(assunto, gestor_para_instancia)
                if estruturado:
                    nome_extraido = estruturado["grupo_nome"]
                    sugestao = sugerir_grupo_orfao(
                        nome_extraido, mapa_gestores,
                        filtrar_instancias=[estruturado["instancia"]],
                    )
                    if sugestao:
                        # Nome do gestor vem do assunto ('Joao'), não do fallback
                        # da função sugerir_grupo_orfao (que usaria o nome da instância).
                        sugestao["gestor"] = estruturado["gestor"]
                        print(f"   🎯 assunto estruturado: gestor '{estruturado['gestor']}' → "
                              f"buscando '{nome_extraido}' só em {estruturado['instancia']}.")
                else:
                    nome_extraido = extrair_nome_do_assunto(assunto)
                    sugestao = sugerir_grupo_orfao(nome_extraido, mapa_gestores)
                if MODO_TESTE:
                    if sugestao:
                        print(f"   🔎 órfão detectado: '{nome_extraido}' → sugestão: "
                              f"{sugestao['gestor']} / {sugestao['subject']} (só logando em MODO_TESTE).")
                    else:
                        print(f"   🔎 órfão detectado: '{nome_extraido}' → sem sugestão única.")
                else:
                    if not sugestao:
                        print(f"⚠️  '{nome_cliente}' ({nome_extraido}): órfão sem match único — cadastro pendente.")
                        pendentes_cadastro.append(f"{nome_extraido} (assunto: {assunto})")
                        # Se o parser identificou o gestor, o pendente vai pro
                        # resumo privado dele; senão fica só no log local.
                        if estruturado:
                            _add_por_gestor(estruturado["gestor"], "pendentes",
                                            f"{nome_extraido} (assunto: {assunto})",
                                            instancia=estruturado["instancia"])
                        continue
                    # Match único → registra no CSV e prossegue
                    nova = {
                        "cliente": nome_extraido,
                        "gestor": sugestao["gestor"],
                        "instancia": sugestao["instancia"],
                        "grupo": sugestao["subject"],
                        "id": sugestao["jid"],
                        "status": "OK (auto)",
                    }
                    adicionar_cliente_db(nova)
                    # atualiza estruturas em memória pra a mesma execução usar
                    mapa_grupos.append((
                        _norm_nome(nome_extraido), nome_extraido,
                        sugestao["jid"], sugestao["instancia"],
                    ))
                    # Se é o 1º cliente desse gestor entrando, popular o mapa
                    # de gestores agora — se não, o _add_por_gestor não acha
                    # o gestor pelo `mapa_gestores.get(instancia)` mais adiante.
                    mapa_gestores.setdefault(sugestao["instancia"], sugestao["gestor"])
                    gestor_para_instancia[sugestao["gestor"]] = sugestao["instancia"]
                    gid_grupo = sugestao["jid"]
                    cliente_casado = nome_extraido
                    instancia_cliente = sugestao["instancia"]
                    nome_exibicao = nome_para_exibir(assunto, cliente_casado) or nome_cliente
                    auto_cadastrados.append(
                        f"{nome_extraido} → {sugestao['gestor']} / {sugestao['subject']}"
                    )
                    _add_por_gestor(sugestao["gestor"], "auto", nome_extraido, instancia=sugestao["instancia"])
                    print(f"   🆕 auto-cadastrado: {nome_extraido} → "
                          f"{sugestao['gestor']} / {sugestao['subject']} ({sugestao['instancia']}).")

            # Rodada filtrada (checkbox no painel): pula quem não foi
            # selecionado. Não marca como lido — o e-mail fica disponível
            # pra um próximo run (agendado ou manual) processar.
            if clientes_filtro is not None and _norm_nome(cliente_casado or nome_exibicao) not in clientes_filtro:
                continue

            print(f"➡️  Processando: {nome_exibicao}")

            # Busca o cadastro completo do cliente no banco (saudação/estilo
            # customizados, se o gestor preencheu no painel).
            cliente_row = buscar_cliente_dashgoo(cliente_casado or nome_exibicao)
            saudacao_cliente = (cliente_row or {}).get("saudacao_padrao")
            estilo_cliente = (cliente_row or {}).get("estilo_mensagem")

            texto, pdf_bytes = render_relatorio(link)
            mensagem = gerar_mensagem(nome_exibicao, periodo, texto, estilo_mensagem=estilo_cliente)

            # Cliente zerado: se o Claude sinalizou que não houve tráfego pago na
            # semana, pula com segurança — NÃO salva no Drive e NÃO envia nada.
            if mensagem.strip().upper().startswith("SEM_TRAFEGO_PAGO"):
                print(f"   ⏭️  {nome_exibicao}: sem tráfego pago na semana (zerado). Pulei — não enviei nada.")
                pulados.append(f"{nome_exibicao} (sem tráfego pago)")
                zerados.append(nome_exibicao)
                _add_por_gestor(mapa_gestores.get(instancia_cliente), "zerados", nome_exibicao,
                                instancia=instancia_cliente)
                if cliente_row:
                    db.registrar_envio(cliente_row["id"], periodo, "sem_trafego")
                continue

            nome_arquivo = f"{nome_exibicao} - {periodo}"
            salvar_no_drive(drive, pdf_bytes, f"{nome_arquivo}.pdf", pasta_semana_id)

            nome_arquivo_local = nome_arquivo.replace("/", "-")
            caminho_txt = os.path.join(pasta_semana_local, f"{nome_arquivo_local}.txt")

            # Quebra a mensagem em métricas (3ª msg) e conclusão (4ª msg)
            metricas, conclusao = dividir_metricas_conclusao(mensagem)

            # Monta um registro completo das 4 mensagens pro arquivo .txt
            registro = (
                f"{saudacao_cliente or SAUDACAO}\n\n"
                f"{LEGENDA_PDF.format(periodo=periodo)}\n"
                f"[Anexo: {nome_arquivo_local}.pdf]\n\n"
                f"{metricas}\n\n"
                f"{conclusao}"
            ).strip()
            with open(caminho_txt, "w", encoding="utf-8") as f:
                f.write(registro)

            print("   ✅ PDF salvo no Drive e mensagem gerada.")

            # ---- MODO_REVISAO: grava rascunho na fila do painel, não envia ----
            if MODO_REVISAO and cliente_row:
                caminho_pdf_local = os.path.join(pasta_semana_local, f"{nome_arquivo_local}.pdf")
                with open(caminho_pdf_local, "wb") as f:
                    f.write(pdf_bytes)
                db.inserir_pendente(
                    cliente_id=cliente_row["id"],
                    periodo=periodo,
                    saudacao=saudacao_cliente or SAUDACAO,
                    metricas=metricas,
                    conclusao=conclusao,
                    pdf_path=caminho_pdf_local,
                )
                rascunhos.append(nome_exibicao)
                print(f"   🗒️  Rascunho salvo na fila de revisão — {nome_exibicao}. Não enviei nada.")
                marcar_como_lido(gmail, msg_id)
                time.sleep(INTERVALO_ENTRE_ENVIOS)
                continue
            elif MODO_REVISAO and not cliente_row:
                print(f"   ⚠️  {nome_exibicao}: MODO_REVISAO ligado mas não achei o cadastro no banco "
                      f"— enviando direto por segurança (não deixar o relatório se perder).")

            # ---- Define o destino ----
            if MODO_TESTE:
                destino = MEU_NUMERO
                if not destino:
                    print("   ⚠️  MEU_NUMERO não preenchido — pulei o envio.")
                    pulados.append(nome_exibicao)
                    continue
                etiqueta = f"seu WhatsApp ({destino})"
            else:
                destino = gid_grupo
                etiqueta = f"grupo de '{cliente_casado}'"
                if GRUPO_TESTE_ID:
                    destino = GRUPO_TESTE_ID
                    etiqueta = f"GRUPO DE TESTE (seria: '{cliente_casado}')"

            # ---- Envia as 4 mensagens (pela instância do gestor dono do cliente) ----
            enviar_sequencia(
                destino, periodo, pdf_bytes,
                f"{nome_arquivo_local}.pdf", metricas, conclusao,
                instancia=instancia_cliente, saudacao=saudacao_cliente,
            )
            print(f"   📲 4 mensagens enviadas — {etiqueta} via {instancia_cliente or EVOLUTION_INSTANCIA}.")
            enviados.append(nome_exibicao)
            _add_por_gestor(mapa_gestores.get(instancia_cliente), "enviados", nome_exibicao,
                            instancia=instancia_cliente)
            if cliente_row and not MODO_TESTE:
                db.registrar_envio(cliente_row["id"], periodo, "enviado")

            # Só marca como lido se deu tudo certo (o que falhar é tentado de novo depois)
            marcar_como_lido(gmail, msg_id)

            # Pausa entre um cliente e outro, pra não parecer disparo em massa
            time.sleep(INTERVALO_ENTRE_ENVIOS)

        except Exception as e:
            print(f"   ❌ ERRO em '{nome_cliente}': {e}")
            print("      Pulei este cliente e segui pros próximos (e-mail segue não lido).")
            erros.append(f"{nome_cliente}: {e}")
            if cliente_row and not MODO_TESTE:
                db.registrar_envio(cliente_row["id"], periodo, "erro", detalhe=str(e)[:500])
            continue

    # ---- Resumo final ----
    print("\n========== RESUMO ==========")
    print(f"✅ Enviados ({len(enviados)}): {', '.join(enviados) if enviados else '-'}")
    if rascunhos:
        print(f"🗒️  Rascunhos na fila de revisão ({len(rascunhos)}): {', '.join(rascunhos)}")
    if pulados:
        print(f"⏭️  Pulados ({len(pulados)}): {', '.join(pulados)}")
    if auto_cadastrados:
        print(f"🆕 Auto-cadastrados ({len(auto_cadastrados)}):")
        for a in auto_cadastrados:
            print(f"   - {a}")
    if pendentes_cadastro:
        print(f"⚠️  Cadastro pendente ({len(pendentes_cadastro)}):")
        for p in pendentes_cadastro:
            print(f"   - {p}")
    if erros:
        print(f"❌ Com erro ({len(erros)}):")
        for er in erros:
            print(f"   - {er}")
    print("============================")

    if MODO_REVISAO:
        # Nada foi enviado no WhatsApp neste modo — inclusive os resumos
        # privados dos gestores ficariam sem sentido (diriam "enviado" sem
        # ter enviado nada). Abra o painel.py pra revisar/editar/enviar.
        print(f"\n🗒️  {len(rascunhos)} rascunho(s) esperando revisão no painel.py.")
    else:
        # Resumo semanal: uma mensagem privada por gestor com o que aconteceu
        # com os clientes dele. (O grupo interno foi descontinuado em 2026-07-13
        # — GRUPO_RESUMO_ID vazio no topo do arquivo desativa o legado.)
        enviar_resumos_privados(periodo, resumo_por_gestor)
        enviar_resumo_grupo(periodo, enviados, zerados, auto_cadastrados, pendentes_cadastro)

    print(f"\n🎉 Concluído. As mensagens estão em: {pasta_semana_local}")


def _notificar_falha_critica(erro):
    """Avisa por WhatsApp que o run INTEIRO falhou — não confundir com erro
    de um cliente (esses já são tratados no loop e aparecem no resumo). Cobre
    falhas fora do loop principal (autenticação Google, Drive, etc.) que hoje
    não geram nenhum alerta, só log (HANDOFF §8.8). Best-effort: se o próprio
    envio falhar (ex.: Evolution fora do ar), só loga — não mascara o erro
    original.
    """
    destino = config.ALERTA_NUMERO
    if not destino:
        print("⚠️  Falha crítica sem ALERTA_NUMERO configurado — nenhum alerta enviado.")
        return
    texto = (
        f"🚨 Falha crítica na automação de relatórios (Dashgoo)\n\n"
        f"{type(erro).__name__}: {erro}\n\n"
        f"O run não completou. Confira o log."
    )
    try:
        enviar_whatsapp_texto(destino, texto, instancia=config.ALERTA_INSTANCIA)
        print(f"🚨 Alerta de falha crítica enviado para {destino}.")
    except Exception as e:
        print(f"⚠️  Falha crítica E o alerta também falhou ao enviar: {e}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n❌ FALHA CRÍTICA — o run não completou: {e}")
        _notificar_falha_critica(e)
        raise  # mantém o traceback no log e o exit code != 0 (pro agendador perceber)
