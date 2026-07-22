---
description: Gera narração com voz clonada (ElevenLabs) a partir da copy do time — fluxo guiado (tom → voz → copy).
argument-hint: (opcional) cole a copy + nome do cliente, ou deixe vazio para o fluxo guiado
---

Você vai gerar uma **narração com voz humana clonada** (ElevenLabs) para a
Comendo MKT. Siga o processo da skill `comendo-narracao`
(`.claude/skills/comendo-narracao/SKILL.md`) — leia-a se precisar dos detalhes.

## Regra de ouro
A copy do time entra **VERBATIM**. Nunca reescrever, nunca mudar POV, nunca
"melhorar". A adaptação fonética (abrasileirar) é automática no script e só
afeta o texto que vai ao motor de voz.

## Fluxo guiado (conduza nesta ordem)
1. **Pergunte o TOM** com `AskUserQuestion` — opções **Média** (padrão
   acolhedor: família, tradição), **Empolgada** (fast food, delivery, promoção,
   jovem) e **Calma** (premium, ticket alto). Cada uma com descrição/preview.
2. **Pergunte a VOZ** — **Vitória** (recomendada, feminina aprovada), **Lucas**
   (masculina aprovada), Daniel/Eduardo (interinas). Pode juntar tom + voz num
   único `AskUserQuestion` (duas perguntas).
3. **Peça a copy + nome do cliente** (e briefing, se houver), caso não tenham
   vindo em `$ARGUMENTS`.
4. **Mostre o texto abrasileirado** antes de gerar (não gasta cota):
   ```bash
   narracao-ia/scripts/narra --voz <voz> --tom <tom> --arquivo <copy.txt> --mostrar-texto
   ```
   Itere com o usuário se algum termo ficar estranho.
5. **Salve a copy** em `narracao-ia/clientes/<Cliente>/testes/copy.txt` e **gere**:
   ```bash
   narracao-ia/scripts/narra --voz <voz> --tom <tom> \
     --arquivo "narracao-ia/clientes/<Cliente>/testes/copy.txt" \
     --saida "narracao-ia/clientes/<Cliente>/testes/<Cliente> - <tom>.mp3"
   ```
   O wrapper injeta a chave (do `.env` na raiz ou do secret do environment) e o
   ffmpeg automaticamente.
6. **Entregue o mp3** ao usuário (`SendUserFile`) e itere até aprovar. Ao
   aprovar, copie para a raiz da pasta do cliente com prefixo `APROVADO - ...mp3`.

## Se a chave não estiver configurada
Se o wrapper reclamar de `ELEVENLABS_API_KEY`, avise o usuário para configurá-la
como variável do environment (ícone de nuvem → engrenagem → Environment
variables) ou criar um `.env` na raiz a partir de `.env.example`.

Contexto adicional do usuário (copy/cliente, se fornecido): $ARGUMENTS
