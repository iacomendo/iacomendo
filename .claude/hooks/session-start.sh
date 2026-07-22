#!/bin/bash
# SessionStart hook — prepara o ambiente do Sistema de Narração da Comendo.
#
# Faz, de forma idempotente:
#   1. Instala o ffmpeg estático em ~/.local/bin (se ainda não houver).
#   2. Persiste FFMPEG_BIN e PATH para toda a sessão (via CLAUDE_ENV_FILE).
#   3. Valida a ELEVENLABS_API_KEY — aceita a chave vinda de:
#        (a) variável de ambiente do environment (recomendado), ou
#        (b) arquivo .env na raiz do repo (gitignorado).
#      Não derruba a sessão se faltar — só avisa, pra não travar o chat.
set -uo pipefail

# roda só no ambiente remoto (Claude Code na web)
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

ROOT="${CLAUDE_PROJECT_DIR:-$(pwd)}"
BIN_DIR="$HOME/.local/bin"
mkdir -p "$BIN_DIR"

# ---------------------------------------------------------------------------
# 1. ffmpeg
# ---------------------------------------------------------------------------
if [ ! -x "$BIN_DIR/ffmpeg" ]; then
  echo "[narra] instalando ffmpeg estático..."
  TMP="$(mktemp -d)"
  URL="https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"
  if curl -sSL -m 180 -o "$TMP/ffmpeg.tar.xz" "$URL"; then
    if tar xf "$TMP/ffmpeg.tar.xz" -C "$TMP"; then
      cp "$TMP"/ffmpeg-*-static/ffmpeg "$BIN_DIR/" 2>/dev/null || true
      cp "$TMP"/ffmpeg-*-static/ffprobe "$BIN_DIR/" 2>/dev/null || true
      chmod +x "$BIN_DIR/ffmpeg" "$BIN_DIR/ffprobe" 2>/dev/null || true
      echo "[narra] ffmpeg instalado em $BIN_DIR"
    else
      echo "[narra] AVISO: falha ao extrair ffmpeg (siga sem — o acabamento de áudio não vai funcionar)"
    fi
  else
    echo "[narra] AVISO: falha ao baixar ffmpeg (siga sem — o acabamento de áudio não vai funcionar)"
  fi
  rm -rf "$TMP"
else
  echo "[narra] ffmpeg já presente em $BIN_DIR"
fi

# ---------------------------------------------------------------------------
# 2. Persistir ambiente para a sessão
# ---------------------------------------------------------------------------
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  {
    echo "export PATH=\"$BIN_DIR:\$PATH\""
    if [ -x "$BIN_DIR/ffmpeg" ]; then
      echo "export FFMPEG_BIN=\"$BIN_DIR/ffmpeg\""
    fi
  } >> "$CLAUDE_ENV_FILE"
fi

# ---------------------------------------------------------------------------
# 3. Validar a chave (secret do environment OU .env)
# ---------------------------------------------------------------------------
KEY="${ELEVENLABS_API_KEY:-}"
if [ -z "$KEY" ] && [ -f "$ROOT/.env" ]; then
  # tenta ler do .env sem executá-lo por completo
  KEY="$(grep -E '^\s*ELEVENLABS_API_KEY=' "$ROOT/.env" | tail -1 | cut -d= -f2- | tr -d '"'\''[:space:]')"
  if [ -n "$KEY" ] && [ -n "${CLAUDE_ENV_FILE:-}" ]; then
    # torna a chave do .env disponível para toda a sessão
    echo "export ELEVENLABS_API_KEY=\"$KEY\"" >> "$CLAUDE_ENV_FILE"
  fi
fi

if [ -z "$KEY" ]; then
  echo "[narra] AVISO: ELEVENLABS_API_KEY não encontrada."
  echo "[narra]        Configure-a como variável do environment (recomendado)"
  echo "[narra]        ou crie um .env a partir de .env.example. Sem ela, a geração de áudio não roda."
else
  echo "[narra] ELEVENLABS_API_KEY presente ✓"
fi

echo "[narra] ambiente pronto."
exit 0
