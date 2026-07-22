---
name: narra-onboarding
description: Transforma copy pronta do time da Comendo MKT em narração com voz humana clonada (ElevenLabs) para vídeos de onboarding e campanhas de captação. Use quando o Lucas colar uma copy + nome do cliente e pedir para narrar. Classifica o tom, aplica a camada de pronúncia abrasileirada e gera o áudio na voz certa, salvando na pasta do cliente.
---

# /narra-onboarding — Narração por voz clonada (Comendo MKT)

## Regra de ouro
A copy do time entra **VERBATIM**. Nunca reescrever, nunca mudar POV, nunca
"melhorar". Só se adapta **foneticamente** o texto que vai ao motor de voz — e
isso o `narrar.py` já faz sozinho na camada de pronúncia.

## Fluxo guiado (padrão para o chat dos operadores)
Sempre conduza nesta ordem, usando o pop-up `AskUserQuestion`:

1. **Pergunte o TOM** com `AskUserQuestion` (opções: Média / Empolgada / Calma,
   cada uma com descrição e preview do que muda). Se der pra inferir do cliente,
   marque a opção provável como "(recomendado)" em primeiro.
2. **Pergunte a VOZ** (Vitória recomendada / Lucas / Daniel / Eduardo).
   Pode perguntar tom e voz no mesmo `AskUserQuestion` (duas perguntas).
3. **Peça a copy + nome do cliente** (e briefing, se houver).
4. **Mostre o texto abrasileirado** com `--mostrar-texto` (dry-run, não gasta
   cota) antes de gerar. Itere se algum termo ficar estranho.
5. **Gere**, entregue o mp3, e itere até aprovar.

## Fluxo (resumo técnico)
O Lucas cola: **copy + nome do cliente + 1-2 linhas de briefing**.
Você então:

1. **Classifica o tom** a partir do briefing/cliente:
   - `empolgada` — fast food, delivery, promoção, público jovem
   - `media` — família, tradição, acolhedor *(padrão quando em dúvida)*
   - `calma` — premium, sofisticado, ticket alto
2. **Escolhe a voz** (padrão `vitoria`, feminina aprovada). Só usa outra se o
   Lucas pedir. `lucas` (masculina) também está aprovada. **Não** usar `francis`
   (reprovada, robótica) sem aviso.
3. **Salva a copy** em `clientes/<Cliente>/testes/copy.txt`.
4. **Gera** com o script:
   ```bash
   ELEVENLABS_API_KEY=... FFMPEG_BIN=~/.local/bin/ffmpeg \
   python3 scripts/narrar.py --voz vitoria --tom <tom> \
     --arquivo clientes/<Cliente>/testes/copy.txt \
     --saida "clientes/<Cliente>/testes/<Cliente> - <tom>.mp3"
   ```
   (ou use o wrapper `scripts/narra` que já injeta chave/ffmpeg)
5. **Confere a camada de pronúncia** antes de gerar, com `--mostrar-texto`, e
   itera com o Lucas se algum termo abrasileirado ficar estranho.
6. **Entrega** o mp3 pro Lucas. Iterações vão em `testes/`. Quando ele aprovar,
   renomeia pra raiz da pasta do cliente com prefixo `APROVADO - ...mp3`.

## Preferências do Lucas (importantes)
- Prefere narração **enxuta e ágil** — acabamento acelerado já é padrão.
- Quando a medição diz "está igual" e o ouvido dele diz "não está", **o ouvido
  está certo**. Procurar a causa em outra dimensão.
- **Não inventar complexidade.** Clone limpo + params padrão + ajuste uniforme.
- Entregas longas vão para arquivo, não impressas no chat.

## Parâmetros técnicos
Ver `scripts/narrar.py` (fonte da verdade) e `docs/HANDOFF-NARRACAO.md`. Resumo:
- Modelo `eleven_multilingual_v2` — **NUNCA** `eleven_v3` (inventa sotaque).
- Output `mp3_44100_128` (máximo do plano Starter).
- Acabamento: domador de picos (sempre) + ritmo enxuto (silenceremove + atempo).

## Camada de pronúncia (abrasileirar) — já automática no script
`delivery→delíveri` · `catupiry→catupirí` · `Seo→Seu` · `self service→sélfi sérvice`
· `500g→quinhentos gramas`. Termos novos: achar a grafia PT que reproduz a fala
real (referência: Google Tradutor em PT). Adicionar em `SUBS_PRONUNCIA` no script.

## Vozes (voice_id)
| Alias | voice_id | Status |
|---|---|---|
| vitoria | ybcErWwDz8ZBwtYt8cwD | ✅ oficial (feminina) |
| lucas | JrsSi780rKB0vvPdkEsF | ✅ aprovada (masculina) |
| francis | EfZInModTDcSzE4ZSGRb | ⚠️ reprovada (robótica) |
| daniel | czvzJwIVS2asEKnthV40 | interina |
| eduardo | 83Nae6GFQiNslSbuzmE7 | interina |
