# Guia do Operador — chat de uso da narração

Este é o guia do **chat de USO** (para o time gerar narrações no dia a dia).
As mudanças técnicas (parâmetros, vozes novas, pronúncias) são feitas no **chat
técnico do Lucas** e chegam aqui via `git pull`.

## Como gerar uma narração
1. Digite **`/narra-onboarding`**.
2. O assistente vai te perguntar, em pop-up:
   - **Tom** — Média (padrão acolhedor) / Empolgada (fast food, promoção) /
     Calma (premium).
   - **Voz** — Vitória (padrão) / Lucas / Daniel / Eduardo.
3. **Cole a copy + o nome do cliente** (e 1-2 linhas de briefing, se tiver).
4. Ele te mostra o texto abrasileirado (confira) e gera o áudio.
5. Ouça. Se precisar, peça ajuste (tom, voz, ritmo, pronúncia). Quando aprovar,
   ele salva a versão final.

## Regras que o time deve respeitar
- **A copy entra verbatim.** Não peça pra "melhorar" ou reescrever — só adaptação
  fonética, que é automática.
- **Vozes aprovadas:** Vitória e Lucas. Evite Francis (soa robótica).
- Dúvida de pronúncia de um termo novo? Avise o Lucas — ele adiciona na camada.

## O que NÃO fazer aqui
- Mexer em `scripts/` ou parâmetros — isso é no chat técnico.
- Trocar a chave da API — idem.
