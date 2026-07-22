# Comendo MKT — Automação de Relatórios (migração para nuvem)

Automação de tráfego pago da Comendo MKT: relatórios semanais no WhatsApp do
cliente (fluxo Dashgoo e fluxo Meta Ads direto) + auditoria de qualidade.

Este repositório é a **reimplementação para nuvem** do protótipo que hoje roda
localmente no Mac. O código foi trazido do stack local e está sendo adaptado,
fase a fase, para rodar em servidor sempre-ligado, com segredos fora do código
e banco gerenciado.

> Contexto completo da operação: `docs/OPERACAO-COMENDO-MKT.md`,
> `docs/HANDOFF.md`, `docs/POP_META_ADS.md`.

---

## Arquitetura: local (hoje) × nuvem (destino)

| Peça | Local (Mac) | Nuvem (destino) |
|---|---|---|
| WhatsApp (Evolution) | Docker em `localhost:8080` | servidor sempre-ligado, URL pública |
| Banco | SQLite (`clientes.db`) | Postgres gerenciado (Supabase) |
| Ingestão Dashgoo | Gmail OAuth + Playwright, local | backend lendo Gmail por API |
| Agendador | `launchd` (seg 10h) | cron do provedor / GitHub Actions |
| Segredos | hardcoded / arquivos | variáveis de ambiente / secret store |
| Chamada de IA | chave no `.py` | chave em backend (env) |

O código é o mesmo dos dois lados — o que muda é **de onde vem a
configuração**. Tudo passa por `config.py`, que lê variáveis de ambiente.

---

## Configuração (`config.py` + `.env`)

Nenhum segredo fica no código. Toda config vem de variáveis de ambiente,
centralizadas em `config.py`.

**Dev local:**
```bash
cp .env.example .env      # preencha com os valores reais
pip install -r requirements.txt
```

**Nuvem:** defina as mesmas variáveis no secret store do provedor (sem `.env`).

Variáveis principais (ver `.env.example` para a lista completa):

| Variável | Para quê |
|---|---|
| `ANTHROPIC_API_KEY` | resumo das métricas (Claude) |
| `EVOLUTION_URL` / `EVOLUTION_API_KEY` | WhatsApp (local `localhost:8080` ou URL pública) |
| `GOOGLE_TOKEN_JSON` / `GOOGLE_CREDENTIALS_JSON` | Gmail+Drive por env (nuvem) |
| `GOOGLE_TOKEN_PATH` / `GOOGLE_CREDENTIALS_PATH` | Gmail+Drive por arquivo (local) |
| `DATABASE_URL` | Postgres (nuvem) — quando ausente, usa SQLite `DB_PATH` |
| `PAINEL_HOST` / `PORT` | bind do painel (local `127.0.0.1`, nuvem `0.0.0.0`) |
| `NUMEROS_GESTORES` / `MEU_NUMERO` | fallback de números de gestor |

### Segredos — ⚠️ importante

Nunca são versionados (ver `.gitignore`): `token.json`, `credentials.json`,
`clientes.db`, CSVs, `.env`.

As chaves que existiam **em texto puro** no protótipo (Anthropic, Evolution,
`client_secret` Google, tokens OAuth) **devem ser rotacionadas** antes de ir
pra produção, porque já circularam. Ver `docs/HANDOFF.md` §10.

---

## Componentes

| Arquivo | O que é |
|---|---|
| `config.py` | configuração central (env vars) |
| `comendo_db.py` | camada de dados — a **única** porta pro banco (CRUD + CLI) |
| `relatorios_automacao.py` | fluxo Dashgoo: Gmail → PDF → Claude → Drive → WhatsApp |
| `enviar_ads.py` | envio do fluxo Meta Ads direto |
| `painel.py` | painel web (cadastro, fila de revisão, disparo manual) |
| `logar_google.py` | gera `token.json` (OAuth) — rodar uma vez, local |
| `backfill_envios_gmail.py` | reconstrói histórico de envio a partir do Gmail |
| `adicionar_cliente.py`, `listar_grupos*.py`, `pegar_id_grupo.py` | utilitários |

O banco tem 4 tabelas: `clientes`, `gestores`, `envios`, `mensagens_pendentes`.
Como todo acesso passa por `comendo_db.py`, migrar SQLite → Postgres é trocar
**um** arquivo, sem tocar no resto.

---

## Roteiro da migração (fases)

- [x] **Fase 1 — Fundação cloud-ready.** Código no repositório; toda
  configuração externalizada em env vars (`config.py`); segredos protegidos
  (`.gitignore`); `EVOLUTION_URL` e credenciais Google já preparados para
  URL pública / env. *(esta entrega)*
- [ ] **Fase 2 — Banco na nuvem.** `comendo_db.py` ganha backend Postgres
  quando `DATABASE_URL` estiver definida; migração do schema + dados do
  `clientes.db` atual para o Postgres gerenciado (Supabase).
- [ ] **Fase 3 — Ingestão Dashgoo.** Gmail por API no backend (ou webhook
  Dashgoo), sem depender de máquina pessoal.
- [ ] **Fase 4 — Agendador + segredos no backend.** Cron do provedor;
  segredos no secret store; alerta de falha (hoje inexistente).
- [ ] **Fase 5 — Evolution na nuvem.** Servidor sempre-ligado; reconexão de
  cada instância; teste em grupo de teste antes de tocar cliente real.
- [ ] **Fase 6 — Virada.** Rodar em paralelo com o Mac por 1–2 semanas antes
  de desligar o stack local.

Detalhe do que o produto final precisa cobrir: `docs/HANDOFF.md` §11.
