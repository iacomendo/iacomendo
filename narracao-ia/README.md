# Sistema de Narração por IA — Comendo MKT

Transforma **copy pronta do time** em **narração com voz humana clonada**
(ElevenLabs), para vídeos de onboarding e campanhas de captação de leads.

> **Regra de ouro:** a copy do time entra **verbatim**. Nunca reescrever, nunca
> mudar POV, nunca "melhorar". Só se adapta **foneticamente** o texto que vai ao
> motor de voz.

## Setup

```bash
# 1. ffmpeg estático user-space (se ainda não tiver)
#    baixe de https://johnvansickle.com/ffmpeg/ e copie para ~/.local/bin/

# 2. chave da API
cp .env.example .env      # e preencha ELEVENLABS_API_KEY
```

## Uso rápido

```bash
# gerar narração
scripts/narra --voz vitoria --tom empolgada \
  --arquivo clientes/DeVitis/testes/copy.txt \
  --saida "clientes/DeVitis/testes/DeVitis - empolgada.mp3"

# ver o texto abrasileirado que vai ao motor (dry-run, sem gastar cota)
scripts/narra --voz vitoria --tom media --arquivo copy.txt --mostrar-texto
```

Ou, pelo Claude Code, digite `/narra-onboarding` e cole a copy + cliente + briefing.

### Flags do `narrar.py`
| Flag | Valores | Nota |
|---|---|---|
| `--voz` | vitoria \| lucas \| francis \| daniel \| eduardo | padrão prático: `vitoria` |
| `--tom` | empolgada \| media \| calma | `media` é o padrão em dúvida |
| `--arquivo` / `--texto` / stdin | — | fonte da copy |
| `--saida` | caminho .mp3 | obrigatório (exceto dry-run) |
| `--sem-acabamento` | — | pula domador de picos + ritmo |
| `--sem-pronuncia` | — | pula abrasileiramento automático |
| `--mostrar-texto` | — | dry-run: mostra o texto do motor e sai |

## Tons (parâmetros validados)
| Tom | stability | similarity | style | Quando usar |
|---|---|---|---|---|
| empolgada | 0.40 | 0.90 | 0.35 | fast food, delivery, promoção, jovem |
| media | 0.55 | 0.90 | 0.15 | família, tradição, acolhedor *(padrão)* |
| calma | 0.70 | 0.90 | 0.10 | premium, sofisticado, ticket alto |

Modelo: `eleven_multilingual_v2` (**nunca** `eleven_v3` — inventa sotaque).
Output: `mp3_44100_128`. `use_speaker_boost: true` sempre.

## Estrutura
```
scripts/narrar.py     motor (fonte da verdade dos parâmetros)
scripts/narra         wrapper (injeta chave + ffmpeg)
.claude/skills/narra-onboarding/SKILL.md   comando /narra-onboarding
docs/HANDOFF-NARRACAO.md       handoff completo (receitas, o que foi reprovado, pendências)
clientes/<Cliente>/   saídas; testes/ (iterações), raiz (APROVADO - ...mp3)
```

Detalhes completos, receita de clonagem, o que foi reprovado e pendências:
ver [`docs/HANDOFF-NARRACAO.md`](docs/HANDOFF-NARRACAO.md).
