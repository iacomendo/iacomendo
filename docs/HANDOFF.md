# HANDOFF — Automação de Relatórios Semanais · Comendo MKT

> Documento de contexto para continuar este projeto em qualquer sessão do
> Claude Code (ou outro app do Claude). Leia tudo antes de mexer em qualquer
> arquivo. Não há segredos aqui — chaves e credenciais ficam apenas nos
> arquivos locais (ver seção 10).
>
> **Atualizado em 2026-07-16** — reescrito do zero após a pasta ter sido
> reorganizada (tudo que era solto em `Comendo/Projetos/` foi pra dentro de
> `Comendo/Projetos/Automacao-Relatorios/`) e depois de uma leva grande de
> mudanças: migração CSV → SQLite, painel visual unificado (Dashgoo + Meta
> Ads), rastreio de status de envio, fila de revisão manual e envio seletivo
> por cliente. Se você é uma sessão nova do Claude pegando isso pela primeira
> vez, este arquivo já reflete o estado atual — não assuma nada do que uma
> versão anterior deste documento possa ter dito sobre CSV ser a fonte da
> verdade, isso mudou.
>
> **⚠️ Este sistema local (Python/SQLite/painel) é um protótipo/teste, não
> o destino final.** O Lucas confirmou (16/07/2026) que o plano é
> reimplementar isso dentro do **sistema da Comendo feito no Lovable**.
> Ou seja: trate este documento e o código local como a **especificação
> viva** do que o app no Lovable precisa cobrir — não invista esforço em
> infraestrutura de produção aqui (banco compartilhado na nuvem, hosting
> sempre-ligado, etc.) só porque parece "a próxima etapa óbvia"; isso só
> faz sentido resolver dentro do Lovable. A seção 11 lista o que acho que
> ainda falta pensar/cobrir pro rebuild.

---

## 1. O que é este projeto

Duas automações irmãs que mandam relatório semanal de tráfego pago pro
WhatsApp do cliente, sem o gestor precisar escrever nada na mão (a não ser
que queira ajustar o texto):

| Fluxo | Fonte dos dados | Como roda |
|---|---|---|
| **Dashgoo / mLabs** | E-mail do Dashgoo no Gmail (PDF + métricas) | `relatorios_automacao.py`, agendado toda segunda 10h via `launchd` |
| **Meta Ads direto** (clientes só de tráfego, sem mLabs) | Meta Marketing API via MCP | comando `/relatorios-ads` no Claude Code, disparado na mão (por enquanto) |

Ambos os fluxos escrevem no **mesmo banco** (`clientes.db`, SQLite) e podem
ser geridos pelo **mesmo painel visual** (`painel.py`, porta 8077).

Roda localmente no Mac do Lucas (usuário `franca`). Está **em produção**.

## 2. Estado atual (16/07/2026)

- **Fonte da verdade agora é `clientes.db` (SQLite), não CSV.** Os arquivos
  `grupos.csv`, `contas_ads.csv` etc. continuam na pasta só como histórico —
  não são mais lidos por nenhum script. Ver seção 3.
- **Painel visual único** (`painel.py`) pra cadastrar/editar cliente (dos
  dois fluxos), definir saudação/estilo de mensagem por cliente, gerenciar
  gestores (criar instância Evolution + QR + número de teste), rodar a
  automação Dashgoo na hora, revisar rascunhos antes de enviar, e ver o
  status do último envio de cada cliente. Ver seção 4a.
- **Rastreio de envio (tabela `envios`).** Todo envio (sucesso, erro, sem
  tráfego, descartado) fica registrado por cliente/período. O painel mostra
  isso como uma pill colorida na tabela de clientes. Histórico anterior a
  essa feature foi reconstruído via `backfill_envios_gmail.py` (usa o
  status lido/não-lido do e-mail do Dashgoo como prova de envio — só marca
  como lido depois do envio das 4 mensagens dar certo).
- **Envio manual seletivo.** Cada cliente Dashgoo tem um checkbox na aba
  Clientes do painel. Marcando um ou mais, os botões "Gerar rascunhos" /
  "Rodar agora" passam a agir só neles — útil quando algo falhou (ex.: erro
  no mLabs) e o gestor corrige depois e quer reenviar só aquele cliente sem
  reprocessar todo mundo.
- **Modo revisão.** Em vez de enviar direto, dá pra gerar os rascunhos das
  mensagens (Dashgoo) e deixar na fila do painel pro gestor editar o texto
  à vontade antes de mandar — com botão de teste (manda só pro WhatsApp
  privado do gestor) e botão de envio manual (grupo do cliente).
- **51 clientes cadastrados** — 47 no fluxo Dashgoo, 4 no fluxo Meta Ads
  direto.
- **Multi-gestor ativo.** Cada gestor tem instância Evolution própria
  (`comendo_<nome>`). Gestores com instância + número de teste cadastrados
  hoje: **Yago** (`comendo_yago`) e **Joao** (`comendo_joao`). Existem
  também clientes marcados com gestor `Heitor` (Meta Ads, rodando hoje pela
  instância do Yago — ele ainda não tem instância própria) — e um resquício
  de dado antigo em que algumas linhas Dashgoo têm o campo `gestor` igual à
  própria instância (`comendo_joao`) em vez do nome bonito (`Joao`); não
  atrapalha o envio (a automação usa a `instancia`, não o `gestor`, pra
  rotear), mas deixa o agrupamento do painel com um bloco de nome estranho —
  vale um `UPDATE` pontual algum dia, não é urgente.
- **E-mail central da automação: `relatorioscomendomkt@gmail.com`.** Já
  autenticado (`token.json`, OAuth "Em produção" → token não expira).

## 3. Onde tudo vive (estrutura de pastas)

```
/Users/franca/Comendo/
├── Projetos/
│   ├── Automacao-Relatorios/        # <- TUDO deste projeto vive aqui agora
│   │   ├── relatorios_automacao.py  # script principal (fluxo Dashgoo)
│   │   ├── comendo_db.py            # módulo/CLI do banco (fonte da verdade)
│   │   ├── painel.py / Painel.command  # painel web (porta 8077)
│   │   ├── enviar_ads.py            # helper de envio Evolution (fluxo Meta Ads)
│   │   ├── adicionar_cliente.py     # cadastro via terminal (fallback do painel)
│   │   ├── backfill_envios_gmail.py # reconstrói histórico de envio a partir do Gmail
│   │   ├── listar_grupos.py / listar_grupos_yago.py / pegar_id_grupo.py  # utilitários
│   │   ├── logar_google.py          # refaz login OAuth isolado
│   │   ├── clientes.db              # SQLite — FONTE DA VERDADE (SEGREDO: dados de cliente)
│   │   ├── credentials.json         # OAuth Google (SEGREDO)
│   │   ├── token.json               # login Google gerado (SEGREDO)
│   │   ├── grupos.csv, contas_ads.csv, grupos_yago.csv, *.backup_*  # HISTÓRICO — não lidos mais
│   │   ├── automacao_log.txt / automacao_erro.txt  # log do agendador
│   │   ├── HANDOFF.md               # este arquivo
│   │   └── POP_META_ADS.md          # POP do fluxo Meta Ads direto
│   ├── Documentos/                  # POPs gerais (não específicos deste projeto)
│   ├── Materiais-RH-Treinamento/
│   ├── Dados-Campanhas/
│   └── (Agent-Reach/, camp lead lp .../, headroom/, etc. — outros projetos, intocados)
├── Evolution/
│   ├── docker-compose.yml           # stack da Evolution API (WhatsApp)
│   ├── mostrar_qr.py
│   └── resetar_e_conectar.py
└── Relatorios/                      # saída local das mensagens (.txt/.pdf), por período
```

Agendador: `~/Library/LaunchAgents/com.comendo.relatorios.plist` — aponta
pra `.../Automacao-Relatorios/relatorios_automacao.py` com
`WorkingDirectory` na mesma pasta. **Se essa pasta mudar de lugar de novo,
o plist e o slash command `/relatorios-ads`
(`~/.claude/commands/relatorios-ads.md`) precisam ser atualizados e o
launchd recarregado** (`launchctl unload` + `launchctl load` no plist), ou
o envio de segunda para de funcionar silenciosamente.

> IMPORTANTE: o projeto **NÃO pode** ficar dentro de `~/Desktop`,
> `~/Documents` ou `~/Downloads` — o macOS bloqueia o agendador de acessar
> essas pastas (foi causa de um bug antigo). Manter sempre em `~/Comendo`.

## 4. Componentes e configurações

### 4a. Painel visual (`painel.py`, porta 8077)

- Roda com `python3 painel.py` (ou 2 cliques em `Painel.command`) dentro de
  `Automacao-Relatorios/`. Abre sozinho no navegador.
- **Aba Clientes:** lista todos os clientes (Dashgoo + Meta Ads) agrupados
  por gestor, com pill de status de conexão da instância, pill de status do
  último envio, checkbox de seleção manual, e um seletor de **Visão**
  (Mestre = todos, ou micro = só os clientes daquele gestor — pensado pra
  quando cada gestor tiver seu próprio acesso no futuro).
  - Cadastro/edição de cliente: nome, gestor/instância, grupo do WhatsApp
    (busca direto da instância via Evolution), fluxo (dashgoo/meta_ads),
    `ad_account_id` (só Meta Ads), saudação padrão e estilo de mensagem
    (texto livre — o gestor escreve como quiser que o Claude escreva pra
    aquele cliente), status.
  - "+ Adicionar gestor": cria a instância Evolution, mostra QR (embutido
    ou pelo Evolution Manager), pede o número de WhatsApp do gestor (usado
    no botão de teste).
  - "🗒 Gerar rascunhos p/ revisão" / "▶ Rodar agora": disparam
    `relatorios_automacao.py` como subprocesso. Sem seleção, processa
    todos; com clientes marcados no checkbox, processa só eles
    (`COMENDO_CLIENTES_FILTRO`, ver seção 6).
- **Aba Fila de revisão:** rascunhos gerados em modo revisão (Dashgoo) ou
  via `/relatorios-ads revisao` (Meta Ads). Dá pra editar saudação/
  métricas/conclusão, descartar, ou selecionar em lote e mandar como
  **teste** (WhatsApp privado do gestor, prefixado `🧪 [TESTE]`) ou
  **manual** (grupo de verdade do cliente).
- Todas as escritas vão pro `clientes.db` via `comendo_db.py` — nunca edite
  esse banco na mão fora dele.

### 4b. Gmail + Drive (Google) — fluxo Dashgoo

- Busca e-mails **não lidos** do remetente `no-reply@mg.dashgoo.com` dos
  últimos 7 dias (`is:unread newer_than:7d`).
- Escopos: `gmail.modify` + `drive`.
- Marca o e-mail como **lido somente após o envio bem-sucedido das 4
  mensagens** (o que falha continua não-lido e é tentado de novo no
  próximo run — isso também é o que permite reconstruir histórico via
  `backfill_envios_gmail.py`).
- App OAuth **publicado "Em produção"** → token de longa duração.
- Segredos: `credentials.json` e `token.json`, dentro de `Automacao-Relatorios/`.

### 4c. Claude API (resumo das métricas + estilo por cliente)

- Chave em `ANTHROPIC_API_KEY` dentro do script (segredo, só local).
- O prompt aceita opcionalmente o `estilo_mensagem` cadastrado pelo gestor
  pra aquele cliente (via painel) e ajusta o tom/instruções de acordo.
- `SYSTEM_PROMPT` define a estrutura obrigatória da mensagem **e** a regra
  de cliente zerado: sem tráfego pago na semana → responde só
  `SEM_TRAFEGO_PAGO` (o script registra isso como `sem_trafego` no
  histórico e pula sem enviar nada).

### 4d. Evolution API (WhatsApp) — Docker local

- Imagem `evoapicloud/evolution-api:latest` + `postgres:15-alpine` +
  `redis:7-alpine`. URL: `http://localhost:8080` · API key:
  `comendo-evolution-2026`.
- Uma instância Evolution por gestor (`comendo_<nome>`), sessão persistida
  em volume Docker — mover a pasta de scripts não derruba a conexão.
- Painel de administração oficial em `http://localhost:8080/manager`.
- Envio: `POST /message/sendText/<instancia>` e
  `POST /message/sendMedia/<instancia>` (header `apikey`), usando o **JID
  do grupo** (`...@g.us`) no campo `number`.

### 4e. Meta Ads direto (sem mLabs)

- Comando `/relatorios-ads` (definido em
  `~/.claude/commands/relatorios-ads.md`) — lê os clientes do fluxo
  `meta_ads` via `comendo_db.py listar --fluxo meta_ads`, puxa métricas via
  MCP da Meta Ads, e envia via `enviar_ads.py`.
- Argumentos: `simulacao` (só mostra), `teste` (manda pro privado do
  gestor), `revisao` (grava rascunho na fila do painel em vez de enviar),
  `apenas=<Nome>` (um cliente só), `gestor=<Nome>` (filtra por gestor).
- **Decisão de acesso (16/07/2026): BM central, não MCP por gestor.** Em
  vez de cada gestor conectar o próprio MCP/login Meta, os gestores
  adicionam os clientes de Meta Ads na **BM central da Comendo Marketing**
  — assim o MCP conectado no Claude Code do Lucas já enxerga a conta de
  anúncios de todo mundo, sem precisar de um conector por pessoa. Na
  prática o Lucas continua sendo quem dispara `/relatorios-ads` (com
  `gestor=<Nome>` pra filtrar), lendo o `ad_account_id` que cada gestor
  cadastrou no painel. Detalhes em `POP_META_ADS.md` §7 (reescrita — a
  versão antiga falava em MCP individual por gestor, isso mudou).
- Detalhes completos de classificação de campanha, cadastro de cliente
  novo etc. estão em `POP_META_ADS.md`, na mesma pasta.

## 5. Lógica de funcionamento (fluxo Dashgoo, resumo)

- **Roteamento:** o nome do cliente no banco é casado como **substring do
  assunto** do e-mail Dashgoo (ignora prefixos de estratégia tipo `PF-`,
  `T,`, `R,`, `M`, `A`). Quando casa, pega o `grupo_id` e a `instancia`
  daquele cliente e dispara as 4 mensagens via
  `POST /message/.../{instancia}`.
- **Formato preferido no assunto pra auto-onboarding:**
  `Gestor | Nome exato do grupo` (ex.: `Yago | TAZ BURGUER - MKT`) —
  restringe a busca à instância daquele gestor.
- **Estrutura das 4 mensagens** por cliente:
  1. Saudação (padrão do cliente, se cadastrada no painel — senão a
     saudação padrão do sistema)
  2. PDF + legenda ("Segue relatório de performance dos anúncios de
     {período}")
  3. As métricas
  4. A conclusão
- **Loop blindado:** cada cliente roda dentro de um `try/except`; erro
  registra `erro` no histórico de envio (`envios`) e pula só aquele
  cliente, segue os demais; no fim imprime um **RESUMO**.
- **Resumo semanal em grupo interno:** ao fim da rodada manda uma mensagem
  no grupo `Performance - Sem Relatório` com até 4 seções (Enviados /
  Zerados / Auto-cadastrados / Cadastro pendente). Pulado em modo revisão.
- **Auto-onboarding de cliente órfão:** e-mail cujo cliente ainda não está
  no banco → tenta achar o grupo sozinho (match único por substring na(s)
  instância(s) conectada(s)); se achar, cadastra no banco com
  `status = "OK (auto)"` e envia; se ambíguo, reporta como pendente.

## 6. Flags de controle (topo do `relatorios_automacao.py`)

- `MODO_TESTE` → `True`: manda tudo para `MEU_NUMERO` (teste manual local,
  não usado pelo painel). `False` em produção.
- `MODO_SIMULACAO` → `True`: só mostra o roteamento, sem enviar.
- `GRUPO_TESTE_ID` → se preenchido, manda tudo pra esse grupo de teste.
- `MODO_REVISAO` (env var `COMENDO_MODO_REVISAO=1`, setada pelo painel) →
  gera as mensagens mas não envia; grava rascunho em `mensagens_pendentes`
  pro gestor revisar no painel. **`False` por padrão** — senão o run
  agendado de segunda 10h pararia de enviar sozinho.
- `CLIENTES_FILTRO` (env var `COMENDO_CLIENTES_FILTRO`, separada por `|`,
  setada pelo painel quando há checkbox marcado na aba Clientes) → só
  processa os clientes listados; os demais ficam intocados (e-mail
  continua não-lido, disponível pro próximo run). **Vazia por padrão** —
  processa todo mundo, igual sempre foi.
- **Produção (run agendado):** todas as flags/env vars acima no padrão —
  `MODO_TESTE=False`, `MODO_SIMULACAO=False`, `GRUPO_TESTE_ID=""`,
  `COMENDO_MODO_REVISAO` e `COMENDO_CLIENTES_FILTRO` ausentes.

## 7. Como rodar e testar com segurança

- Rodar na mão: `cd ~/Comendo/Projetos/Automacao-Relatorios && python3 relatorios_automacao.py`
- Abrir o painel: `cd ~/Comendo/Projetos/Automacao-Relatorios && python3 painel.py` (ou `Painel.command`)
- Forçar o agendador agora: `launchctl start com.comendo.relatorios`
- Ver logs: `tail -n 30 ~/Comendo/Projetos/Automacao-Relatorios/automacao_log.txt` · `cat ~/Comendo/Projetos/Automacao-Relatorios/automacao_erro.txt`
- Testar **sem afetar clientes de verdade:** usar o modo revisão do painel
  (gera rascunho, não envia) + botão de teste (manda só pro WhatsApp
  privado do gestor cadastrado).
- Reabrir e-mails para reteste: marcar como **não-lido** no Gmail os
  relatórios do Dashgoo desejados.
- O Docker/Evolution precisa estar rodando e com `"state":"open"` na
  instância pra enviar de verdade.
- **Cuidado real já aconteceu aqui:** processo órfão de teste + Evolution
  subindo no meio de um teste já mandou mensagem de teste de verdade pro
  WhatsApp de um gestor (só o número de teste dele, nenhum cliente
  afetado). Antes de testar qualquer rota que manda mensagem de verdade
  (`/api/pendente/testar`, `/api/pendente/enviar`, `/api/criar_gestor`),
  confirme que não tem processo antigo de `painel.py` rodando
  (`lsof -i :8077`, `pkill -f painel.py` se precisar) e prefira testar só
  rotas de leitura/banco quando o Evolution estiver de fato conectado.

## 8. Pendências / próximos passos

1. ~~Decidir como o MCP acessa a conta de anúncios de cada gestor~~ —
   **resolvido em 16/07/2026:** os gestores adicionam os clientes na BM
   central da Comendo Marketing em vez de cada um plugar seu próprio MCP
   (ver seção 4e / `POP_META_ADS.md` §7). Continua em aberto, só se algum
   dia um gestor quiser rodar `/relatorios-ads` na própria máquina (aí sim
   esbarra em `clientes.db` só existir no Mac do Lucas) — não prioritário.
2. **Nomear no painel as instâncias Evolution que já conectaram mas ainda
   não têm gestor cadastrado** (ex.: `comendo_anafabri`,
   `comendo_gabrielly`, `comendo_julio`, `comendo`). Sem nome cadastrado,
   o seletor de gestor no cadastro de cliente mostra o nome técnico da
   instância em vez do nome da pessoa — use o botão "✎ Nomear agora" que
   aparece no modal de cadastro de cliente quando há instância pendente.
3. ~~Limpar o campo `gestor` de linhas antigas com o valor da instância
   (`comendo_joao`) em vez do nome (`Joao`)~~ — **resolvido**, hoje os 51
   clientes têm só 3 valores de `gestor`: `Heitor`, `Joao`, `Yago`.
4. **Dar instância Evolution própria pro Heitor**, se ele for continuar
   recebendo/gerindo clientes — hoje os clientes dele rodam pela instância
   do Yago.
5. **Automatizar o disparo do fluxo Meta Ads.** Hoje `/relatorios-ads` é
   manual (o Lucas ou o gestor precisa rodar); o fluxo Dashgoo já é 100%
   automático via launchd.
6. **Precisão do Claude / prompt.** Ver se vale migrar de Haiku pra um
   modelo maior nas mensagens Dashgoo — não houve mudança nessa frente
   nesta rodada de trabalho.
7. **Risco operacional: máquina única.** Tudo roda no Mac do Lucas. Se ele
   dormir/cair internet na segunda 10h, ninguém recebe.
8. **Fase grande — plataforma multiusuário da agência** (longo prazo). App
   web com login e níveis admin/gestor, painel próprio por gestor. O
   piloto multi-tenant local de hoje (visão Mestre/micro no painel,
   `gestor=` no comando Meta Ads) é a especificação inicial dessa
   plataforma.

## 9. Convenções de comunicação (manter sempre)

- Texto final em **plain text**, pronto para colar no WhatsApp.
- Tom **profissional, factual e objetivo** — sem adjetivos elogiosos, sem
  exclamações no corpo, sem projeções/recomendações não pedidas.
- Emojis **apenas** nos títulos de bloco e no emoji principal do nicho.
- Conclusão da semana: parágrafo curto (2–3 frases, máx ~60 palavras).
- **Nunca inventar dados.**
- Se o cliente tiver `estilo_mensagem` cadastrado no painel, isso tem
  prioridade sobre o tom padrão (dentro do razoável — a estrutura das 4
  mensagens e a regra de nunca inventar dado continuam valendo).

## 10. Segredos (NÃO escrever os valores neste arquivo nem em lugar compartilhado)

- Chave da API do Claude: dentro do script (`ANTHROPIC_API_KEY`), só local.
- OAuth Google: `credentials.json` + `token.json`, dentro de
  `Automacao-Relatorios/`.
- API key da Evolution: `comendo-evolution-2026`.
- `clientes.db` tem dado de cliente (nome, grupo, conta de anúncio) — não é
  segredo técnico, mas não deve ser commitado/compartilhado fora da
  agência.
- **Nunca** versionar (git) nem compartilhar esses arquivos. Se for criar
  repositório, adicionar `.gitignore` cobrindo `credentials.json`,
  `token.json`, `clientes.db` e o `.py` com a chave (ou mover pra variável
  de ambiente).

## 11. O que falta pensar pro rebuild no Lovable (16/07/2026)

Avaliação de gaps do protótipo local, pra servir de checklist na hora de
especificar o app de verdade — não é lista de tarefas do protótipo, é o
que o **produto final** provavelmente precisa cobrir que hoje é feito na
gambiarra/manual ou não existe:

1. **Login e permissão por papel (admin × gestor).** Hoje qualquer um que
   abre o painel local vê e edita tudo — a "visão Mestre/micro" é só um
   filtro visual, não uma restrição de segurança de verdade. O app
   precisa de autenticação de verdade (Supabase Auth, se for esse o
   backend do Lovable) com um gestor só enxergando/editando os próprios
   clientes, e admin (Lucas) enxergando tudo.
2. **WhatsApp não pode depender de um Mac ligado.** Hoje cada gestor
   escaneia QR pra uma instância Evolution rodando em Docker no Mac do
   Lucas — se ele desligar/perder internet numa segunda 10h, ninguém
   recebe relatório (pendência já conhecida, seção 8). No rebuild, isso
   significa Evolution (ou WhatsApp Cloud API oficial da Meta, que é mais
   robusta mas exige verificação de negócio) rodando num servidor
   sempre-ligado, não mais numa máquina pessoal.
3. **Onde a chamada de IA roda e como a chave fica protegida.** Hoje é
   `ANTHROPIC_API_KEY` direto no script Python local. No Lovable isso
   precisa virar uma função de backend (edge function) — a chave nunca
   pode ir pro código que roda no navegador do gestor.
4. **Ingestão do Dashgoo é frágil por natureza (e-mail + scraping).** Hoje:
   e-mail chega → Gmail API → acha o link → Playwright baixa o PDF →
   casa o nome do cliente por **substring do assunto do e-mail** (a parte
   mais gambiarra de tudo — cliente cujo nome não bate literalmente vira
   "cadastro pendente" silenciosamente). Vale desenhar isso melhor no
   rebuild: se o Dashgoo tiver webhook/API, preferir isso a depender de
   parsing de e-mail; se não tiver, pelo menos trocar "match por
   substring" por um identificador estável por cliente.
5. **A fila de revisão (rascunho → editar → testar → enviar) é uma boa
   peça de UX pra portar quase 1:1** — já foi desenhada e testada aqui,
   vale reaproveitar o fluxo (não o código Python, o *fluxo*) no Lovable.
6. **Histórico de envio (`envios`) é hoje só uma pill de status — dá pra
   virar um dashboard de verdade** no Lovable: filtro por período/gestor/
   cliente, taxa de entrega, alerta de "cliente sem relatório há N
   semanas" (isso já existe como print no backfill, merece virar tela).
7. **Auto-cadastro de cliente órfão por match único tem risco de casar
   errado silenciosamente** (mesmo problema do item 4, mas do lado
   Evolution/grupo). Vale um passo de confirmação humana antes de qualquer
   auto-cadastro virar produção de verdade, não só reportar como
   "pendente" quando é ambíguo.
8. **Não existe alerta de falha — só log em `.txt`.** Hoje o único jeito de
   saber que a automação não rodou numa segunda é abrir o Mac e olhar
   `automacao_log.txt`/`automacao_erro.txt` na mão. O rebuild deveria
   notificar ativamente (WhatsApp/e-mail pro Lucas) quando o run agendado
   falha ou não roda no horário esperado.
9. **Meta Ads via BM central resolve o acesso, mas o disparo ainda é
   manual** (`/relatorios-ads` rodado à mão). No app de verdade isso
   deveria ser agendado igual ao fluxo Dashgoo, não depender de alguém
   lembrar de rodar o comando.
