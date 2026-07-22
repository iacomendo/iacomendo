#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Painel visual pra gerenciar a automação de relatórios.
Roda:  python3 painel.py   (ou dê 2 cliques no Painel.command)
Abre uma tela no navegador pra:
  - Adicionar/editar/excluir clientes (fluxo Dashgoo OU Meta Ads, num só painel)
  - Definir saudação e estilo de mensagem por cliente (cada gestor escreve do seu jeito)
  - Revisar e editar mensagens antes de enviar (fila de revisão)
  - Adicionar um gestor novo (cria a instância Evolution + mostra o QR)
  - Rodar a automação Dashgoo na hora (direto ou gerando rascunhos p/ revisão)
As mudanças são salvas em clientes.db (SQLite) — grupos.csv/contas_ads.csv não
são mais lidos por este painel (ficam só como histórico do que existia antes).
"""

import os
import sys
import json
import subprocess
import threading
import unicodedata
import re
import urllib.parse
import urllib.request
import urllib.error
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import comendo_db as db
import config

API = config.EVOLUTION_URL
KEY = config.EVOLUTION_API_KEY
PORT = config.PAINEL_PORT

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPT_PATH = os.path.join(BASE_DIR, "relatorios_automacao.py")
RUN_LOG_PATH = os.path.join(BASE_DIR, "painel_ultima_execucao.log")

db.inicializar()

# Estado da execução em andamento (subprocess.Popen). Lock pra evitar 2 runs.
_run_state = {"proc": None, "lock": threading.Lock()}


# =====================================================================
# Helpers Evolution API
# =====================================================================

def _http(method, path, body=None):
    url = f"{API}{path}"
    data = None
    headers = {"apikey": KEY}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    # 240s: buscar grupos de instâncias com muito histórico (ex: número
    # pessoal do Lucas) pode demorar bem mais que uma chamada comum.
    with urllib.request.urlopen(req, timeout=240) as r:
        raw = r.read().decode("utf-8")
        if not raw:
            return {}
        return json.loads(raw)


def fetch_instancias():
    data = _http("GET", "/instance/fetchInstances")
    saida = []
    if isinstance(data, list):
        for inst in data:
            nome = inst.get("name") or inst.get("instanceName") or ""
            estado = inst.get("connectionStatus") or inst.get("state") or "?"
            if nome:
                saida.append({"name": nome, "state": estado})
    saida.sort(key=lambda x: x["name"].lower())
    return saida


def fetch_grupos(instancia):
    inst = urllib.parse.quote(instancia)
    data = _http("GET", f"/group/fetchAllGroups/{inst}?getParticipants=false")
    out = []
    if isinstance(data, list):
        for g in data:
            out.append({"subject": g.get("subject") or "(sem nome)", "id": g.get("id") or ""})
    out.sort(key=lambda x: x["subject"].lower())
    return out


def criar_instancia(nome):
    body = {"instanceName": nome, "qrcode": True, "integration": "WHATSAPP-BAILEYS"}
    try:
        data = _http("POST", "/instance/create", body)
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read().decode("utf-8"))
        except Exception:
            err = {"raw": str(e)}
        return {"erro": err}
    qr = (data.get("qrcode") or {}).get("base64") or ""
    return {"instancia": nome, "qr_base64": qr}


def estado_instancia(instancia):
    inst = urllib.parse.quote(instancia)
    data = _http("GET", f"/instance/connectionState/{inst}")
    return (data.get("instance") or {}).get("state") or "?"


def reqr_instancia(instancia):
    inst = urllib.parse.quote(instancia)
    data = _http("GET", f"/instance/connect/{inst}")
    return {"qr_base64": data.get("base64", "")}


def enviar_whatsapp_texto(numero, mensagem, instancia):
    url = f"{API}/message/sendText/{urllib.parse.quote(instancia)}"
    req = urllib.request.Request(
        url,
        data=json.dumps({"number": numero, "text": mensagem}).encode("utf-8"),
        headers={"apikey": KEY, "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8") or "{}")


def enviar_whatsapp_documento(numero, instancia, caminho_pdf, legenda):
    """Manda um PDF local (com legenda) pelo WhatsApp. Usado ao enviar um
    rascunho pendente que tem PDF salvo (fluxo Dashgoo)."""
    import base64
    with open(caminho_pdf, "rb") as f:
        midia_b64 = base64.b64encode(f.read()).decode()
    url = f"{API}/message/sendMedia/{urllib.parse.quote(instancia)}"
    req = urllib.request.Request(
        url,
        data=json.dumps({
            "number": numero,
            "mediatype": "document",
            "mimetype": "application/pdf",
            "media": midia_b64,
            "fileName": os.path.basename(caminho_pdf),
            "caption": legenda,
        }).encode("utf-8"),
        headers={"apikey": KEY, "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode("utf-8") or "{}")


def slug(nome):
    s = unicodedata.normalize("NFKD", nome or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s


# =====================================================================
# Run da automação Dashgoo (subprocess) — direto ou em modo revisão
# =====================================================================

def iniciar_run(modo_revisao=False, clientes_filtro=None):
    with _run_state["lock"]:
        proc = _run_state.get("proc")
        if proc and proc.poll() is None:
            return {"erro": "Já existe uma execução em andamento."}
        with open(RUN_LOG_PATH, "w", encoding="utf-8") as f:
            f.write("")
        logf = open(RUN_LOG_PATH, "a", encoding="utf-8")
        env = dict(os.environ)
        if modo_revisao:
            env["COMENDO_MODO_REVISAO"] = "1"
        if clientes_filtro:
            env["COMENDO_CLIENTES_FILTRO"] = "|".join(clientes_filtro)
        proc = subprocess.Popen(
            [sys.executable, SCRIPT_PATH],
            cwd=BASE_DIR, env=env,
            stdout=logf, stderr=subprocess.STDOUT,
        )
        _run_state["proc"] = proc
        return {"ok": True}


def estado_run():
    proc = _run_state.get("proc")
    if not proc:
        return {"rodando": False, "rc": None}
    rc = proc.poll()
    return {"rodando": rc is None, "rc": rc}


def ler_run_log():
    if not os.path.exists(RUN_LOG_PATH):
        return ""
    with open(RUN_LOG_PATH, encoding="utf-8", errors="replace") as f:
        return f.read()


# =====================================================================
# HTML / JS do painel
# =====================================================================

HTML = r'''<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Painel — Relatórios Comendo MKT</title>
<style>
  :root {
    --bg:#000000; --card:#141414; --card2:#0c0c0c; --txt:#f4f7fb; --muted:#96a0ab; --linha:#2a2a2a;
    --amarelo:#F2C50E; --amarelo2:#ffd83d; --navy-on-amarelo:#0D1A2E;
    --verde:#22c55e; --vermelho:#ef4444; --input-bg:#0a0a0a;
  }
  * { box-sizing:border-box; }
  body { margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; background:var(--bg); color:var(--txt); }
  .wrap { max-width:1040px; margin:0 auto; padding:24px; }
  h1 { font-size:22px; margin:0 0 4px; font-weight:800; letter-spacing:.2px; }
  h1 .marca-marketing { color:var(--amarelo); font-style:italic; font-weight:800; }
  .sub { color:var(--muted); font-size:14px; margin-bottom:20px; }
  .card { background:var(--card); border:1px solid var(--linha); border-radius:14px; padding:18px; margin-bottom:18px; }
  .topo { display:flex; justify-content:space-between; align-items:center; gap:8px; flex-wrap:wrap; margin-bottom:12px; }
  .acoes-topo { display:flex; gap:8px; flex-wrap:wrap; align-items:center; }
  table { width:100%; border-collapse:collapse; }
  th,td { text-align:left; padding:10px 8px; border-bottom:1px solid var(--linha); font-size:14px; vertical-align:top; }
  th { color:var(--muted); font-weight:600; }
  button { cursor:pointer; border:none; border-radius:8px; padding:9px 14px; font-size:14px; font-weight:600; }
  button:disabled { opacity:.45; cursor:not-allowed; }
  .btn { background:var(--amarelo); color:var(--navy-on-amarelo); }
  .btn:hover { background:var(--amarelo2); }
  .btn-verde { background:var(--verde); color:#06210f; }
  .btn-teste { background:transparent; color:var(--amarelo); border:1px solid var(--amarelo); }
  .btn-teste:hover { background:rgba(242,197,14,.12); }
  .btn-sec { background:transparent; color:var(--txt); border:1px solid var(--linha); }
  .btn-del { background:transparent; color:var(--vermelho); border:1px solid var(--linha); padding:6px 10px; }
  .btn-edit { background:transparent; color:var(--txt); border:1px solid var(--linha); padding:6px 10px; margin-right:6px; }
  input,select,textarea { width:100%; padding:10px; border-radius:8px; border:1px solid var(--linha); background:var(--input-bg); color:var(--txt); font-size:14px; font-family:inherit; }
  input:focus,select:focus,textarea:focus { outline:none; border-color:var(--amarelo); }
  textarea { resize:vertical; min-height:70px; }
  label { display:block; font-size:13px; color:var(--muted); margin:12px 0 4px; }
  .hint { color:var(--muted); font-size:12px; margin-top:4px; }
  .acoes { display:flex; justify-content:flex-end; gap:8px; margin-top:16px; }
  .toast { position:fixed; bottom:22px; left:50%; transform:translateX(-50%); background:var(--amarelo); color:var(--navy-on-amarelo); padding:11px 18px; border-radius:10px; font-weight:700; opacity:0; transition:opacity .25s; pointer-events:none; z-index:99; }
  .toast.show { opacity:1; }
  .toast.erro { background:var(--vermelho); color:#fff; }
  .hidden { display:none !important; }
  .vazio { color:var(--muted); padding:14px 8px; }
  .grpid { color:var(--muted); font-size:12px; margin-top:2px; }
  .pill { display:inline-block; font-size:11px; padding:2px 8px; border-radius:999px; background:var(--input-bg); border:1px solid var(--linha); color:var(--muted); }
  .pill.aberto { color:var(--verde); border-color:var(--verde); }
  .pill.fechado { color:var(--vermelho); border-color:var(--vermelho); }
  .pill.fluxo-dashgoo { color:#c7d2e0; border-color:#c7d2e0; }
  .pill.fluxo-meta_ads { color:var(--amarelo); border-color:var(--amarelo); }
  .pill.sem-numero { color:var(--vermelho); border-color:var(--vermelho); cursor:pointer; }
  .pill.status-enviado { color:var(--verde); border-color:var(--verde); }
  .pill.status-erro { color:var(--vermelho); border-color:var(--vermelho); cursor:help; }
  .pill.status-sem_trafego { color:var(--muted); border-color:var(--linha); }
  .pill.status-descartado { color:var(--muted); border-color:var(--linha); }
  .pill.status-nunca { color:var(--muted); border-color:var(--linha); border-style:dashed; }
  .visao-select { max-width:220px; }
  .gestor-bloco { margin-top:14px; }
  .gestor-titulo { display:flex; align-items:center; gap:10px; margin:8px 0; color:var(--muted); font-size:13px; text-transform:uppercase; letter-spacing:.5px; }
  .gestor-titulo .link-numero { color:var(--amarelo); cursor:pointer; text-transform:none; letter-spacing:0; font-size:12px; background:none; border:none; padding:0; font-weight:600; }
  .tabs { display:flex; gap:6px; margin-bottom:16px; }
  .tab { padding:9px 16px; border-radius:9px; background:transparent; color:var(--muted); border:1px solid var(--linha); cursor:pointer; font-weight:600; font-size:14px; }
  .tab.ativa { background:var(--amarelo); color:var(--navy-on-amarelo); border-color:var(--amarelo); }
  .badge-count { background:var(--vermelho); color:#fff; border-radius:999px; padding:1px 7px; font-size:11px; margin-left:6px; }
  .pend-card { border:1px solid var(--linha); border-radius:10px; padding:14px; margin-bottom:12px; background:var(--card2); }
  .pend-card.selecionado { border-color:var(--amarelo); box-shadow:0 0 0 1px var(--amarelo) inset; }
  .pend-topo { display:flex; justify-content:space-between; align-items:baseline; margin-bottom:8px; flex-wrap:wrap; gap:6px; }
  .pend-topo strong { font-size:15px; }
  .pend-check { display:flex; align-items:center; gap:8px; }
  .pend-check input { width:auto; margin:0; }
  .fila-toolbar { display:flex; align-items:center; gap:10px; flex-wrap:wrap; margin-bottom:14px; padding-bottom:14px; border-bottom:1px solid var(--linha); }
  .fila-toolbar .contagem-sel { color:var(--muted); font-size:13px; }
  .modal-bg { position:fixed; inset:0; background:rgba(0,0,0,.6); display:flex; align-items:center; justify-content:center; z-index:50; }
  .modal { background:var(--card); border:1px solid var(--linha); border-radius:14px; padding:22px; width:min(560px, 92vw); max-height:90vh; overflow:auto; }
  .qrbox { background:#fff; padding:12px; border-radius:10px; display:flex; align-items:center; justify-content:center; }
  .qrbox img { display:block; max-width:100%; height:auto; }
  pre { background:var(--input-bg); border:1px solid var(--linha); border-radius:8px; padding:12px; max-height:380px; overflow:auto; font-size:12px; white-space:pre-wrap; word-break:break-word; }
  .radio-row { display:flex; gap:16px; margin-top:6px; }
  .radio-row label { display:flex; align-items:center; gap:6px; color:var(--txt); font-size:14px; margin:0; }
  .radio-row input { width:auto; }
</style>
</head>
<body>
<div class="wrap">
  <h1>📊 Painel — Comendo <span class="marca-marketing">Marketing</span></h1>
  <div class="sub">Cadastro único (Dashgoo + Meta Ads) com estilo de mensagem por cliente. Salva direto no banco.</div>

  <div class="tabs">
    <button class="tab ativa" id="tabClientes" onclick="mudarAba('clientes')">Clientes</button>
    <button class="tab" id="tabFila" onclick="mudarAba('fila')">Fila de revisão <span class="badge-count hidden" id="badgeFila">0</span></button>
  </div>

  <div id="painelClientes">
    <div class="card">
      <div class="topo">
        <strong id="contagem">Clientes</strong>
        <div class="acoes-topo">
          <label style="margin:0;display:flex;align-items:center;gap:6px;font-size:13px;color:var(--muted);">👁 Visão
            <select class="visao-select" id="selVisao" onchange="mudarVisao(this.value)"></select>
          </label>
          <button class="btn-sec" onclick="abrirGestor()">+ Adicionar gestor</button>
          <button class="btn" onclick="abrirCliente()">+ Adicionar cliente</button>
          <button class="btn-sec" onclick="rodar(true)">🗒 Gerar rascunhos p/ revisão (Dashgoo)</button>
          <button class="btn-verde" onclick="rodar(false)" id="btnRodar">▶ Rodar agora (envio direto)</button>
        </div>
      </div>
      <div class="fila-toolbar hidden" id="selClientesToolbar">
        <span class="contagem-sel" id="selClientesInfo">0 selecionado(s)</span>
        <span class="hint" style="margin:0;">Os botões "Gerar rascunhos" / "Rodar agora" acima vão agir só nesses clientes.</span>
        <button class="btn-sec" onclick="limparSelecaoClientes()">Limpar seleção</button>
      </div>
      <div id="listaGestores"></div>
      <div id="vazio" class="vazio hidden">Nenhum cliente cadastrado ainda.</div>
    </div>
  </div>

  <div id="painelFila" class="hidden">
    <div class="card">
      <div class="topo">
        <strong>Mensagens aguardando revisão</strong>
        <span class="hint" style="margin:0;">Edite o texto à vontade antes de enviar. Rascunhos do Meta Ads entram aqui via <code>/relatorios-ads revisao</code>.</span>
      </div>
      <div class="fila-toolbar" id="filaToolbar">
        <label class="pend-check" style="margin:0;"><input type="checkbox" id="chkTodos" onchange="selecionarTodos(this.checked)"> Selecionar todos</label>
        <span class="contagem-sel" id="contagemSel">0 selecionado(s)</span>
        <button class="btn-teste" onclick="enviarTesteSelecionados()" id="btnTesteSel" disabled>🧪 Enviar teste (privado do gestor)</button>
        <button class="btn-verde" onclick="enviarManualSelecionados()" id="btnManualSel" disabled>✅ Enviar manual (pro grupo do cliente)</button>
      </div>
      <div id="listaPendentes"></div>
      <div id="filaVazia" class="vazio hidden">Nenhuma mensagem pendente no momento.</div>
    </div>
  </div>
</div>

<!-- Modal: Adicionar/Editar cliente -->
<div class="modal-bg hidden" id="modalCliente">
  <div class="modal">
    <strong id="tituloCliente">Adicionar cliente</strong>

    <label>Fluxo</label>
    <div class="radio-row">
      <label><input type="radio" name="fluxo" value="dashgoo" checked onchange="onTrocarFluxo()"> Dashgoo / mLabs</label>
      <label><input type="radio" name="fluxo" value="meta_ads" onchange="onTrocarFluxo()"> Meta Ads direto (só tráfego)</label>
    </div>

    <label>Gestor</label>
    <select id="inGestor" onchange="onTrocarGestor()"></select>
    <div class="hint hidden" id="avisoSemNome" style="margin-top:4px;">
      <span id="avisoSemNomeTexto"></span>
      <button class="btn-sec" type="button" style="padding:3px 8px;font-size:12px;margin-left:4px;" onclick="nomearInstanciasPendentes()">✎ Nomear agora</button>
    </div>
    <label>Nome do cliente (como aparece no relatório/e-mail)</label>
    <input id="inCliente" placeholder="Ex: Bar da Praia">

    <div id="blocoAdAccount" class="hidden">
      <label>Ad Account ID (Meta Ads) <span class="hint" style="margin:0;">só números, sem "act_"</span></label>
      <input id="inAdAccount" placeholder="Ex: 112343182536011">
    </div>

    <label>Grupo no WhatsApp <span id="hintGrupos" style="color:var(--muted);font-size:12px;"></span></label>
    <input id="filtroGrupo" placeholder="Filtrar grupos pelo nome..." oninput="filtrarGrupos()" style="margin-bottom:8px;">
    <select id="inGrupo" size="6"></select>

    <label>Saudação padrão deste cliente <span class="hint" style="margin:0;">(opcional — em branco usa a saudação padrão do sistema)</span></label>
    <input id="inSaudacao" placeholder="Ex: Bom dia, time! Tudo certo?">

    <label>Estilo de mensagem deste cliente <span class="hint" style="margin:0;">(opcional — escreva do seu jeito: tom, o que sempre incluir, o que nunca fazer)</span></label>
    <textarea id="inEstilo" placeholder="Ex: tom mais informal e direto; sempre citar o fim de semana separado; evitar a palavra 'performance'; fechar sempre com uma pergunta pro cliente."></textarea>

    <label>Status</label>
    <select id="inStatus">
      <option value="OK">OK (produção)</option>
      <option value="TESTE">TESTE (só com flag teste)</option>
      <option value="PENDENTE_ACESSO">PENDENTE_ACESSO (Meta Ads sem acesso ainda)</option>
      <option value="OFF">OFF (pausado)</option>
    </select>

    <div class="acoes">
      <button class="btn-sec" onclick="fecharCliente()">Cancelar</button>
      <button class="btn" onclick="salvarCliente()">Salvar</button>
    </div>
  </div>
</div>

<!-- Modal: Adicionar gestor -->
<div class="modal-bg hidden" id="modalGestor">
  <div class="modal">
    <strong>Adicionar gestor</strong>
    <p style="color:var(--muted);font-size:13px;margin:8px 0 0;">Vou criar uma instância Evolution e mostrar o QR. O gestor abre WhatsApp → Aparelhos conectados → Conectar aparelho.</p>

    <div id="passo1">
      <label>Nome do gestor (ex.: Yago, João, Maria)</label>
      <input id="inNomeGestor" placeholder="Yago">
      <label>Número do WhatsApp dele <span class="hint" style="margin:0;">(DDI+DDD+número, ex: 5519999167515 — usado pra receber envio de teste)</span></label>
      <input id="inNumeroGestor" placeholder="5519999999999">
      <div class="acoes">
        <button class="btn-sec" onclick="fecharGestor()">Cancelar</button>
        <button class="btn" onclick="criarGestor()" id="btnCriarGestor">Criar instância</button>
      </div>
    </div>

    <div id="passo2" class="hidden">
      <p style="margin:12px 0 8px;">Instância criada: <code id="instCriada"></code></p>
      <p style="margin:0 0 10px;"><a href="http://localhost:8080/manager" target="_blank" class="btn" style="display:inline-block;text-decoration:none;">↗ Abrir no Evolution Manager pra escanear</a></p>
      <p class="hint" style="margin:0 0 10px;">Lá, procure a instância <code id="instCriada2"></code> na lista e clique em conectar. Ou, se preferir, escaneie aqui embaixo mesmo:</p>
      <div class="qrbox"><img id="qrImg" alt="QR Code"></div>
      <p style="color:var(--muted);font-size:13px;margin:10px 0 0;" id="statusConexao">Esperando conexão...</p>
      <div class="acoes">
        <button class="btn-sec" onclick="fecharGestor()">Fechar</button>
      </div>
    </div>
  </div>
</div>

<!-- Modal: Rodar agora -->
<div class="modal-bg hidden" id="modalRun">
  <div class="modal">
    <strong id="tituloRun">Execução manual</strong>
    <p style="color:var(--muted);font-size:13px;margin:6px 0 10px;" id="runStatus">Disparando...</p>
    <pre id="runLog"></pre>
    <div class="acoes">
      <button class="btn-sec" onclick="fecharRun()">Fechar</button>
    </div>
  </div>
</div>

<div class="toast" id="toast"></div>

<script>
let clientes = [];
let instancias = [];
let gruposCache = {};
let editId = null;
let pendentes = [];
let gestoresNumero = [];   // [{instancia, nome, numero}]
let selecionados = new Set();
let selecionadosClientes = new Set();  // ids de clientes marcados p/ envio manual avulso (checkbox na aba Clientes)
let enviosUltimos = {};    // {cliente_id: {periodo, status, detalhe, criado_em}}
let visaoAtual = localStorage.getItem("comendo_visao") || "mestre";

function mudarAba(aba) {
  document.getElementById("tabClientes").classList.toggle("ativa", aba === "clientes");
  document.getElementById("tabFila").classList.toggle("ativa", aba === "fila");
  document.getElementById("painelClientes").classList.toggle("hidden", aba !== "clientes");
  document.getElementById("painelFila").classList.toggle("hidden", aba !== "fila");
  if (aba === "fila") carregarPendentes();
}

async function carregar() {
  try {
    const [rc, ri, rg, re] = await Promise.all([
      fetch("/api/clientes"), fetch("/api/instancias"), fetch("/api/gestores"), fetch("/api/envios/ultimos"),
    ]);
    clientes = await rc.json();
    instancias = await ri.json();
    gestoresNumero = await rg.json();
    enviosUltimos = await re.json();
    const idsAtuais = new Set(clientes.map(c => c.id));
    selecionadosClientes.forEach(id => { if (!idsAtuais.has(id)) selecionadosClientes.delete(id); });
    preencherSelVisao();
    render();
    carregarPendentes();
  } catch (e) { toast("Erro ao carregar dados. Docker/Evolution está rodando?", true); }
}

function preencherSelVisao() {
  const sel = document.getElementById("selVisao");
  // Junta gestor de cliente já cadastrado + toda instância conectada — senão
  // gestor sem cliente ainda (recém-plugado) nem aparece na lista de visões.
  const doClientes = clientes.map(c => c.gestor).filter(Boolean);
  const dasInstancias = instancias.map(inst => nomeExibicaoGestor(inst.name));
  const nomes = Array.from(new Set([...doClientes, ...dasInstancias])).sort((a,b) => a.localeCompare(b));
  sel.innerHTML = "<option value='mestre'>Mestre (todos os gestores)</option>" +
    nomes.map(n => "<option value='" + esc(n) + "'>" + esc(n) + " (micro)</option>").join("");
  if (!["mestre", ...nomes].includes(visaoAtual)) visaoAtual = "mestre";
  sel.value = visaoAtual;
}
function mudarVisao(v) {
  visaoAtual = v;
  localStorage.setItem("comendo_visao", v);
  render();
  renderPendentes();
}
function clientesNaVisao() {
  return visaoAtual === "mestre" ? clientes : clientes.filter(c => c.gestor === visaoAtual);
}
function pendentesNaVisao() {
  return visaoAtual === "mestre" ? pendentes : pendentes.filter(p => p.gestor === visaoAtual);
}

function numeroDoGestor(instancia) {
  const g = gestoresNumero.find(x => x.instancia === instancia);
  return (g && g.numero) || "";
}

async function editarNumeroGestor(instancia) {
  const atual = numeroDoGestor(instancia);
  const novo = prompt("Número de WhatsApp desse gestor (DDI+DDD+número, usado pra receber envio de teste):", atual);
  if (novo === null) return;
  await fetch("/api/gestor/numero", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ instancia: instancia, numero: novo.trim() }),
  });
  const r = await fetch("/api/gestores");
  gestoresNumero = await r.json();
  render();
  toast("Número atualizado.");
}

function esc(s) {
  return (s || "").replace(/[&<>"']/g, function(m){
    return {"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[m];
  });
}

const STATUS_LABEL = {
  enviado: "✅ enviado", erro: "❌ erro", sem_trafego: "⏭️ sem tráfego", descartado: "🗑 descartado",
};

function pillEnvio(clienteId) {
  const ev = enviosUltimos[clienteId];
  if (!ev) return "<span class='pill status-nunca'>— nunca enviado</span>";
  const label = STATUS_LABEL[ev.status] || ev.status;
  const titulo = ev.detalhe ? esc(ev.detalhe) : "";
  return "<span class='pill status-" + ev.status + "' title=\"" + titulo + "\">" + label + " (" + esc(ev.periodo) + ")</span>";
}

function render() {
  const c = document.getElementById("listaGestores");
  c.innerHTML = "";
  const visiveis = clientesNaVisao();
  document.getElementById("contagem").textContent = "Clientes (" + visiveis.length + (visaoAtual !== "mestre" ? " · " + esc(visaoAtual) : "") + ")";
  document.getElementById("vazio").classList.toggle("hidden", visiveis.length > 0);

  const porGestor = {};
  visiveis.forEach(function(cl){
    const g = cl.gestor || "(sem gestor)";
    if (!porGestor[g]) porGestor[g] = [];
    porGestor[g].push(cl);
  });
  const nomesGestores = Object.keys(porGestor).sort(function(a,b){ return a.localeCompare(b); });

  nomesGestores.forEach(function(nomeG){
    const inst = (porGestor[nomeG][0] || {}).instancia || "";
    const conn = (instancias.find(x => x.name === inst) || {}).state || "?";
    const pill = conn === "open" ? "<span class='pill aberto'>● conectado</span>"
              : conn === "?"     ? ""
              : "<span class='pill fechado'>● " + esc(conn) + "</span>";

    const numero = numeroDoGestor(inst);
    const pillNumero = numero
      ? "<span class='pill' style='cursor:pointer;' onclick=\"editarNumeroGestor('" + inst + "')\" title='Clique pra editar'>📱 " + esc(numero) + "</span>"
      : "<span class='pill sem-numero' onclick=\"editarNumeroGestor('" + inst + "')\" title='Clique pra definir'>⚠️ sem número de teste</span>";

    const bloco = document.createElement("div");
    bloco.className = "gestor-bloco";
    bloco.innerHTML =
      "<div class='gestor-titulo'>" + esc(nomeG) + " <span style='color:var(--muted);text-transform:none;'>(" + esc(inst) + ")</span> " + pill + " " + pillNumero + "</div>" +
      "<table><thead><tr><th style='width:26px;'></th><th>Cliente</th><th>Fluxo</th><th>Grupo</th><th>Último relatório</th><th style='text-align:right;'>Ações</th></tr></thead><tbody></tbody></table>";
    const tb = bloco.querySelector("tbody");
    porGestor[nomeG].forEach(function(cl){
      const tr = document.createElement("tr");
      const fluxoLabel = cl.fluxo === "meta_ads" ? "Meta Ads" : "Dashgoo";
      const estiloTag = cl.estilo_mensagem ? " <span class='hint'>✎ estilo próprio</span>" : "";
      const podeSelecionar = cl.fluxo === "dashgoo";
      const chk = podeSelecionar
        ? "<input type='checkbox' " + (selecionadosClientes.has(cl.id) ? "checked" : "") + " onchange='toggleClienteSel(" + cl.id + ", this.checked)'>"
        : "<input type='checkbox' disabled title='Meta Ads roda pelo comando /relatorios-ads, não por aqui'>";
      tr.innerHTML = "<td>" + chk + "</td>" +
        "<td><strong>" + esc(cl.nome) + "</strong>" + estiloTag + "</td>" +
        "<td><span class='pill fluxo-" + cl.fluxo + "'>" + fluxoLabel + "</span></td>" +
        "<td>" + esc(cl.grupo_nome) + "<div class='grpid'>" + esc(cl.grupo_id) + "</div></td>" +
        "<td>" + pillEnvio(cl.id) + "</td>" +
        "<td style='text-align:right; white-space:nowrap;'>" +
        "<button class='btn-edit' onclick='editar(" + cl.id + ")'>Editar</button>" +
        "<button class='btn-del' onclick='excluir(" + cl.id + ")'>Excluir</button></td>";
      tb.appendChild(tr);
    });
    c.appendChild(bloco);
  });
  atualizarSelecaoClientes();
}

// ---------- Seleção avulsa de clientes (aba Clientes) — pra enviar manual
// só de quem o gestor escolher, ex: corrigiu um erro no mLabs depois da
// automação e quer reenviar só aquele cliente sem rodar todo mundo de novo.
function toggleClienteSel(id, checked) {
  if (checked) selecionadosClientes.add(id); else selecionadosClientes.delete(id);
  atualizarSelecaoClientes();
}
function limparSelecaoClientes() {
  selecionadosClientes.clear();
  render();
}
function atualizarSelecaoClientes() {
  const n = selecionadosClientes.size;
  document.getElementById("selClientesToolbar").classList.toggle("hidden", n === 0);
  document.getElementById("selClientesInfo").textContent = n + " selecionado(s)";
  document.getElementById("btnRodar").textContent = n ? "▶ Enviar " + n + " selecionado(s) agora" : "▶ Rodar agora (envio direto)";
}

// ---------- Form cliente ----------
// Nome do gestor pra exibir: 1) cadastro oficial em `gestores` (fonte da
// verdade), 2) se não tem, tenta puxar de algum cliente já cadastrado
// nessa instância, 3) senão mostra o nome técnico da instância mesmo.
function nomeExibicaoGestor(instanciaNome) {
  const g = gestoresNumero.find(x => x.instancia === instanciaNome);
  if (g) return g.nome;
  const usado = clientes.find(c => c.instancia === instanciaNome);
  return (usado && usado.gestor) || instanciaNome;
}
function instanciasSemNome() {
  return instancias.filter(inst => !gestoresNumero.find(g => g.instancia === inst.name)).map(inst => inst.name);
}
function preencherSelectGestores() {
  const sel = document.getElementById("inGestor");
  sel.innerHTML = "";
  instancias.forEach(function(inst){
    const op = document.createElement("option");
    const nomeGestor = nomeExibicaoGestor(inst.name);
    op.value = inst.name;
    op.textContent = nomeGestor + " (" + inst.name + ")";
    op.dataset.gestor = nomeGestor;
    sel.appendChild(op);
  });
  const semNome = instanciasSemNome();
  document.getElementById("avisoSemNome").classList.toggle("hidden", semNome.length === 0);
  document.getElementById("avisoSemNomeTexto").textContent =
    semNome.length + " instância(s) sem gestor nomeado ainda (mostrando o nome técnico).";
}
async function nomearInstanciasPendentes() {
  const pendentes = instanciasSemNome();
  for (const inst of pendentes) {
    const nome = prompt("Nome do gestor da instância '" + inst + "':");
    if (nome === null || !nome.trim()) continue;
    const numero = prompt("Número de WhatsApp de " + nome.trim() + " (opcional, usado pra receber teste):", "");
    if (numero === null) continue;
    await fetch("/api/gestor/numero", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ instancia: inst, nome: nome.trim(), numero: numero.trim() }),
    });
  }
  const r = await fetch("/api/gestores");
  gestoresNumero = await r.json();
  preencherSelectGestores();
  render();
  toast("Gestores nomeados!");
}

function onTrocarFluxo() {
  const fluxo = document.querySelector('input[name="fluxo"]:checked').value;
  document.getElementById("blocoAdAccount").classList.toggle("hidden", fluxo !== "meta_ads");
}

async function carregarGruposDoGestor(instancia, selecionado) {
  const sel = document.getElementById("inGrupo");
  const hint = document.getElementById("hintGrupos");
  sel.innerHTML = "<option>Carregando...</option>";
  hint.textContent = "";
  if (gruposCache[instancia]) {
    preencherGrupos(gruposCache[instancia], selecionado);
    return;
  }
  // Instâncias com muito histórico de conversa (ex: número pessoal) podem
  // demorar bastante nessa busca — depois de alguns segundos avisa que
  // ainda está carregando, pra não parecer que travou/deu erro.
  const avisoDemora = setTimeout(function(){
    hint.textContent = "ainda buscando... contas com muito histórico de conversa podem demorar até 2 min.";
  }, 6000);
  try {
    const r = await fetch("/api/grupos?instancia=" + encodeURIComponent(instancia));
    if (!r.ok) throw new Error("falha");
    const dados = await r.json();
    gruposCache[instancia] = dados;
    preencherGrupos(dados, selecionado);
    hint.textContent = "(" + dados.length + " grupos)";
  } catch (e) {
    sel.innerHTML = "";
    hint.textContent = "Erro ao buscar grupos dessa instância — confira se o Docker/Evolution está rodando e se essa instância está conectada, e tente de novo.";
  } finally {
    clearTimeout(avisoDemora);
  }
}

function preencherGrupos(grupos, selecionado) {
  const sel = document.getElementById("inGrupo");
  const filtro = (document.getElementById("filtroGrupo").value || "").toLowerCase();
  sel.innerHTML = "";
  grupos.filter(function(g){ return g.subject.toLowerCase().includes(filtro); })
        .forEach(function(g){
    const op = document.createElement("option");
    op.value = g.id; op.textContent = g.subject;
    if (g.id === selecionado) op.selected = true;
    sel.appendChild(op);
  });
}
function filtrarGrupos(){
  const inst = document.getElementById("inGestor").value;
  if (!inst) return;
  const sel = document.getElementById("inGrupo").value;
  preencherGrupos(gruposCache[inst] || [], sel);
}
function onTrocarGestor(){
  const inst = document.getElementById("inGestor").value;
  carregarGruposDoGestor(inst, null);
}

function abrirCliente() {
  editId = null;
  document.getElementById("tituloCliente").textContent = "Adicionar cliente";
  document.getElementById("inCliente").value = "";
  document.getElementById("inAdAccount").value = "";
  document.getElementById("inSaudacao").value = "";
  document.getElementById("inEstilo").value = "";
  document.getElementById("inStatus").value = "OK";
  document.getElementById("filtroGrupo").value = "";
  document.querySelector('input[name="fluxo"][value="dashgoo"]').checked = true;
  onTrocarFluxo();
  preencherSelectGestores();
  if (instancias.length === 0) {
    toast("Nenhum gestor cadastrado. Adicione um gestor primeiro.", true);
    return;
  }
  document.getElementById("modalCliente").classList.remove("hidden");
  onTrocarGestor();
  document.getElementById("inCliente").focus();
}
function editar(id) {
  editId = id;
  const c = clientes.find(x => x.id === id);
  document.getElementById("tituloCliente").textContent = "Editar cliente";
  document.getElementById("inCliente").value = c.nome;
  document.getElementById("inAdAccount").value = c.ad_account_id || "";
  document.getElementById("inSaudacao").value = c.saudacao_padrao || "";
  document.getElementById("inEstilo").value = c.estilo_mensagem || "";
  document.getElementById("inStatus").value = c.status || "OK";
  document.getElementById("filtroGrupo").value = "";
  document.querySelector('input[name="fluxo"][value="' + c.fluxo + '"]').checked = true;
  onTrocarFluxo();
  preencherSelectGestores();
  document.getElementById("inGestor").value = c.instancia;
  document.getElementById("modalCliente").classList.remove("hidden");
  carregarGruposDoGestor(c.instancia, c.grupo_id);
}
function fecharCliente(){ document.getElementById("modalCliente").classList.add("hidden"); }

async function salvarCliente() {
  const nome = document.getElementById("inCliente").value.trim();
  const fluxo = document.querySelector('input[name="fluxo"]:checked').value;
  const selG = document.getElementById("inGestor");
  const selGr = document.getElementById("inGrupo");
  if (!nome) { toast("Digite o nome do cliente.", true); return; }
  if (!selG.value) { toast("Escolha um gestor.", true); return; }
  if (!selGr.value) { toast("Escolha um grupo.", true); return; }
  const nomeGestor = selG.options[selG.selectedIndex].dataset.gestor || selG.value;
  const payload = {
    id: editId,
    nome: nome,
    gestor: nomeGestor,
    instancia: selG.value,
    grupo_nome: selGr.options[selGr.selectedIndex].text,
    grupo_id: selGr.value,
    fluxo: fluxo,
    ad_account_id: fluxo === "meta_ads" ? document.getElementById("inAdAccount").value.trim() : null,
    saudacao_padrao: document.getElementById("inSaudacao").value.trim() || null,
    estilo_mensagem: document.getElementById("inEstilo").value.trim() || null,
    status: document.getElementById("inStatus").value,
  };
  try {
    const r = await fetch("/api/cliente", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!r.ok) throw new Error("falha");
  } catch (e) { toast("Erro ao salvar no banco.", true); return; }
  fecharCliente();
  await carregar();
  toast(editId ? "Cliente atualizado!" : "Cliente adicionado!");
}

async function excluir(id) {
  const c = clientes.find(x => x.id === id);
  if (!confirm("Remover \"" + c.nome + "\" da lista de envio?")) return;
  await fetch("/api/cliente/excluir", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id: id }),
  });
  await carregar();
  toast("Cliente removido.");
}

// ---------- Fila de revisão ----------
async function carregarPendentes() {
  try {
    const r = await fetch("/api/pendentes");
    pendentes = await r.json();
  } catch (e) { pendentes = []; }
  const idsAtuais = new Set(pendentes.map(p => p.id));
  selecionados.forEach(id => { if (!idsAtuais.has(id)) selecionados.delete(id); });
  renderPendentes();
}

function renderPendentes() {
  const c = document.getElementById("listaPendentes");
  c.innerHTML = "";
  const visiveis = pendentesNaVisao();
  const badge = document.getElementById("badgeFila");
  badge.textContent = visiveis.length;
  badge.classList.toggle("hidden", visiveis.length === 0);
  document.getElementById("filaVazia").classList.toggle("hidden", visiveis.length > 0);
  document.getElementById("filaToolbar").classList.toggle("hidden", visiveis.length === 0);
  visiveis.forEach(function(p){
    const div = document.createElement("div");
    div.className = "pend-card" + (selecionados.has(p.id) ? " selecionado" : "");
    const fluxoLabel = p.fluxo === "meta_ads" ? "Meta Ads" : "Dashgoo";
    const marcado = selecionados.has(p.id) ? "checked" : "";
    const numeroGestor = numeroDoGestor(p.instancia);
    const avisoNumero = numeroGestor ? "" : " <span class='pill sem-numero' title='Sem número — teste vai falhar'>⚠️ sem número</span>";
    div.innerHTML =
      "<div class='pend-topo'>" +
      "<label class='pend-check'><input type='checkbox' " + marcado + " onchange='toggleSelecionado(" + p.id + ", this)'> <strong>" + esc(p.cliente_nome) + "</strong></label>" +
      " <span class='pill fluxo-" + p.fluxo + "'>" + fluxoLabel + "</span>" +
      " <span class='hint' style='margin:0;'>" + esc(p.periodo) + " · " + esc(p.gestor) + "</span>" + avisoNumero + "</div>" +
      "<label>Saudação</label><textarea data-campo='saudacao' data-id='" + p.id + "' style='min-height:40px;'>" + esc(p.saudacao) + "</textarea>" +
      "<label>Métricas</label><textarea data-campo='metricas' data-id='" + p.id + "' style='min-height:140px;'>" + esc(p.metricas) + "</textarea>" +
      "<label>Conclusão</label><textarea data-campo='conclusao' data-id='" + p.id + "' style='min-height:70px;'>" + esc(p.conclusao || "") + "</textarea>" +
      (p.pdf_path ? "<div class='hint'>PDF salvo em: " + esc(p.pdf_path) + "</div>" : "") +
      "<div class='acoes'>" +
      "<button class='btn-del' onclick='descartarPendente(" + p.id + ")'>Descartar</button>" +
      "<button class='btn-sec' onclick='salvarEdicaoPendente(" + p.id + ")'>Salvar edição</button>" +
      "</div>";
    c.appendChild(div);
  });
  atualizarToolbarFila();
}

// ---------- Seleção em lote (teste ou envio manual) ----------
// Manipula o DOM direto (não chama renderPendentes) pra não perder edições
// não salvas nas textareas dos outros cards.
function toggleSelecionado(id, checkboxEl) {
  if (checkboxEl.checked) selecionados.add(id); else selecionados.delete(id);
  atualizarToolbarFila();
  const card = checkboxEl.closest(".pend-card");
  if (card) card.classList.toggle("selecionado", checkboxEl.checked);
}
function selecionarTodos(marcado) {
  selecionados = new Set(marcado ? pendentesNaVisao().map(p => p.id) : []);
  document.querySelectorAll("#listaPendentes .pend-card").forEach(function(card){
    const chk = card.querySelector('input[type="checkbox"]');
    if (chk) chk.checked = marcado;
    card.classList.toggle("selecionado", marcado);
  });
  atualizarToolbarFila();
}
function atualizarToolbarFila() {
  const n = selecionados.size;
  document.getElementById("contagemSel").textContent = n + " selecionado(s)";
  document.getElementById("btnTesteSel").disabled = n === 0;
  document.getElementById("btnManualSel").disabled = n === 0;
  const visiveis = pendentesNaVisao().length;
  document.getElementById("chkTodos").checked = visiveis > 0 && n === visiveis;
}

async function _salvarEdicaoSilenciosa(id) {
  const campos = _lerCamposPendente(id);
  await fetch("/api/pendente/atualizar", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id: id, ...campos }),
  });
}

async function enviarTesteSelecionados() {
  const ids = Array.from(selecionados);
  if (ids.length === 0) return;
  if (!confirm("Enviar teste de " + ids.length + " mensagem(ns) pro WhatsApp PRIVADO de cada gestor (não vai pro cliente)?")) return;
  let ok = 0; const erros = [];
  for (const id of ids) {
    await _salvarEdicaoSilenciosa(id);
    try {
      const r = await fetch("/api/pendente/testar", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: id }),
      });
      const d = await r.json();
      if (d.erro) { erros.push(d.erro); } else { ok++; }
    } catch (e) { erros.push("erro de rede"); }
  }
  if (ok) toast(ok + " teste(s) enviado(s) pro privado do gestor!");
  if (erros.length) toast(erros[0], true);
  carregarPendentes();
}

async function enviarManualSelecionados() {
  const ids = Array.from(selecionados);
  if (ids.length === 0) return;
  if (!confirm("Enviar " + ids.length + " mensagem(ns) DE VERDADE pro grupo de cada cliente?")) return;
  let ok = 0; const erros = [];
  for (const id of ids) {
    await _salvarEdicaoSilenciosa(id);
    try {
      const r = await fetch("/api/pendente/enviar", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: id }),
      });
      const d = await r.json();
      if (d.erro) { erros.push(d.erro); } else { ok++; selecionados.delete(id); }
    } catch (e) { erros.push("erro de rede"); }
  }
  if (ok) toast(ok + " mensagem(ns) enviada(s)!");
  if (erros.length) toast(erros[0], true);
  carregarPendentes();
}

function _lerCamposPendente(id) {
  const campos = {};
  document.querySelectorAll('[data-id="' + id + '"]').forEach(function(el){
    campos[el.dataset.campo] = el.value;
  });
  return campos;
}

async function salvarEdicaoPendente(id) {
  const campos = _lerCamposPendente(id);
  await fetch("/api/pendente/atualizar", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id: id, ...campos }),
  });
  toast("Edição salva.");
  carregarPendentes();
}

async function descartarPendente(id) {
  if (!confirm("Descartar este rascunho sem enviar?")) return;
  await fetch("/api/pendente/descartar", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id: id }),
  });
  toast("Descartado.");
  carregarPendentes();
}

// ---------- Form gestor ----------
let pollQRTimer = null;
function abrirGestor() {
  document.getElementById("inNomeGestor").value = "";
  document.getElementById("inNumeroGestor").value = "";
  document.getElementById("passo1").classList.remove("hidden");
  document.getElementById("passo2").classList.add("hidden");
  document.getElementById("modalGestor").classList.remove("hidden");
  document.getElementById("inNomeGestor").focus();
}
function fecharGestor() {
  if (pollQRTimer) { clearInterval(pollQRTimer); pollQRTimer = null; }
  document.getElementById("modalGestor").classList.add("hidden");
  carregar();
}
async function criarGestor() {
  const nome = document.getElementById("inNomeGestor").value.trim();
  const numero = document.getElementById("inNumeroGestor").value.trim();
  if (!nome) { toast("Digite o nome do gestor.", true); return; }
  const btn = document.getElementById("btnCriarGestor");
  btn.disabled = true; btn.textContent = "Criando...";
  try {
    const r = await fetch("/api/criar_gestor", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ nome: nome, numero: numero }),
    });
    const d = await r.json();
    if (!r.ok || d.erro) {
      toast("Erro: " + (d.erro && d.erro.message ? d.erro.message : JSON.stringify(d.erro || "?")), true);
      btn.disabled = false; btn.textContent = "Criar instância";
      return;
    }
    document.getElementById("passo1").classList.add("hidden");
    document.getElementById("passo2").classList.remove("hidden");
    document.getElementById("instCriada").textContent = d.instancia;
    document.getElementById("instCriada2").textContent = d.instancia;
    document.getElementById("qrImg").src = d.qr_base64;
    monitorarConexao(d.instancia);
  } catch (e) {
    toast("Erro ao criar instância.", true);
    btn.disabled = false; btn.textContent = "Criar instância";
  }
}
function monitorarConexao(instancia) {
  let tentativas = 0;
  pollQRTimer = setInterval(async function(){
    tentativas++;
    try {
      const r = await fetch("/api/estado_instancia?instancia=" + encodeURIComponent(instancia));
      const d = await r.json();
      if (d.state === "open") {
        document.getElementById("statusConexao").innerHTML = "✅ Conectado!";
        clearInterval(pollQRTimer); pollQRTimer = null;
        toast("Gestor adicionado!");
        setTimeout(fecharGestor, 1200);
        return;
      } else {
        document.getElementById("statusConexao").textContent = "Esperando conexão... (" + tentativas + ")";
      }
    } catch (e) {}
    if (tentativas % 25 === 0) {
      try {
        const r2 = await fetch("/api/reqr?instancia=" + encodeURIComponent(instancia));
        const d2 = await r2.json();
        if (d2.qr_base64) document.getElementById("qrImg").src = d2.qr_base64;
      } catch (e) {}
    }
  }, 2000);
}

// ---------- Rodar (direto ou revisão) ----------
let pollRunTimer = null;
async function rodar(revisao) {
  const nomesSel = clientes.filter(c => selecionadosClientes.has(c.id)).map(c => c.nome);
  const alvo = nomesSel.length ? (nomesSel.length + " cliente(s) selecionado(s) (" + nomesSel.join(", ") + ")") : "TODOS os clientes Dashgoo com e-mail pendente";
  const msg = revisao
    ? "Gerar rascunhos AGORA (Dashgoo) pra " + alvo + "? Processa os e-mails, mas NÃO envia nada — só cria mensagens pra você revisar na aba \"Fila de revisão\"."
    : "Disparar a automação AGORA em modo produção pra " + alvo + "? Vai processar os e-mails Dashgoo e ENVIAR direto pros grupos.";
  if (!confirm(msg)) return;
  document.getElementById("tituloRun").textContent = (revisao ? "Gerando rascunhos" : "Execução manual (envio direto)") + (nomesSel.length ? " — " + nomesSel.length + " selecionado(s)" : "");
  document.getElementById("runLog").textContent = "";
  document.getElementById("runStatus").textContent = "Disparando...";
  document.getElementById("modalRun").classList.remove("hidden");
  try {
    const r = await fetch("/api/rodar", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ revisao: !!revisao, clientes: nomesSel }),
    });
    const d = await r.json();
    if (d.erro) { document.getElementById("runStatus").textContent = d.erro; return; }
  } catch (e) { document.getElementById("runStatus").textContent = "Erro ao disparar."; return; }
  pollRunTimer = setInterval(async function(){
    try {
      const r1 = await fetch("/api/log_run");
      const d1 = await r1.json();
      document.getElementById("runLog").textContent = d1.log || "";
      const pre = document.getElementById("runLog");
      pre.scrollTop = pre.scrollHeight;
      const r2 = await fetch("/api/estado_run");
      const d2 = await r2.json();
      if (!d2.rodando) {
        document.getElementById("runStatus").textContent = d2.rc === 0 ? "✅ Concluído (rc=0)" : "❌ Falhou (rc=" + d2.rc + ")";
        clearInterval(pollRunTimer); pollRunTimer = null;
        if (d2.rc === 0) selecionadosClientes.clear();
        carregar();
      } else {
        document.getElementById("runStatus").textContent = "⏳ Rodando...";
      }
    } catch (e) {}
  }, 1500);
}
function fecharRun() {
  if (pollRunTimer) { clearInterval(pollRunTimer); pollRunTimer = null; }
  document.getElementById("modalRun").classList.add("hidden");
}

// ---------- Toast ----------
let toastTimer;
function toast(msg, erro) {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.classList.toggle("erro", !!erro);
  t.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(function(){ t.classList.remove("show"); }, 2800);
}

carregar();
</script>
</body>
</html>'''


# =====================================================================
# Handler HTTP
# =====================================================================

class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        b = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _query(self):
        parsed = urllib.parse.urlsplit(self.path)
        return urllib.parse.parse_qs(parsed.query), parsed.path

    def log_message(self, *args):
        pass

    def do_GET(self):
        q, path = self._query()
        if path == "/" or path.startswith("/index"):
            self._send(200, HTML, "text/html")
        elif path == "/api/clientes":
            fluxo = (q.get("fluxo") or [None])[0]
            self._send(200, json.dumps(db.listar_clientes(fluxo=fluxo), ensure_ascii=False))
        elif path == "/api/pendentes":
            fluxo = (q.get("fluxo") or [None])[0]
            self._send(200, json.dumps(db.listar_pendentes(fluxo=fluxo), ensure_ascii=False))
        elif path == "/api/gestores":
            self._send(200, json.dumps(db.listar_gestores(), ensure_ascii=False))
        elif path == "/api/envios/ultimos":
            self._send(200, json.dumps(db.listar_ultimos_envios(), ensure_ascii=False))
        elif path == "/api/instancias":
            try:
                self._send(200, json.dumps(fetch_instancias(), ensure_ascii=False))
            except Exception as e:
                self._send(500, json.dumps({"erro": str(e)}))
        elif path == "/api/grupos":
            inst = (q.get("instancia") or [""])[0]
            if not inst:
                self._send(400, json.dumps({"erro": "instancia obrigatória"}))
                return
            try:
                self._send(200, json.dumps(fetch_grupos(inst), ensure_ascii=False))
            except Exception as e:
                self._send(500, json.dumps({"erro": str(e)}))
        elif path == "/api/estado_instancia":
            inst = (q.get("instancia") or [""])[0]
            try:
                self._send(200, json.dumps({"state": estado_instancia(inst)}))
            except Exception as e:
                self._send(500, json.dumps({"erro": str(e)}))
        elif path == "/api/reqr":
            inst = (q.get("instancia") or [""])[0]
            try:
                self._send(200, json.dumps(reqr_instancia(inst)))
            except Exception as e:
                self._send(500, json.dumps({"erro": str(e)}))
        elif path == "/api/estado_run":
            self._send(200, json.dumps(estado_run()))
        elif path == "/api/log_run":
            self._send(200, json.dumps({"log": ler_run_log()}))
        else:
            self._send(404, json.dumps({"erro": "rota nao encontrada"}))

    def do_POST(self):
        _q, path = self._query()
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length).decode("utf-8") if length else ""
        try:
            payload = json.loads(raw) if raw else {}
        except Exception:
            payload = {}

        if path == "/api/cliente":
            try:
                campos = dict(
                    nome=payload.get("nome", "").strip(),
                    gestor=payload.get("gestor", "").strip(),
                    instancia=payload.get("instancia", "").strip(),
                    grupo_nome=payload.get("grupo_nome", "").strip(),
                    grupo_id=payload.get("grupo_id", "").strip(),
                    fluxo=payload.get("fluxo", "dashgoo"),
                    ad_account_id=(payload.get("ad_account_id") or None),
                    status=payload.get("status") or "OK",
                    saudacao_padrao=(payload.get("saudacao_padrao") or None),
                    estilo_mensagem=(payload.get("estilo_mensagem") or None),
                )
                if payload.get("id"):
                    db.atualizar_cliente(payload["id"], **campos)
                else:
                    db.inserir_cliente(**campos)
                self._send(200, json.dumps({"ok": True}))
            except Exception as e:
                self._send(500, json.dumps({"erro": str(e)}))
        elif path == "/api/cliente/excluir":
            try:
                db.excluir_cliente(payload["id"])
                self._send(200, json.dumps({"ok": True}))
            except Exception as e:
                self._send(500, json.dumps({"erro": str(e)}))
        elif path == "/api/pendente/atualizar":
            try:
                db.atualizar_pendente(
                    payload["id"],
                    saudacao=payload.get("saudacao"),
                    metricas=payload.get("metricas"),
                    conclusao=payload.get("conclusao"),
                )
                self._send(200, json.dumps({"ok": True}))
            except Exception as e:
                self._send(500, json.dumps({"erro": str(e)}))
        elif path == "/api/pendente/descartar":
            try:
                pend = next((p for p in db.listar_pendentes(status="pendente") if p["id"] == payload["id"]), None)
                db.atualizar_pendente(payload["id"], status="descartado")
                if pend:
                    db.registrar_envio(pend["cliente_id"], pend["periodo"], "descartado")
                self._send(200, json.dumps({"ok": True}))
            except Exception as e:
                self._send(500, json.dumps({"erro": str(e)}))
        elif path == "/api/pendente/enviar":
            try:
                pend = next((p for p in db.listar_pendentes(status="pendente") if p["id"] == payload["id"]), None)
                if not pend:
                    self._send(404, json.dumps({"erro": "pendente não encontrado (já foi enviado/descartado?)"}))
                    return
                try:
                    enviar_whatsapp_texto(pend["grupo_id"], pend["saudacao"], pend["instancia"])
                    if pend.get("pdf_path") and os.path.exists(pend["pdf_path"]):
                        legenda = f"Segue relatório de performance dos anúncios de {pend['periodo']}"
                        enviar_whatsapp_documento(pend["grupo_id"], pend["instancia"], pend["pdf_path"], legenda)
                    enviar_whatsapp_texto(pend["grupo_id"], pend["metricas"], pend["instancia"])
                    if (pend.get("conclusao") or "").strip():
                        enviar_whatsapp_texto(pend["grupo_id"], pend["conclusao"], pend["instancia"])
                except Exception as e:
                    db.registrar_envio(pend["cliente_id"], pend["periodo"], "erro", detalhe=str(e)[:500])
                    raise
                db.atualizar_pendente(payload["id"], status="enviado")
                db.registrar_envio(pend["cliente_id"], pend["periodo"], "enviado")
                self._send(200, json.dumps({"ok": True}))
            except Exception as e:
                self._send(500, json.dumps({"erro": str(e)}))
        elif path == "/api/pendente/testar":
            try:
                pend = next((p for p in db.listar_pendentes(status="pendente") if p["id"] == payload["id"]), None)
                if not pend:
                    self._send(404, json.dumps({"erro": "pendente não encontrado (já foi enviado/descartado?)"}))
                    return
                gestor = db.buscar_gestor(pend["instancia"])
                numero_teste = gestor and gestor.get("numero")
                if not numero_teste:
                    self._send(400, json.dumps({
                        "erro": f"gestor '{pend['gestor']}' não tem número de WhatsApp cadastrado — "
                                f"clique no aviso ⚠️ ao lado do nome dele na aba Clientes pra definir."
                    }, ensure_ascii=False))
                    return
                # Manda pro PRÓPRIO gestor (não pro cliente) — não muda o status,
                # o rascunho continua na fila esperando o envio real.
                enviar_whatsapp_texto(numero_teste, f"🧪 [TESTE — {pend['cliente_nome']}]", pend["instancia"])
                enviar_whatsapp_texto(numero_teste, pend["saudacao"], pend["instancia"])
                if pend.get("pdf_path") and os.path.exists(pend["pdf_path"]):
                    legenda = f"Segue relatório de performance dos anúncios de {pend['periodo']}"
                    enviar_whatsapp_documento(numero_teste, pend["instancia"], pend["pdf_path"], legenda)
                enviar_whatsapp_texto(numero_teste, pend["metricas"], pend["instancia"])
                if (pend.get("conclusao") or "").strip():
                    enviar_whatsapp_texto(numero_teste, pend["conclusao"], pend["instancia"])
                self._send(200, json.dumps({"ok": True}))
            except Exception as e:
                self._send(500, json.dumps({"erro": str(e)}))
        elif path == "/api/criar_gestor":
            nome_humano = (payload.get("nome") or "").strip()
            numero = (payload.get("numero") or "").strip() or None
            if not nome_humano:
                self._send(400, json.dumps({"erro": "nome obrigatório"}))
                return
            instancia = f"comendo_{slug(nome_humano)}"
            res = criar_instancia(instancia)
            if "erro" in res:
                self._send(400, json.dumps(res, ensure_ascii=False))
                return
            db.upsert_gestor(instancia, nome_humano, numero)
            self._send(200, json.dumps(res, ensure_ascii=False))
        elif path == "/api/gestor/numero":
            try:
                instancia = payload["instancia"]
                numero = (payload.get("numero") or "").strip() or None
                nome = (payload.get("nome") or "").strip()
                if not nome:
                    gestor_existente = db.buscar_gestor(instancia)
                    nome = gestor_existente["nome"] if gestor_existente else instancia
                db.definir_numero_gestor(instancia, nome, numero)
                self._send(200, json.dumps({"ok": True}))
            except Exception as e:
                self._send(500, json.dumps({"erro": str(e)}))
        elif path == "/api/rodar":
            clientes_filtro = [n.strip() for n in (payload.get("clientes") or []) if n and n.strip()]
            res = iniciar_run(modo_revisao=bool(payload.get("revisao")), clientes_filtro=clientes_filtro)
            if "erro" in res:
                self._send(409, json.dumps(res, ensure_ascii=False))
                return
            self._send(200, json.dumps(res))
        else:
            self._send(404, json.dumps({"erro": "rota nao encontrada"}))


def main():
    host = config.PAINEL_HOST
    httpd = HTTPServer((host, PORT), Handler)
    url = f"http://{host}:{PORT}/"
    print(f"Painel rodando em {url}")
    print("Deixe esta janela aberta enquanto usa o painel.")
    print("Pra fechar, aperte Ctrl+C aqui (ou feche esta janela).")
    # Só abre o navegador sozinho em ambiente local (host de loopback).
    # Na nuvem (host 0.0.0.0) não há navegador — pula.
    if host in ("127.0.0.1", "localhost"):
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nPainel encerrado.")


if __name__ == "__main__":
    main()
