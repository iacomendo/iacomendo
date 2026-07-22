# Imagem da automação Comendo MKT (fluxo Dashgoo + Meta Ads + painel).
#
# Pensada pra rodar num VPS sempre-ligado (Fase 5), lado a lado com a
# Evolution API (ver deploy/evolution/docker-compose.yml). O agendamento
# (Fase 4) fica por conta do host — ver deploy/systemd/ — porque o SQLite
# (clientes.db) é um arquivo em disco: precisa persistir entre execuções,
# o que um runner efêmero (ex.: GitHub Actions) não oferece. Se um dia
# migrar pra Postgres (DATABASE_URL), essa restrição deixa de existir e o
# agendamento pode virar serverless sem mudar uma linha de código.
FROM python:3.12-slim

WORKDIR /app

# Dependências de sistema do Playwright (renderização/download do PDF do Dashgoo).
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget gnupg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install --with-deps chromium

COPY . .

# clientes.db (SQLite) e a saída de mensagens vivem num volume persistente —
# ver o comentário de VOLUME no docker-compose de exemplo mais abaixo.
VOLUME ["/app/data"]
ENV DB_PATH=/app/data/clientes.db
ENV PASTA_SAIDA_MENSAGENS=/app/data/relatorios_saida

# Painel web (porta configurável via PORT/PAINEL_PORT — ver config.py).
EXPOSE 8077
ENV PAINEL_HOST=0.0.0.0

CMD ["python3", "painel.py"]
