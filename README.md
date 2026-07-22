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
| `comendo_db.py` | camada de dados — a **única** porta pro banco (CRUD + CLI); backend SQLite ou Postgres |
| `migrar_para_postgres.py` | migra os dados do `clientes.db` local para o Postgres de destino |
| `relatorios_automacao.py` | fluxo Dashgoo: Gmail → PDF → Claude → Drive → WhatsApp |
| `enviar_ads.py` | envio do fluxo Meta Ads direto |
| `painel.py` | painel web (cadastro, fila de revisão, disparo manual) |
| `logar_google.py` | gera `token.json` (OAuth) — rodar uma vez, local |
| `backfill_envios_gmail.py` | reconstrói histórico de envio a partir do Gmail |
| `adicionar_cliente.py`, `listar_grupos*.py`, `pegar_id_grupo.py` | utilitários |

O banco tem 4 tabelas: `clientes`, `gestores`, `envios`, `mensagens_pendentes`.
Como todo acesso passa por `comendo_db.py`, o backend é escolhido em runtime:
**SQLite** (padrão, `DB_PATH`) quando `DATABASE_URL` está ausente, **Postgres**
quando está definida. O resto do código (painel, automação, CLI) não muda —
usa as mesmas funções (`listar_clientes`, `inserir_cliente`, etc.) nos dois casos.

### Banco de dados — SQLite → Postgres

Pra migrar o `clientes.db` local para um Postgres (ex.: Supabase):

```bash
export DATABASE_URL=postgresql://usuario:senha@host:5432/banco

# 1. Confira o que seria migrado, sem gravar nada:
python3 migrar_para_postgres.py --sqlite-path clientes.db --dry-run

# 2. Rode de verdade:
python3 migrar_para_postgres.py --sqlite-path clientes.db
```

O script cria o schema no Postgres (se não existir), copia `clientes`,
`gestores`, `envios` e `mensagens_pendentes` **preservando os ids originais**
(essencial pra manter as referências `cliente_id` de `envios`/
`mensagens_pendentes` intactas) e ajusta as sequences pro próximo id
automático não colidir. É idempotente — rodar de novo só pula quem já existe,
não duplica.

Depois de migrado, basta manter `DATABASE_URL` definida nas variáveis de
ambiente de produção — `comendo_db.py` passa a usar o Postgres automaticamente,
sem nenhuma mudança de código em `painel.py`/`relatorios_automacao.py`/
`enviar_ads.py`.

**Validado nesta entrega:** schema, CRUD completo, CLI, cascade delete,
idempotência e integridade referencial testados contra Postgres 16 real (não
só SQLite), incluindo uma migração completa dos 82 clientes / 122 envios do
`clientes.db` de produção atual, com verificação de zero referências órfãs.

---

## Roteiro da migração (fases)

- [x] **Fase 1 — Fundação cloud-ready.** Código no repositório; toda
  configuração externalizada em env vars (`config.py`); segredos protegidos
  (`.gitignore`); `EVOLUTION_URL` e credenciais Google já preparados para
  URL pública / env. *(esta entrega)*
- [x] **Fase 2 — Banco na nuvem.** `comendo_db.py` ganha backend Postgres
  quando `DATABASE_URL` estiver definida (mesma API pública, SQLite e Postgres
  lado a lado); `migrar_para_postgres.py` migra o `clientes.db` atual
  preservando ids e integridade referencial. *(esta entrega — falta apenas
  provisionar o Postgres real de destino, ex. Supabase, e rodar a migração
  contra ele — ver §Externo pendente)*
- [ ] **Fase 3 — Ingestão Dashgoo.** Gmail por API no backend (ou webhook
  Dashgoo), sem depender de máquina pessoal.
- [ ] **Fase 4 — Agendador + segredos no backend.** Cron do provedor;
  segredos no secret store; alerta de falha (hoje inexistente).
- [ ] **Fase 5 — Evolution na nuvem.** Servidor sempre-ligado; reconexão de
  cada instância; teste em grupo de teste antes de tocar cliente real.
- [ ] **Fase 6 — Virada.** Rodar em paralelo com o Mac por 1–2 semanas antes
  de desligar o stack local.

Detalhe do que o produto final precisa cobrir: `docs/HANDOFF.md` §11.

---

## Externo pendente

Itens que só avançam com algo que só quem opera a agência tem acesso —
código e testes já estão prontos, falta só a peça externa:

1. **Postgres real de destino (Fase 2).** O adapter e a migração já estão
   testados de ponta a ponta contra um Postgres real (dados de produção
   completos, 82 clientes / 122 envios, zero inconsistência). Falta só um
   `DATABASE_URL` real — se o app da Comendo no Lovable já tem um Supabase
   por trás, é o encaixe natural (usar o mesmo). Assim que tiver a string de
   conexão, rodar `migrar_para_postgres.py` é o único passo restante.
2. **Servidor para a Evolution (WhatsApp) — Fase 5.** Precisa de um VPS/PaaS
   sempre-ligado (Railway, Render, Hetzner, DigitalOcean…) pra hospedar a
   Evolution API, e depois **reconectar cada instância escaneando o QR de
   novo** — isso é uma ação física de cada gestor no próprio celular, não
   automatizável.
