# POP — Relatórios semanais via Meta Ads (fluxo "só tráfego")

**Versão:** 1.0
**Data:** 2026-07-09
**Responsável:** Comendo MKT
**Aplica-se a:** Gestores de tráfego que atendem clientes SEM mLabs vinculado

---

## 1. Pra que serve este fluxo

A agência tem dois tipos de cliente:

| Tipo | Como gera relatório |
|---|---|
| **Full-service (pacote com mLabs)** | Dashgoo manda e-mail → automação `relatorios_automacao.py` roda toda segunda 10h → envia relatório pro grupo. **Já funciona hoje, nada muda.** |
| **Só tráfego pago (sem mLabs)** | Este novo fluxo puxa os números direto da conta de anúncios via Meta MCP → envia relatório pro grupo. **É o que este POP explica.** |

Um cliente **nunca deve estar nos dois** — é ou um, ou outro.

---

## 2. Como cadastrar um cliente novo neste fluxo

### Passo 1 — Descobrir o `ad_account_id` do cliente

O `ad_account_id` é o número da conta de anúncios na Meta. Pra achar:

1. Abra o **Gerenciador de Anúncios** logado com um perfil que tenha acesso à conta do cliente.
2. Selecione a conta do cliente no seletor de contas do topo.
3. O número aparece na URL: `https://adsmanager.facebook.com/adsmanager/manage/campaigns?act=112343182536011&...` → o `ad_account_id` é **`112343182536011`** (o número depois do `act=`).

**Observação:** a conta não precisa estar dentro do BM da agência. O MCP funciona com qualquer conta que o Claude tem acesso via login autorizado — inclusive contas do cliente.

### Passo 2 — Ter o grupo do WhatsApp já criado

- O grupo do WhatsApp precisa **já existir** e ter o número do gestor dentro (via instância Evolution `comendo_<seu_nome>`).
- Se sua instância Evolution ainda não existe, fale com o Lucas — ele cria (`comendo_<seunome>`).
- Pra pegar o **ID do grupo** (formato `120363xxxxxxxxxx@g.us`), rode:
  ```bash
  cd ~/Comendo/Projetos/Automacao-Relatorios
  python3 listar_grupos_yago.py   # ou o listar_grupos.py da sua instância
  ```
  E procure o nome do grupo do seu cliente na saída.

### Passo 3 — Cadastrar o cliente no painel

Abra o painel visual (dá 2 cliques em `Painel.command`, ou rode `python3 painel.py` dentro de `~/Comendo/Projetos/Automacao-Relatorios`) e clique em **"+ Adicionar cliente"**:

- Marque o fluxo **"Meta Ads direto (só tráfego)"**.
- Escolha seu gestor, digite o nome do cliente, selecione o grupo do WhatsApp na lista (o painel já busca os grupos da sua instância).
- Preencha o **Ad Account ID** (só números, sem `act_`).
- (Opcional) Preencha **saudação padrão** e **estilo de mensagem** se quiser que o relatório desse cliente saia com um tom diferente do padrão — ex: mais informal, sempre mencionar algo específico.
- Deixe o status como `TESTE` até validar (próximos passos).

Isso grava no banco (`clientes.db`) — não existe mais edição direta de CSV. Se preferir, o cadastro também pode ser feito por linha de comando pelo Lucas com `python3 comendo_db.py listar --fluxo meta_ads` (só leitura) — mas o jeito normal é o painel.

**Referência dos campos** (o que o painel pede):

| Campo | O que preencher |
|---|---|
| Cliente | Nome curto do cliente (é o que aparece na saudação do relatório). |
| Gestor | Seu primeiro nome (com maiúscula: `Yago`, `Marcio`, etc.). |
| Instância | Sua instância Evolution — o painel já lista as que existem. |
| Grupo | Selecionado da lista — o painel busca direto do seu WhatsApp. |
| Ad Account ID | O número da conta de anúncios da Meta (só números, sem `act_`). |
| Status | Ver seção abaixo — **4 valores possíveis**. |

**Valores de `status`:**

| Status | Quando usar | O que a automação faz |
|---|---|---|
| `PENDENTE_ACESSO` | Cliente ainda não deu acesso à conta Meta pro MCP ver. Já cadastrado no painel mas sem `ad_account_id`. | **Pula**, mas avisa no resumo interno pro Lucas cobrar o acesso. |
| `TESTE` | Cadastrado com `ad_account_id`, mas ainda em validação. | **Só envia quando rodar com o flag `teste`** (vai pro celular do Yago, não pro grupo). |
| `OK` | Em produção. | **Envia toda segunda** pro grupo do cliente. |
| `OFF` | Cliente saiu / pausou. | **Ignora sempre**. Mantido só pra histórico. |

**Muito importante:** confirme com o Lucas que o cliente **não** está cadastrado no fluxo Dashgoo (`python3 comendo_db.py listar --fluxo dashgoo`). Se estiver nos dois, a automação avisa mas prefere não enviar duplicado.

### Passo 4 — Rodar em modo simulação

Peça pro Lucas (ou rode você mesmo se tiver Claude Code) o comando:

```
/relatorios-ads simulacao apenas=<Nome do Cliente>
```

Isso **não envia nada**. Só mostra na tela como ficaria o relatório. Confira:

- O nome do cliente tá certo?
- O emoji do nicho ficou bom? (Se não, avise pro Lucas ajustar.)
- Os números batem com o que você vê no Gerenciador?
- A conclusão faz sentido?

### Passo 5 — Rodar em modo teste (envia pro celular do Yago)

```
/relatorios-ads teste apenas=<Nome do Cliente>
```

Isso envia pro celular do Yago (`5519999167515`) — não pro grupo do cliente. Ele confere no zap e te dá o OK.

### Passo 6 — Ativar em produção

Troque o **Status** do cliente de `TESTE` pra **`OK`** no painel (editar cliente) e pronto. Na próxima segunda o relatório vai automaticamente pro grupo.

---

## 3. Regras de classificação (o que a automação faz sozinha)

Ela lê **todas as campanhas do cliente** com gasto > R$ 0 nos últimos 7 dias e classifica cada uma pelo **objetivo da campanha** (o campo `objective` da Meta):

**Topo de funil (aparece no bloco "Atração de Clientes / Visibilidade da Marca"):**
Reconhecimento, Alcance, Tráfego, Engajamento, Cliques no link, Visualizações de vídeo, Curtidas na página.

**Fundo de funil (aparece nos blocos "Vendas no Delivery / Reservas e Contatos"):**
Vendas, Cadastros, Conversões, Mensagens, Catálogo de produtos, Visitas à loja.

**Você não precisa fazer nada especial no nome da campanha** — a classificação usa o campo `objective` que a Meta preenche sozinha quando você escolhe o objetivo na criação.

Se um objetivo aparecer que não estiver mapeado, a automação joga como **fundo por segurança**. Se algum bloco não tiver dado, ele é **omitido** (não aparece campo em branco).

---

## 4. O que o cliente NUNCA vê

- Bloco "Movimento da Marca (Orgânico)" — esse é do mLabs (dados de perfil, seguidores, alcance orgânico). Cliente sem mLabs não tem esse dado, então o bloco é omitido.
- Nomes internos de campanha, IDs, conta de anúncios.
- Detalhes técnicos ou erros da automação.

---

## 5. Quando algo dá errado

- **Grupo mudou de ID** (recriaram o grupo) → edite o cliente no painel e escolha o grupo novo.
- **Cliente saiu da carteira** → mude `status` pra `OFF` (ou apague a linha, mas prefiro `OFF` pra manter histórico).
- **Cliente parou de anunciar essa semana** → automação detecta gasto = R$ 0 e **não envia nada** (pula, avisa só no resumo interno).
- **Relatório saiu com número errado** → me chama (Lucas) com o print. Provavelmente é uma campanha classificada errado ou uma métrica que a Meta calcula diferente do Dashgoo — a gente ajusta.
- **Automação não rodou na segunda** → confere se o computador do Lucas dormiu. Log em `automacao_ads_log.txt` e `automacao_ads_erro.txt`.

---

## 6. Checklist rápido pra você (gestor) antes de pedir ativação

- [ ] Cliente **não** está cadastrado no fluxo Dashgoo.
- [ ] `ad_account_id` copiado da URL do Gerenciador de Anúncios (só o número, sem `act_`).
- [ ] Grupo WhatsApp criado e sua instância Evolution é membro.
- [ ] Cliente cadastrado no painel (fluxo Meta Ads) com `status=TESTE`.
- [ ] Rodou `simulacao` e revisou o texto.
- [ ] Rodou `teste` e Yago confirmou.
- [ ] Trocou `status` pra `OK`.

---

## 7. Acesso aos dados da Meta: BM central (decisão atual)

**Decisão (16/07/2026):** em vez de cada gestor conectar o próprio MCP com o
próprio login Meta, todo mundo coloca os clientes de Meta Ads na **BM
(Business Manager) central da Comendo Marketing**. O MCP que roda
`/relatorios-ads` (hoje conectado no Claude Code do Lucas) enxerga a conta
de anúncios de qualquer cliente que esteja dentro dessa BM — não precisa de
um conector por gestor.

**O que isso muda na prática, pro gestor:**

1. **Adicione a conta de anúncios do cliente na BM central da Comendo
   Marketing** (Meta Business Suite → Configurações do negócio → Contas →
   Contas de anúncio → dar acesso à BM da agência), em vez de só na sua BM
   pessoal.
2. Cadastre o cliente no painel normalmente (fluxo Meta Ads, `ad_account_id`,
   seu nome como gestor — ver seção 2). O comando puxa e envia **conforme o
   que estiver cadastrado no painel pra cada cliente** — o gestor não
   precisa mexer em nada além do cadastro.
3. Pra rodar só os seus clientes (em vez de todos), use
   `/relatorios-ads gestor=<SeuNome>`.

**O que isso resolve:** não precisa mais de "cada gestor com seu próprio
conector MCP configurado" — um único MCP (na BM central) cobre todo mundo.
Isso também simplifica quem roda o comando: como o acesso já é centralizado,
normalmente é o Lucas quem dispara `/relatorios-ads` (com ou sem
`gestor=`), não cada gestor na própria máquina.

**O que ainda não está resolvido:** se algum dia um gestor quiser rodar o
comando **por conta própria, na própria máquina** (não só filtrar o
resultado, mas efetivamente executar o Claude Code dele), ainda esbarra em
duas coisas — (a) precisaria do próprio Claude Code + acesso à BM central
via login dele, e (b) `clientes.db` hoje só existe no Mac do Lucas
(`~/Comendo/Projetos/Automacao-Relatorios/clientes.db`); rodar de outra
máquina exigiria um banco compartilhado (pasta sincronizada tipo iCloud
Drive/Dropbox, ou banco na nuvem) — isso é um passo de infraestrutura
maior, não prioritário agora que o acesso via BM central resolve o caso de
uso principal. Fala com o Lucas se quiser priorizar isso.

---

## 8. Contato

Dúvida, erro, ajuste do template → Lucas França (`domingues.lucas1@icloud.com`).
