#!/usr/bin/env python3
"""
servidor.py — Serviço de narração da Comendo MKT.

Expõe o mesmo motor (scripts/narrar.py) em duas pontas:
  • Página web  ......  interface simples para o time (cola copy, escolhe voz, baixa MP3)
  • API JSON    ......  para o GPT personalizado (Action) e integrações

Rotas:
  GET  /?t=<token>        página web
  POST /api/narrar        {"texto","voz","tom","cliente"} -> {"url", "duracao", ...}
  GET  /audio/<id>.mp3    baixa/toca o áudio gerado
  GET  /openapi.json      esquema para configurar a Action do GPT personalizado
  GET  /saude             healthcheck

Autenticação: token compartilhado em NARRA_WEB_TOKEN.
  • API .......... header `X-API-Key: <token>`
  • Página web ... query string `?t=<token>` (o time salva o link nos favoritos)

Variáveis de ambiente:
  NARRA_WEB_TOKEN   token de acesso (obrigatório)
  NARRA_PUBLIC_URL  URL pública do serviço (entra no openapi.json)
  FISH_API_KEY      chave do Fish Audio (motor padrão)
  ELEVENLABS_API_KEY  chave da ElevenLabs (motor alternativo)
  PORT / NARRA_HOST bind (padrão 8080 / 127.0.0.1; na nuvem use 0.0.0.0)
"""
import html
import json
import os
import re
import subprocess
import sys
import tempfile
import unicodedata
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts"))
import narrar  # noqa: E402  (motor: mesma fonte da verdade do CLI)

BASE = os.path.dirname(os.path.abspath(__file__))
SAIDAS = os.path.join(BASE, "saidas")
TOKEN = os.environ.get("NARRA_WEB_TOKEN", "")
PUBLIC_URL = os.environ.get("NARRA_PUBLIC_URL", "").rstrip("/")
MOTOR = os.environ.get("NARRA_MOTOR", "fish")

# Vozes oferecidas na interface, por motor.
def vozes_disponiveis(motor: str):
    return sorted(narrar.VOZES_FISH) if motor == "fish" else sorted(narrar.VOZES)


def _slug(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-")
    return s[:60] or "narracao"


def gerar(texto: str, voz: str, tom: str, cliente: str, motor: str = None):
    """Gera o áudio e devolve (caminho, nome_arquivo, texto_motor). Levanta ValueError."""
    motor = motor or MOTOR
    if not texto.strip():
        raise ValueError("copy vazia")
    if tom not in narrar.TONS:
        raise ValueError(f"tom inválido: {tom}")

    if motor == "fish":
        ref = narrar.VOZES_FISH.get(voz)
        if not ref:
            raise ValueError(f"voz '{voz}' não existe no Fish Audio")
        chave = os.environ.get("FISH_API_KEY") or os.environ.get("FISHAUDIO_API_KEY")
        if not chave:
            raise ValueError("FISH_API_KEY não configurada no servidor")
    else:
        if voz not in narrar.VOZES:
            raise ValueError(f"voz '{voz}' não existe na ElevenLabs")
        chave = os.environ.get("ELEVENLABS_API_KEY")
        if not chave:
            raise ValueError("ELEVENLABS_API_KEY não configurada no servidor")

    # copy verbatim; só o texto do motor é abrasileirado
    texto_motor = narrar.abrasileirar(texto)

    os.makedirs(SAIDAS, exist_ok=True)
    nome = f"{_slug(cliente)}-{voz}-{tom}-{uuid.uuid4().hex[:8]}.mp3"
    destino = os.path.join(SAIDAS, nome)

    with tempfile.NamedTemporaryFile(suffix="_raw.mp3", delete=False) as tmp:
        raw = tmp.name
    try:
        if motor == "fish":
            narrar.gerar_tts_fish(texto_motor, ref, narrar.TONS_FISH[tom], chave, raw)
        else:
            narrar.gerar_tts(texto_motor, narrar.VOZES[voz], narrar.TONS[tom], chave, raw)
        try:
            narrar.acabamento(raw, destino, narrar.TONS[tom]["atempo"])
        except SystemExit:
            # sem ffmpeg: entrega o áudio cru em vez de falhar
            os.replace(raw, destino)
    finally:
        if os.path.exists(raw):
            try:
                os.remove(raw)
            except OSError:
                pass
    return destino, nome, texto_motor


def duracao(caminho: str):
    ff = os.environ.get("FFPROBE_BIN") or os.path.join(
        os.path.dirname(os.environ.get("FFMPEG_BIN", "")), "ffprobe")
    if not os.path.exists(ff):
        ff = "ffprobe"
    try:
        r = subprocess.run([ff, "-v", "error", "-show_entries", "format=duration",
                            "-of", "default=noprint_wrappers=1:nokey=1", caminho],
                           capture_output=True, text=True, timeout=30)
        return round(float(r.stdout.strip()), 1)
    except Exception:
        return None


def openapi(base_url: str) -> dict:
    return {
        "openapi": "3.1.0",
        "info": {"title": "Narração Comendo MKT",
                 "description": "Gera narração com voz clonada a partir da copy do time.",
                 "version": "1.0.0"},
        "servers": [{"url": base_url}],
        "paths": {
            "/api/narrar": {
                "post": {
                    "operationId": "gerarNarracao",
                    "summary": "Gera uma narração e devolve o link do MP3.",
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {
                            "type": "object",
                            "required": ["texto", "voz", "tom"],
                            "properties": {
                                "texto": {"type": "string",
                                          "description": "A copy, VERBATIM. Nunca reescrever."},
                                "voz": {"type": "string", "enum": vozes_disponiveis(MOTOR)},
                                "tom": {"type": "string",
                                        "enum": ["empolgada", "media", "calma"]},
                                "cliente": {"type": "string",
                                            "description": "Nome do cliente (para nomear o arquivo)."},
                            }}}},
                    },
                    "responses": {"200": {"description": "Áudio gerado",
                                          "content": {"application/json": {"schema": {
                                              "type": "object",
                                              "properties": {
                                                  "url": {"type": "string"},
                                                  "duracao": {"type": "number"},
                                                  "texto_narrado": {"type": "string"},
                                              }}}}}},
                }
            }
        },
        "components": {"securitySchemes": {"apiKey": {
            "type": "apiKey", "in": "header", "name": "X-API-Key"}}},
        "security": [{"apiKey": []}],
    }


PAGINA = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Narração — Comendo MKT</title><style>
*{box-sizing:border-box}
body{margin:0;font:16px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
background:#0f1115;color:#e8eaed;display:flex;justify-content:center;padding:24px}
.wrap{width:100%;max-width:680px}
h1{font-size:20px;margin:0 0 4px}
.sub{color:#9aa0a6;font-size:14px;margin:0 0 20px}
label{display:block;font-size:13px;color:#9aa0a6;margin:14px 0 6px}
textarea,select,input{width:100%;padding:11px 12px;border-radius:8px;
border:1px solid #2c313a;background:#171a21;color:#e8eaed;font:inherit}
textarea{min-height:160px;resize:vertical}
.row{display:flex;gap:12px}.row>div{flex:1}
button{margin-top:18px;width:100%;padding:13px;border:0;border-radius:8px;
background:#e8590c;color:#fff;font:600 16px system-ui;cursor:pointer}
button:disabled{opacity:.55;cursor:progress}
.card{margin-top:20px;padding:16px;border:1px solid #2c313a;border-radius:10px;
background:#171a21;display:none}
.card.on{display:block}
audio{width:100%;margin:10px 0}
a.dl{display:inline-block;padding:9px 14px;background:#2c313a;color:#e8eaed;
border-radius:7px;text-decoration:none;font-size:14px}
.err{color:#ff8a80;font-size:14px;margin-top:12px;display:none}
.err.on{display:block}
.hint{color:#6b7280;font-size:12px;margin-top:6px}
@media(prefers-color-scheme:light){body{background:#f6f7f9;color:#1f2328}
textarea,select,input{background:#fff;border-color:#d5d9e0;color:#1f2328}
.card{background:#fff;border-color:#d5d9e0}a.dl{background:#eceff3;color:#1f2328}}
</style></head><body><div class="wrap">
<h1>🎙️ Narração — Comendo MKT</h1>
<p class="sub">Cole a copy do time. Ela é narrada <b>exatamente como está</b>.</p>
<label>Cliente</label><input id="cliente" placeholder="Ex.: Cantinho da Comida Caseira">
<label>Copy</label><textarea id="texto" placeholder="Cole aqui a copy..."></textarea>
<div class="row">
<div><label>Voz</label><select id="voz">__VOZES__</select></div>
<div><label>Tom</label><select id="tom">
<option value="empolgada">Empolgada — promoção, fast food, jovem</option>
<option value="media" selected>Média — acolhedor, família</option>
<option value="calma">Calma — premium, ticket alto</option>
</select></div></div>
<button id="go">Gerar narração</button>
<div class="err" id="err"></div>
<div class="card" id="card">
<div id="meta" class="sub" style="margin:0 0 6px"></div>
<audio id="player" controls></audio>
<a class="dl" id="dl" download>⬇ Baixar MP3</a>
<div class="hint" id="narrado"></div>
</div></div><script>
const $=i=>document.getElementById(i);
const token=new URLSearchParams(location.search).get('t')||'';
$('go').onclick=async()=>{
 const texto=$('texto').value.trim();
 $('err').className='err';$('card').className='card';
 if(!texto){$('err').textContent='Cole a copy antes de gerar.';$('err').className='err on';return}
 $('go').disabled=true;$('go').textContent='Gerando...';
 try{
  const r=await fetch('/api/narrar',{method:'POST',
   headers:{'Content-Type':'application/json','X-API-Key':token},
   body:JSON.stringify({texto,voz:$('voz').value,tom:$('tom').value,cliente:$('cliente').value})});
  const j=await r.json();
  if(!r.ok){throw new Error(j.erro||('Falha '+r.status))}
  $('player').src=j.url;$('dl').href=j.url;
  $('meta').textContent=(j.duracao?j.duracao+'s · ':'')+$('voz').value+' · '+$('tom').value;
  $('narrado').textContent='Texto narrado: '+j.texto_narrado;
  $('card').className='card on';
 }catch(e){$('err').textContent=e.message;$('err').className='err on'}
 $('go').disabled=false;$('go').textContent='Gerar narração';
};</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    server_version = "NarracaoComendo/1.0"

    def log_message(self, fmt, *a):  # log enxuto
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % a))

    # ---------- helpers ----------
    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _autorizado(self, qs=None):
        if not TOKEN:
            return True  # sem token configurado: modo local aberto
        if self.headers.get("X-API-Key") == TOKEN:
            return True
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer ") and auth[7:] == TOKEN:
            return True
        if qs and qs.get("t", [None])[0] == TOKEN:
            return True
        return False

    def _base_url(self):
        if PUBLIC_URL:
            return PUBLIC_URL
        host = self.headers.get("Host", "localhost")
        return f"http://{host}"

    # ---------- rotas ----------
    def do_GET(self):
        u = urlparse(self.path)
        qs = parse_qs(u.query)

        if u.path == "/saude":
            return self._json(200, {"ok": True, "motor": MOTOR,
                                    "vozes": vozes_disponiveis(MOTOR)})

        if u.path == "/openapi.json":
            return self._json(200, openapi(self._base_url()))

        if u.path == "/":
            if not self._autorizado(qs):
                self.send_response(401); self.end_headers()
                return self.wfile.write("Acesso negado. Use o link com ?t=TOKEN".encode())
            opts = "".join(
                f'<option value="{html.escape(v)}">{html.escape(v.capitalize())}</option>'
                for v in vozes_disponiveis(MOTOR))
            body = PAGINA.replace("__VOZES__", opts).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            return self.wfile.write(body)

        if u.path.startswith("/audio/"):
            nome = os.path.basename(u.path)
            caminho = os.path.join(SAIDAS, nome)
            if not os.path.isfile(caminho):
                return self._json(404, {"erro": "áudio não encontrado"})
            dados = open(caminho, "rb").read()
            self.send_response(200)
            self.send_header("Content-Type", "audio/mpeg")
            self.send_header("Content-Length", str(len(dados)))
            self.send_header("Content-Disposition", f'inline; filename="{nome}"')
            self.end_headers()
            return self.wfile.write(dados)

        return self._json(404, {"erro": "rota não encontrada"})

    def do_POST(self):
        u = urlparse(self.path)
        if u.path != "/api/narrar":
            return self._json(404, {"erro": "rota não encontrada"})
        if not self._autorizado(parse_qs(u.query)):
            return self._json(401, {"erro": "não autorizado (X-API-Key)"})
        try:
            n = int(self.headers.get("Content-Length", 0))
            dados = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
        except Exception:
            return self._json(400, {"erro": "JSON inválido"})

        try:
            caminho, nome, texto_motor = gerar(
                dados.get("texto", ""), dados.get("voz", ""),
                dados.get("tom", "media"), dados.get("cliente", ""))
        except ValueError as e:
            return self._json(400, {"erro": str(e)})
        except SystemExit:
            return self._json(502, {"erro": "o motor de voz recusou a requisição "
                                            "(verifique crédito/chave da API)"})
        except Exception as e:
            return self._json(500, {"erro": f"falha ao gerar: {e}"})

        return self._json(200, {"url": f"{self._base_url()}/audio/{nome}",
                                "arquivo": nome,
                                "duracao": duracao(caminho),
                                "texto_narrado": texto_motor})


def main():
    host = os.environ.get("NARRA_HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8080"))
    if not TOKEN:
        print("AVISO: NARRA_WEB_TOKEN não definido — servidor SEM autenticação "
              "(use apenas local).", file=sys.stderr)
    os.makedirs(SAIDAS, exist_ok=True)
    print(f"Narração Comendo em http://{host}:{port}/  (motor: {MOTOR})")
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
