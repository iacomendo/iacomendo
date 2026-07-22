# Migração para a conta ElevenLabs da Comendo Marketing

Quando for trocar da conta atual para a conta oficial da **Comendo Marketing**.

## 1. Trocar a chave (rápido)
A chave nunca está no código — vive só no `.env` (gitignorado). Migrar =
substituir uma linha:

```bash
# no .env
ELEVENLABS_API_KEY=<nova_chave_da_comendo>
```

Pronto. Todo o resto (scripts, tons, pronúncia) continua igual.

## 2. ⚠️ ATENÇÃO: os voice_id são POR CONTA (não migram sozinhos)
Este é o ponto que costuma pegar. Os IDs em `scripts/narrar.py` (`VOZES`)
pertencem à conta **atual**. Na conta da Comendo eles **não existem** até você:

- **Opção A — Re-clonar** cada voz na conta nova, seguindo a receita validada
  (§5 do handoff): áudios de voz crua de microfone, ~5 min, arquivos separados,
  `remove_background_noise=true`. Isso gera **novos** voice_id.
- **Opção B — Compartilhar** as vozes da conta atual com a conta da Comendo
  (recurso de sharing da ElevenLabs), se as duas contas puderem ser vinculadas.

Depois, **atualizar o dicionário `VOZES`** em `scripts/narrar.py` com os novos IDs.

Para listar os voice_id de uma conta:
```bash
curl -sS https://api.elevenlabs.io/v2/voices?page_size=100 \
  -H "xi-api-key: $ELEVENLABS_API_KEY" \
  | python3 -c "import sys,json;[print(v['voice_id'], v['name']) for v in json.load(sys.stdin)['voices']]"
```

## 3. Conferir o plano da conta nova
- Se continuar **Starter**: output máx `mp3_44100_128`, sem PVC. (é o que usamos.)
- Se for **Creator+**: libera 192 kbps e Professional Voice Cloning (resolveria
  o caso do Francis — ver handoff §12.1).
- Se der erro de cota mesmo com plano ativo: checar o limite **da própria API
  key** no painel (Profile → API Keys) — pode estar capada em 0.

## 4. Checklist de migração
- [ ] Nova chave no `.env`
- [ ] Vozes re-clonadas ou compartilhadas na conta nova
- [ ] `VOZES` em `scripts/narrar.py` atualizado com os novos voice_id
- [ ] Rodar 1 teste curto por voz e conferir de ouvido
- [ ] Confirmar plano/cota da conta
