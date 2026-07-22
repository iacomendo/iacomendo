# OPERAÇÃO COMENDO MKT — Documento Mestre

> **Para que serve este documento:** dar a uma sessão nova do Claude (em
> qualquer app — Claude Code, Claude.ai, Cowork) o contexto completo da
> operação de tráfego pago da Comendo MKT: o que é automatizado, como
> funciona, quem são os gestores, quais são os critérios de qualidade e
> onde estão os limites conhecidos.
>
> **Atualizado em:** 21/07/2026
>
> **Documentos irmãos (detalhe técnico):**
> - `Automacao-Relatorios/HANDOFF.md` — detalhe fino da automação de relatórios
> - `Automacao-Relatorios/POP_META_ADS.md` — POP do fluxo Meta Ads direto
>
> **Não há segredos aqui.** Chaves e credenciais vivem só nos arquivos
> locais (ver §9).

---

## 1. O que a operação faz

A Comendo MKT é uma agência de tráfego pago focada em **food service**
(hamburguerias, pizzarias, padarias, restaurantes, bares, hotéis). Cada
cliente tem um gestor responsável, e a comunicação com o cliente acontece
em **grupos de WhatsApp**.

Três sistemas rodam hoje:

| # | Sistema | O que faz | Como dispara |
|---|---|---|---|
| 1 | **Relatórios semanais Dashgoo** | Manda o relatório de performance no grupo do cliente (4 mensagens: saudação, PDF, métricas, conclusão) | Automático — toda segunda 10h via `launchd` |
| 2 | **Relatórios Meta Ads direto** | Mesmo formato, mas para clientes só-tráfego (sem mLabs/Dashgoo), puxando métricas direto da API | Manual — comando `/relatorios-ads` |
| 3 | **Auditoria de Qualidade da Performance** | Varre todas as contas da BM, flagra campanhas fora do benchmark e analisa os criativos, para os gestores debaterem melhorias | Manual — sob demanda (§5) |

Os sistemas 1 e 2 escrevem no mesmo banco (`clientes.db`) e são geridos
pelo mesmo painel (`painel.py`, porta 8077).

**Tudo roda localmente no Mac do Lucas** (usuário `franca`). Está em
produção.

> ⚠️ **Este stack local é protótipo, não destino final.** O plano é
> reimplementar no **sistema da Comendo feito no Lovable**. Trate o código
> local como *especificação viva* — não invista em infra de produção aqui
> (servidor sempre-ligado, banco na nuvem); isso se resolve no Lovable.

---

## 2. Estrutura de gestores e clientes

### 2.1 Estado atual (21/07/2026) — 82 clientes

| Gestor | Clientes | Fluxo | Instância WhatsApp |
|---|---|---|---|
| **Joao** | 26 | Dashgoo | `comendo_joao` |
| **Julio Rossi** | 25 | Dashgoo | `comendo_julio` |
| **Yago** | 22 | Dashgoo | `comendo_yago` |
| **Gabrielly** | 5 | Dashgoo | `comendo_gabrielly` |
| **Heitor** | 4 | Meta Ads | *(usa a instância do Yago — não tem própria)* |

### 2.2 Instâncias Evolution existentes

`comendo` (Lucas), `comendo_yago`, `comendo_joao`, `comendo_julio`,
`comendo_gabrielly`, `comendo_anafabri`, `comendo_francis`.

### 2.3 ⚠️ Pendência ativa: gestores sem número cadastrado

A tabela `gestores` (que guarda instância → nome → número de WhatsApp) só
tem **Joao** e **Yago**. Consequência real: **Gabrielly e Julio Rossi não
recebem o resumo privado semanal** — a automação loga
`Gestor 'X' sem número cadastrado — pulei resumo privado` e segue.

**Como resolver:** cadastrar o número pelo painel (botão de número na aba
Clientes, ou "✎ Nomear agora" no modal de cadastro).

### 2.4 Observação sobre o Lucas

O Lucas mudou de cargo em jun/2026 e **não tem clientes na automação** —
cuida de poucos clientes manualmente. A instância `comendo` (número dele)
segue conectada e é usada para: grupos internos da agência e como
instância de origem de mensagens administrativas.

---

## 3. Sistema 1 — Relatórios semanais (Dashgoo)

### 3.1 O fluxo, ponta a ponta

1. Dashgoo envia o relatório por e-mail para a caixa central
   **`relatorioscomendomkt@gmail.com`**.
2. Segunda 10h o `launchd` dispara `relatorios_automacao.py`.
3. O script busca e-mails **não lidos** de `no-reply@mg.dashgoo.com` dos
   últimos 7 dias.
4. Para cada e-mail: identifica o cliente → baixa o PDF (Playwright) →
   Claude resume as métricas → salva no Drive → dispara **4 mensagens** no
   grupo do cliente, pela instância Evolution do gestor dono.
5. Marca o e-mail como lido **só se o envio deu certo**.
6. No fim, manda um **resumo privado para cada gestor** com o que
   aconteceu com os clientes dele.

### 3.2 Padrão de assunto do e-mail (importante)

O assunto deve vir no formato **`GESTOR | NOME EXATO DO GRUPO`**:

```
Joao | ARAXÁ - MKT
Yago | TAZ BURGUER-MKT
JULIO ROSSI | 3 SMASH BURGERS - MKT
```

Isso permite o **auto-onboarding**: se o cliente ainda não está cadastrado,
o script identifica o gestor pelo assunto, procura o grupo **só na
instância dele**, e se achar match único cadastra sozinho e envia.

**Regras do parser (já resolvidas, não regredir):**
- Acento não importa: `João` e `Joao` resolvem para o mesmo gestor.
- Nome completo cai para o primeiro nome: `JULIO ROSSI` → `comendo_julio`
  (aceito só se bater com **uma única** instância).
- O nome do gestor gravado no banco vem da tabela `gestores` quando
  existe, nunca o nome técnico da instância.

### 3.3 Regra de cliente zerado

Se a semana não teve tráfego pago, o Claude responde só
`SEM_TRAFEGO_PAGO`; o script registra `sem_trafego` no histórico e **não
envia nada** para o cliente.

### 3.4 Blindagem contra falha

Cada cliente roda em `try/except`. Se falhar (erro de rede, timeout), o
script:
- registra `erro` na tabela `envios`,
- **deixa o e-mail não-lido**,
- segue para o próximo cliente.

Na execução seguinte, o cliente que falhou é reprocessado automaticamente.
**Nada se perde.**

---

## 4. Sistema 2 — Relatórios Meta Ads direto

Para clientes só-tráfego, sem Dashgoo/mLabs. Comando `/relatorios-ads`.
Puxa métricas via MCP da Meta Ads e envia via `enviar_ads.py`.

**Decisão de acesso:** os gestores adicionam os clientes na **BM central
da Comendo Marketing** — assim o MCP conectado no Claude do Lucas enxerga
todas as contas, sem precisar de conector por pessoa.

Detalhes completos em `POP_META_ADS.md`.

---

## 5. Sistema 3 — Auditoria de Qualidade da Performance

Levantamento periódico de **todas as contas ativas da BM** (≈136
consultáveis) para achar campanhas fora do padrão de qualidade e alimentar
o debate entre gestores.

### 5.1 Benchmarks definidos

| Métrica | Objetivo da campanha | Limite | Ação |
|---|---|---|---|
| **ROAS** | Vendas (`OUTCOME_SALES`) | **abaixo de 7x** | Flagrar |
| **Custo por Conversa Iniciada** | Mensagens (`MESSAGES`) | **acima de R$ 10** | Flagrar |

Campanhas com gasto zero no período são ignoradas (pausadas / sem verba).

### 5.2 O que é reportado por cliente flagrado

1. Nome do cliente
2. Nome da campanha
3. Objetivo (Vendas ou Mensagem)
4. A métrica que furou, com o valor e o gasto do período
5. **Análise do criativo** (§5.4)

### 5.3 Campos corretos da API

- **ROAS** → `purchase_roas`
- **Custo por Conversa Iniciada** → `cost_per_result` *(em campanha de
  objetivo `MESSAGES`, o "resultado" É a conversa iniciada)*
- **Frequência** → `frequency` *(existe e é filtrável; não está no
  benchmark hoje)*
- Nível: `campaign`. Período usado: `last_7d`.

### 5.4 Metodologia de análise de criativo

Puxar via `ads_get_creatives` (com `creative_ids`, senão vem só o nome) os
campos: `body`, `title`, `link_url`, `call_to_action_type`, `object_type`.

Avaliar friamente:
- **Coerência de destino:** campanha de Vendas deve ter CTA de compra
  (`SHOP_NOW`, `ORDER_NOW`, `SEE_MENU`). CTA `SEE_DETAILS` ("Saiba mais")
  em campanha de Vendas é incoerência.
- **Tem oferta clara?** Preço, combo, desconto, brinde, urgência — ou é
  branding/institucional sem gatilho de compra?
- **Atrito no caminho de compra:** manda para "link na bio" num anúncio
  pago que já tem botão? Empurra o pedido para um número de WhatsApp
  digitado no texto?
- **Objetivo divergente:** criativo de engajamento ("marque um amigo") em
  campanha de conversão.
- **Duplicidade:** criativos com copy idêntica na mesma campanha
  canibalizam entrega e dividem aprendizado.
- **Sazonalidade vencida:** peça de Ano Novo rodando em julho.

### 5.5 ❌ Limitação conhecida: segmentação não é extraível

**O MCP da Meta Ads NÃO expõe o targeting spec dos conjuntos.** Testados e
inexistentes: `targeting`, `geo_locations`, `age_min`, `age_max`,
`custom_audiences`, `publisher_platforms`, `genders`.

Ou seja, **não dá para auditar por automação**: raio/endereço configurado,
idade segmentada, públicos personalizados aplicados, dados demográficos,
plataformas de veiculação.

**Alternativa (não implementada):** via extensão **Claude in Chrome**,
navegando no Gerenciador de Anúncios logado e lendo a segmentação da tela.
É manual, lento, e exige o Chrome aberto e logado — não roda em agendador.
**Decisão do Lucas (21/07/2026): deixar a segmentação de fora por ora.**

### 5.6 Grupos de destino

| Grupo | Instância | Conteúdo |
|---|---|---|
| **GESTOR DE PROJETOS** (`120363423909810904@g.us`) | `comendo` | Lista de clientes com ROAS < 7x |
| **Qualidade da Performance** | `comendo` *(a confirmar)* | Relatório completo: métricas + análise de criativo, para debate |
| **Performance - Sem Relatório** (`120363408731936845@g.us`) | `comendo_yago` | *(legado — desativado; hoje o resumo vai no privado de cada gestor)* |

### 5.7 Achados da última auditoria (13/07 a 19/07)

9 clientes com ROAS < 7x. Nenhum cliente furou o Custo por Conversa.

**Padrão transversal encontrado:**
- Quase nenhum criativo tem **oferta clara** (desconto, combo, urgência)
- Vários misturam **branding/engajamento** com objetivo de conversão
- Muitos mandam para **"link na bio"** em anúncio pago que já tem botão
- **Criativos duplicados** dentro da mesma campanha

**Casos que exigem atenção específica:**
- **Ragatella Pizzerie — ROAS 0,00x:** os criativos estão corretos (oferta
  + preço + CTA de compra). ROAS zero com criativo bom aponta para **falha
  de rastreamento/pixel de compra no site**, não criativo.
- **Kato Japa:** a campanha flagrada está **100% pausada**; os sucessores
  migraram para outra campanha. ROAS lido sobre gasto baixo.
- **Gasto baixo = leitura não confiável:** Kato Japa (R$86) e Pizzaria
  Garutti (R$37) têm ROAS estatisticamente frágil — não sustentam decisão
  de corte ou escala.

---

## 6. Infraestrutura

### 6.1 Onde tudo vive

```
/Users/franca/Comendo/
├── Projetos/
│   ├── OPERACAO-COMENDO-MKT.md      # este documento
│   └── Automacao-Relatorios/        # todo o código da automação
│       ├── relatorios_automacao.py  # script principal (Dashgoo)
│       ├── comendo_db.py            # módulo/CLI do banco
│       ├── painel.py                # painel web (porta 8077)
│       ├── enviar_ads.py            # envio do fluxo Meta Ads
│       ├── clientes.db              # SQLite — FONTE DA VERDADE
│       ├── credentials.json/token.json  # OAuth Google (SEGREDO)
│       ├── HANDOFF.md, POP_META_ADS.md
│       └── *.csv, *.backup_*        # histórico, não lidos mais
├── Evolution/docker-compose.yml     # stack WhatsApp
└── Relatorios/                      # saída local por período
```

Agendador: `~/Library/LaunchAgents/com.comendo.relatorios.plist`

> ⚠️ O projeto **não pode** ficar em `~/Desktop`, `~/Documents` ou
> `~/Downloads` — o macOS bloqueia o agendador nessas pastas.
> Se a pasta mudar de lugar, atualizar o plist **e** recarregar o launchd,
> senão o envio de segunda para silenciosamente.

### 6.2 Banco (`clientes.db`, SQLite)

Fonte da verdade. Tabelas: `clientes`, `gestores`, `envios`,
`mensagens_pendentes`. Sempre escrever via `comendo_db.py`, nunca editar o
banco na mão.

Os arquivos `.csv` na pasta são **histórico** — não são mais lidos.

### 6.3 Evolution API (WhatsApp)

Docker local (`evoapicloud/evolution-api` + postgres + redis),
`http://localhost:8080`, uma instância por gestor. Painel admin em
`/manager`. Sessões persistidas em volume Docker.

---

## 7. Convenções de comunicação (manter sempre)

- Texto final em **plain text**, pronto para colar no WhatsApp.
- Tom **profissional, factual e objetivo** — sem adjetivos elogiosos, sem
  exclamações no corpo, sem projeções ou recomendações não pedidas.
- Emojis **apenas** em títulos de bloco e no emoji do nicho — nunca no meio
  do texto da conclusão.
- Conclusão da semana: parágrafo curto (2–3 frases, máx ~60 palavras).
- **Nunca inventar dados.**
- Se o cliente tem `estilo_mensagem` cadastrado no painel, isso tem
  prioridade sobre o tom padrão (mas a estrutura das 4 mensagens e a regra
  de nunca inventar dado continuam valendo).

---

## 8. Problemas recorrentes e como reconhecê-los

### 8.1 Docker cai sozinho
**Sintoma:** `docker DOWN`, Evolution não responde, envios falham.
**Ação:** `open -a Docker`, esperar subir, conferir
`GET /instance/connectionState/<instancia>` → `"state":"open"`.
É a causa mais comum de falha em execução manual.

### 8.2 Erros de rede no envio
`[Errno 32] Broken pipe`, `[Errno 54] Connection reset by peer`,
`Read timed out` — a Evolution derruba a conexão sob carga (rajadas de
muitos clientes seguidos).
**Não é bug de código.** O e-mail fica não-lido e é reprocessado na
execução seguinte. Basta rodar de novo.

### 8.3 `fetchAllGroups` travando
A instância `comendo` tem ~139 grupos e frequentemente dá timeout ou
resposta vazia ao listar todos. Se precisar do ID de um grupo, tentar
algumas vezes ou pegar o ID direto.

### 8.4 Campo `gestor` gravado com o nome da instância
Bug histórico (já corrigido na raiz) em que o cliente era cadastrado com
`gestor = "comendo_joao"` em vez de `"Joao"`, quebrando o resumo privado.
Se reaparecer, verificar `_resolver_nome_gestor` e `_nome_canonico_gestor`
em `relatorios_automacao.py`, e `nomeExibicaoGestor` no painel.

### 8.5 Cliente que não recebeu relatório
Diagnóstico em 3 passos:
1. Está cadastrado no banco? (`clientes`, com `grupo_id` e `instancia`)
2. O que diz a tabela `envios` para ele no período?
3. O e-mail dele no Gmail está lido ou não-lido?
   - **Não-lido** → falhou e será reprocessado (normal)
   - **Lido sem envio registrado** → investigar, é anomalia

---

## 9. Segredos (nunca escrever valores em documento compartilhado)

- `ANTHROPIC_API_KEY` — dentro do script, só local
- OAuth Google — `credentials.json` + `token.json`
- API key da Evolution — definida no `docker-compose.yml`
- `clientes.db` — dados de cliente; não é segredo técnico, mas não sai da
  agência
- **Nunca versionar** esses arquivos. Se criar repositório, `.gitignore`
  cobrindo todos.

---

## 10. Pendências

### Curto prazo
1. **Cadastrar número de WhatsApp da Gabrielly e do Julio Rossi** na tabela
   `gestores` — sem isso não recebem resumo privado (§2.3).
2. **Nomear as instâncias órfãs** no painel (`comendo_anafabri`,
   `comendo_francis`) — aparecem com nome técnico no seletor.
3. **Dar instância própria ao Heitor** se ele seguir com clientes — hoje
   roda pela do Yago.
4. **Confirmar/criar o grupo "Qualidade da Performance"** e definir a
   cadência da auditoria (hoje é sob demanda).
5. **Pizzaria Favoritta (Gabrielly)** — fica em "cadastro pendente" porque
   não existe grupo com esse nome no WhatsApp dela.

### Médio prazo
6. **Automatizar o disparo do fluxo Meta Ads** — hoje `/relatorios-ads` é
   manual; o Dashgoo já é automático.
7. **Automatizar a auditoria de Qualidade da Performance** — hoje é
   levantamento manual sob demanda.
8. **Não existe alerta de falha** — só log em `.txt`. Se a automação não
   rodar numa segunda, ninguém é avisado ativamente.

### Risco estrutural
9. **Máquina única.** Tudo depende do Mac do Lucas ligado, com Docker de
   pé e internet, na segunda 10h. Mitigação real só no rebuild.

### Longo prazo — rebuild no Lovable
10. Login com papel (admin × gestor), WhatsApp em servidor sempre-ligado,
    chave de IA em backend (nunca no navegador), ingestão do Dashgoo menos
    frágil (webhook/API em vez de parsing de e-mail), dashboard de
    histórico de envio, confirmação humana antes de auto-cadastro virar
    produção. Checklist completo em `HANDOFF.md` §11.
