#!/usr/bin/env python3
"""
narrar.py — Gera narração com voz clonada (ElevenLabs) para a Comendo MKT.

Parâmetros validados no handoff do Sistema de Narração (§6, §7, §8).
Regra de ouro: a copy do time entra VERBATIM. A camada de pronúncia
(abrasileirar) é aplicada SÓ ao texto que vai ao motor de voz.

Uso:
    python3 narrar.py --voz vitoria --tom empolgada --arquivo texto.txt --saida saida.mp3
    echo "sua copy" | python3 narrar.py --voz vitoria --tom media --saida saida.mp3

Flags:
    --voz     vitoria|lucas|francis|daniel|eduardo
    --tom     empolgada|media|calma
    --arquivo caminho do .txt com a copy (ou use stdin)
    --texto   passa a copy direto na linha de comando
    --saida   caminho do .mp3 de saída
    --sem-acabamento   pula o processamento de áudio (domador de picos + ritmo)
    --sem-pronuncia    pula a camada de abrasileiramento automática
    --mostrar-texto    imprime o texto que será enviado ao motor e sai (dry-run)
"""
import argparse
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
import urllib.error

# ---------------------------------------------------------------------------
# 1. Vozes (§3 do handoff)
# ---------------------------------------------------------------------------
VOZES = {
    "vitoria": "ybcErWwDz8ZBwtYt8cwD",   # Narradora oficial (feminina) — Aprovada
    "lucas":   "JrsSi780rKB0vvPdkEsF",   # Voz do Lucas (masculina) — Aprovada
    "francis": "EfZInModTDcSzE4ZSGRb",   # Francis, CEO — reprovada (robótica)
    "daniel":  "czvzJwIVS2asEKnthV40",   # BR masculina genérica — interina
    "eduardo": "83Nae6GFQiNslSbuzmE7",   # BR masculina genérica — interina
}

# ---------------------------------------------------------------------------
# 2. Tons — parâmetros de geração (§6 do handoff)
#    Modelo: eleven_multilingual_v2  (NUNCA eleven_v3 — inventa sotaque)
# ---------------------------------------------------------------------------
TONS = {
    "empolgada": {"stability": 0.40, "similarity_boost": 0.90, "style": 0.35, "atempo": 1.10},
    "media":     {"stability": 0.55, "similarity_boost": 0.90, "style": 0.15, "atempo": 1.10},
    "calma":     {"stability": 0.70, "similarity_boost": 0.90, "style": 0.10, "atempo": 1.12},
}
MODELO = "eleven_multilingual_v2"
OUTPUT_FORMAT = "mp3_44100_128"  # máximo do plano Starter

# ---------------------------------------------------------------------------
# 3. Camada de pronúncia — abrasileirar (§7 do handoff)
#    Regex com \b para não pegar dentro de outras palavras. case-insensitive.
#    Aplicada SÓ ao texto que vai ao motor. A copy original fica intacta.
# ---------------------------------------------------------------------------
SUBS_PRONUNCIA = [
    (r"\bdelivery\b",      "delíveri"),      # validado (erraram delivéri/delivêri)
    (r"\bcatupiry\b",      "catupirí"),      # validado (oxítona)
    (r"\bself[- ]service\b", "sélfi sérvice"),  # a confirmar
    (r"\bSeo\b",           "Seu"),            # Seo Venâncio = Seu, não "Céu"
    (r"\bEur[íi]pes\b",    "Eurípes"),        # acentuar p/ tônica correta (handoff §7)
    (r"\bValença\s+1\b",   "Valença um"),     # números por extenso
]

def substituir_500g(texto: str) -> str:
    """500g -> quinhentos gramas (validado). Trata Ng genérico simples."""
    mapa = {"0": "zero", "1": "um", "2": "dois", "3": "três", "4": "quatro",
            "5": "cinco", "6": "seis", "7": "sete", "8": "oito", "9": "nove"}
    def rep(m):
        num = m.group(1)
        if num == "500":
            return "quinhentos gramas"
        return f"{num} gramas"
    return re.sub(r"\b(\d+)\s*g\b", rep, texto)


def abrasileirar(texto: str) -> str:
    """Aplica a camada de pronúncia. Retorna o texto adaptado foneticamente."""
    out = texto
    for pat, sub in SUBS_PRONUNCIA:
        out = re.sub(pat, sub, out, flags=re.IGNORECASE)
    out = substituir_500g(out)
    return out


# ---------------------------------------------------------------------------
# 4. Geração via API
# ---------------------------------------------------------------------------
def gerar_tts(texto: str, voice_id: str, tom: dict, api_key: str, destino_raw: str):
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}?output_format={OUTPUT_FORMAT}"
    payload = {
        "text": texto,
        "model_id": MODELO,
        "voice_settings": {
            "stability": tom["stability"],
            "similarity_boost": tom["similarity_boost"],
            "style": tom["style"],
            "use_speaker_boost": True,
        },
    }
    import json
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("xi-api-key", api_key)
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "audio/mpeg")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            with open(destino_raw, "wb") as f:
                f.write(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        print(f"ERRO ElevenLabs {e.code}: {body}", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# 5. Acabamento de áudio (§8 do handoff) — via ffmpeg
#    Domador de picos (sempre) + ritmo enxuto (silenceremove + atempo).
# ---------------------------------------------------------------------------
def acabamento(entrada_mp3: str, saida_mp3: str, atempo: float):
    ffmpeg = os.environ.get("FFMPEG_BIN", "ffmpeg")
    filtro = (
        # domador de picos (evita estouros tipo "Reúna")
        "acompressor=threshold=-16dB:ratio=3.5:attack=8:release=180:makeup=1.5,"
        "alimiter=limit=0.9,"
        # ritmo enxuto: remove silêncios longos internos
        "silenceremove=stop_periods=-1:stop_duration=0.15:stop_threshold=-34dB:stop_silence=0.10,"
        # aceleração uniforme
        f"atempo={atempo}"
    )
    cmd = [ffmpeg, "-y", "-i", entrada_mp3, "-af", filtro,
           "-c:a", "libmp3lame", "-b:a", "128k", "-ar", "44100", saida_mp3]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print("ERRO ffmpeg:\n" + r.stderr[-2000:], file=sys.stderr)
        sys.exit(1)


def main():
    ap = argparse.ArgumentParser(description="Narração com voz clonada (Comendo MKT)")
    ap.add_argument("--voz", required=True, choices=list(VOZES.keys()))
    ap.add_argument("--tom", required=True, choices=list(TONS.keys()))
    ap.add_argument("--arquivo", help="caminho do .txt com a copy")
    ap.add_argument("--texto", help="copy passada direto")
    ap.add_argument("--saida", help="caminho do .mp3 de saída (obrigatório exceto em --mostrar-texto)")
    ap.add_argument("--sem-acabamento", action="store_true")
    ap.add_argument("--sem-pronuncia", action="store_true")
    ap.add_argument("--mostrar-texto", action="store_true",
                    help="imprime o texto que iria ao motor e sai (dry-run)")
    args = ap.parse_args()

    # 1. obter a copy (verbatim)
    if args.arquivo:
        with open(args.arquivo, "r", encoding="utf-8") as f:
            copy = f.read().strip()
    elif args.texto:
        copy = args.texto.strip()
    elif not sys.stdin.isatty():
        copy = sys.stdin.read().strip()
    else:
        print("ERRO: forneça --arquivo, --texto ou stdin", file=sys.stderr)
        sys.exit(2)

    if not copy:
        print("ERRO: copy vazia", file=sys.stderr)
        sys.exit(2)

    # 2. camada de pronúncia (só no texto do motor)
    texto_motor = copy if args.sem_pronuncia else abrasileirar(copy)

    if args.mostrar_texto:
        print("=== COPY ORIGINAL (verbatim) ===")
        print(copy)
        print("\n=== TEXTO ENVIADO AO MOTOR (abrasileirado) ===")
        print(texto_motor)
        return

    if not args.saida:
        print("ERRO: --saida é obrigatório", file=sys.stderr)
        sys.exit(2)

    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        print("ERRO: defina ELEVENLABS_API_KEY no ambiente", file=sys.stderr)
        sys.exit(2)

    voice_id = VOZES[args.voz]
    tom = TONS[args.tom]

    os.makedirs(os.path.dirname(os.path.abspath(args.saida)), exist_ok=True)

    # 3. gerar
    with tempfile.NamedTemporaryFile(suffix="_raw.mp3", delete=False) as tmp:
        raw = tmp.name
    gerar_tts(texto_motor, voice_id, tom, api_key, raw)

    # 4. acabamento
    if args.sem_acabamento:
        os.replace(raw, args.saida)
    else:
        acabamento(raw, args.saida, tom["atempo"])
        os.remove(raw)

    print(f"OK: {args.saida}  (voz={args.voz}, tom={args.tom}, "
          f"acabamento={'nao' if args.sem_acabamento else 'sim'})")


if __name__ == "__main__":
    main()
