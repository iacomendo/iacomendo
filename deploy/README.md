# Deploy — Comendo MKT num VPS

Scaffolding pra rodar o stack (automação + painel + Evolution) num servidor
Linux sempre-ligado, no lugar do Mac. **Ainda não foi implantado em nenhum
servidor real** — isto é a preparação (Fase 4/5 do roteiro em `README.md`),
pronta pra usar quando um VPS for provisionado.

## Por que VPS e não serverless

O banco hoje é **SQLite** (arquivo em disco) — de propósito, o Postgres da
Fase 2 existe no código mas não está em uso ainda (decisão: sem Lovable por
enquanto). Um runner efêmero (GitHub Actions, Lambda, etc.) apagaria o
`clientes.db` a cada execução, então o agendamento **precisa** de um host
com disco persistente entre execuções — daí `systemd` timer em vez de cron
serverless. Se um dia migrar pra Postgres (`DATABASE_URL`), essa restrição
some e o agendamento pode virar serverless sem mudar código.

## Peças

| Arquivo | Pra quê |
|---|---|
| `../Dockerfile` | imagem do app Python (automação + painel) |
| `evolution/docker-compose.yml` | stack da Evolution API (WhatsApp) — Postgres + Redis próprios, separados do app |
| `systemd/comendo-relatorios.service` + `.timer` | roda o fluxo Dashgoo toda segunda 10h (substitui o `launchd` do Mac) |
| `systemd/comendo-painel.service` | mantém o painel web no ar continuamente |

## Passo a passo (quando for provisionar o VPS de verdade)

1. **Provisionar o servidor** (Railway/Render/Hetzner/DigitalOcean…) com
   Docker instalado, domínio/subdomínio apontado, e um proxy HTTPS na
   frente (Caddy é o mais simples — 1 linha de config por serviço).
2. **Evolution:** subir `evolution/docker-compose.yml` com uma
   `EVOLUTION_API_KEY` **nova** (rotacionada). Reconectar cada instância de
   gestor escaneando o QR de novo — sessões do Mac não migram.
3. **App:** clonar o repo em `/opt/comendo`, criar `.env` (a partir de
   `.env.example`) com `EVOLUTION_URL` apontando pra URL pública do passo 2,
   e as demais chaves (rotacionadas — ver `docs/HANDOFF.md` §10).
4. **Banco:** copiar o `clientes.db` atual pra `/opt/comendo/clientes.db`
   (ou rodar `comendo_db.py init` pra começar do zero).
5. **Systemd:** copiar as unidades de `systemd/` pra `/etc/systemd/system/`,
   ajustar `User`/`WorkingDirectory` se necessário, `daemon-reload`,
   `enable --now` nos dois timers/serviços.
6. **Rodar em paralelo com o Mac** por 1–2 semanas (Fase 6 do roteiro) antes
   de desligar o `launchd` local, conferindo que os relatórios saem
   corretamente dos dois lados.

## Segredos no VPS

Igual ao resto do projeto: nada hardcoded, tudo em `.env` no host (permissão
`600`, nunca commitado). Ver `.env.example` na raiz do repo.
