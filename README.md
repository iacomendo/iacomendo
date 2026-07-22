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

> **Decisão atual: sem Lovable/Supabase por enquanto.** O backend Postgres
> existe e está testado (Fase 2), mas **não está em uso** — o sistema roda
> em SQLite (o mesmo `clientes.db` de sempre) até essa decisão mudar. Ativar
> o Postgres depois é só definir `DATABASE_URL`; nenhum código muda.

| Peça | Local (Mac) | Nuvem (destino) |
|---|---|---|
| WhatsApp (Evolution) | Docker em `localhost:8080` | servidor sempre-ligado (VPS), URL pública — ver `deploy/` |
| Banco | SQLite (`clientes.db`) | **segue SQLite por ora** (mesmo arquivo, agora num VPS); Postgres fica pronto e desligado |
| Ingestão Dashgoo | Gmail OAuth + Playwright, local | mesmo código, rodando no VPS (Gmail já é uma API — não depende de onde roda) |
| Agendador | `launchd` (seg 10h) | `systemd` timer num VPS — ver `deploy/systemd/` (não serverless: SQLite precisa de disco persistente) |
| Alerta de falha | inexistente (só log em `.txt`) | aviso por WhatsApp quando o run inteiro falha (`ALERTA_NUMERO`) |
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
| `DATABASE_URL` | Postgres (nuvem) — **não usada por ora** (decisão: sem Lovable/Supabase ainda); ausente = SQLite `DB_PATH` |
| `PAINEL_HOST` / `PORT` | bind do painel (local `127.0.0.1`, nuvem `0.0.0.0`) |
| `NUMEROS_GESTORES` / `MEU_NUMERO` | fallback de números de gestor |
| `ALERTA_NUMERO` / `ALERTA_INSTANCIA` | pra onde avisar por WhatsApp se o run inteiro falhar (default: `MEU_NUMERO`/instância padrão) |

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

**Por ora, este backend fica pronto mas inativo** — a operação continua em
SQLite até a decisão de usar Postgres/Lovable mudar (ver nota no topo).

---

## Deploy num VPS

Scaffolding pronto em `deploy/` (Dockerfile na raiz + `deploy/evolution/` +
`deploy/systemd/`) pra rodar o stack inteiro (app + painel + Evolution) num
servidor Linux sempre-ligado, no lugar do Mac — inclusive o agendamento
semanal (substituindo o `launchd`) e o alerta de falha crítica por WhatsApp
(`ALERTA_NUMERO`), que hoje não existe (HANDOFF §8.8). Detalhes e passo a
passo em `deploy/README.md`. **Ainda não implantado em nenhum servidor
real** — é a preparação, pronta pra usar quando um VPS for provisionado.

---

## Roteiro da migração (fases)

- [x] **Fase 1 — Fundação cloud-ready.** Código no repositório; toda
  configuração externalizada em env vars (`config.py`); segredos protegidos
  (`.gitignore`); `EVOLUTION_URL` e credenciais Google já preparados para
  URL pública / env. *(esta entrega)*
- [x] **Fase 2 — Banco na nuvem (código pronto, não ativado).**
  `comendo_db.py` ganha backend Postgres quando `DATABASE_URL` estiver
  definida (mesma API pública, SQLite e Postgres lado a lado);
  `migrar_para_postgres.py` migra o `clientes.db` atual preservando ids e
  integridade referencial — testado contra Postgres real. **Decisão atual:
  sem Lovable/Supabase por ora** — a operação segue em SQLite; ativar
  Postgres depois é só definir `DATABASE_URL`, sem mudar código.
- [x] **Ingestão Dashgoo — já cloud-ready desde a Fase 1.** Gmail é uma API
  (não depende de rodar no Mac); `autenticar_google()` já suporta headless
  via `GOOGLE_TOKEN_JSON`. O que falta (webhook do Dashgoo em vez de parsing
  de e-mail/assunto) depende do Dashgoo oferecer isso — não é código nosso,
  fica registrado como limitação conhecida (`docs/HANDOFF.md` §11.4).
- [x] **Fase 4 — Alerta de falha + scaffolding do agendador.** Falha crítica
  (fora do loop por-cliente) agora avisa por WhatsApp (`ALERTA_NUMERO`) e
  garante exit code de erro pro agendador perceber — antes só ficava em log
  (HANDOFF §8.8). `deploy/systemd/` traz o `.service`+`.timer` que substitui
  o `launchd`, pronto pra instalar num VPS. *(falta só ligar isso num
  servidor real — ver `deploy/README.md`)*
- [ ] **Fase 5 — Evolution na nuvem.** `deploy/evolution/docker-compose.yml`
  pronto; falta provisionar o VPS de verdade e reconectar cada instância
  escaneando o QR de novo (ação manual, por gestor).
- [ ] **Fase 6 — Virada.** Rodar em paralelo com o Mac por 1–2 semanas antes
  de desligar o stack local.

Detalhe do que o produto final precisa cobrir: `docs/HANDOFF.md` §11.

---

## Externo pendente

Itens que só avançam com algo que só quem opera a agência tem acesso —
código e testes já estão prontos, falta só a peça externa:

1. **Um VPS sempre-ligado (Fases 4/5).** O scaffolding inteiro já está em
   `deploy/` (Dockerfile, docker-compose da Evolution, unidades systemd do
   agendador e do painel) — falta só provisionar o servidor de verdade
   (Railway, Render, Hetzner, DigitalOcean…), apontar um domínio, e seguir o
   passo a passo em `deploy/README.md`. Depois disso, **reconectar cada
   instância de gestor escaneando o QR de novo** é uma ação manual, física,
   de cada gestor no próprio celular — não automatizável.
2. **Postgres real de destino (Fase 2) — não urgente agora.** Adapter e
   migração já testados de ponta a ponta contra Postgres real (82 clientes /
   122 envios, zero inconsistência), mas **adiado por decisão**: sem
   Lovable/Supabase por enquanto. Quando isso mudar, é só um `DATABASE_URL`
   e rodar `migrar_para_postgres.py`.
