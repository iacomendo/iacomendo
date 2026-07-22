# HANDOFF — Sistema de Narração por IA da Comendo MKT

> Documento de transferência. Contém tudo: comandos, arquivos, vozes, receitas validadas, o que já foi testado e reprovado, e o que está pendente.
> Última atualização: 2026-07-22

---

## 1. O que esse sistema faz

Transforma **copy pronta do time** em **narração com voz humana clonada**, para os vídeos de onboarding e para campanhas de captação de leads.

**Fluxo:** Lucas cola a copy + diz qual cliente → o Claude classifica o tom, aplica a camada de pronúncia abrasileirada, gera o áudio na voz certa e salva na pasta do cliente.

**Regra de ouro:** a copy do time entra **verbatim**. Nunca reescrever, nunca mudar POV, nunca "melhorar". Só se adapta foneticamente o texto que vai ao motor de voz.

---

## 2. Setup necessário

### Ferramentas (todas já instaladas, user-space, sem sudo)

| Ferramenta | Para quê | Caminho / instalação |
|---|---|---|
| `ffmpeg` | processamento de áudio | `~/.local/bin/ffmpeg` |
| `yt-dlp` | baixar áudio de reels do Instagram | `~/.local/bin/yt-dlp` |
| `transcrever` | transcrição local (faster-whisper), grátis | `~/.local/bin/transcrever` |
| `demucs` | separar voz de música de fundo | `uv tool install demucs --with numpy --with soundfile` |

⚠️ **demucs:** o pacote **não declara numpy**. Sem `--with numpy` quebra com `ModuleNotFoundError`.
Uso: `demucs --two-stems=vocals -o <saida> <arquivos>` → gera `vocals.wav` e `no_vocals.wav`.

### ElevenLabs

- **Chave:** `ELEVENLABS_API_KEY` em `~/Developer/video-use/.env`
- **Plano atual:** **Starter**
  - Instant Voice Cloning (IVC): ✅ liberado
  - Professional Voice Cloning (PVC): ❌ **bloqueado** (exige plano Creator)
  - Output máximo: `mp3_44100_128` (192 kbps exige Creator)
  - Upload de treino: **máximo 11 MB por arquivo**
- ⚠️ Se der erro de cota, checar o **limite da própria API key** no painel (Profile → API Keys) — ela pode estar capada em 0 mesmo com plano ativo.

---

## 3. As vozes clonadas

| Alias | voice_id | Quem é | Status |
|---|---|---|---|
| `vitoria` | `ybcErWwDz8ZBwtYt8cwD` | Narradora oficial (feminina) | ✅ **Aprovada** — "maestria e perfeição" |
| `lucas` | `JrsSi780rKB0vvPdkEsF` | Voz do Lucas (masculina) | ✅ Aprovada |
| `francis` | `EfZInModTDcSzE4ZSGRb` | Francis, CEO (masculina) | ⚠️ **Reprovada** — soa robótica (ver §9) |
| `daniel` | `czvzJwIVS2asEKnthV40` | BR masculina genérica | interina |
| `eduardo` | `83Nae6GFQiNslSbuzmE7` | BR masculina genérica | interina |

Vozes antigas do Francis (não usar): `fhgiP1p9WBugy2EWdCiF`, `pWLgn1Kh8MPwjOtTFTaZ`.

---

## 4. O comando `/comendo-narracao`

**Localização:** `~/.claude/skills/comendo-narracao/`
- `SKILL.md` — instruções do processo
- `narrar.py` — script que gera o áudio

**Uso pelo Lucas:** digitar `/comendo-narracao` e colar a copy + nome do cliente + 1-2 linhas de briefing.

**Uso direto do script:**
```bash
cd ~/.claude/skills/comendo-narracao
python3 narrar.py --voz vitoria --tom empolgada --arquivo texto.txt --saida saida.mp3
```
Flags: `--voz` (vitoria|lucas|francis|daniel|eduardo) · `--tom` (empolgada|media|calma) · `--sem-acabamento`

---

## 5. Receita validada de clonagem (a que deu certo na Vitória)

1. **Fonte:** gravações de **voz crua direto no microfone** (áudios de WhatsApp / Voice Memos). **NÃO** áudio extraído de vídeo produzido.
2. **Quantidade:** ~5 min.
3. **Preparo de cada arquivo:** `highpass=f=60, loudnorm=I=-16:TP=-1.5:LRA=11`, 48 kHz mono, **sem lowpass** (lowpass abafa o clone).
4. **Envio:** **arquivos separados** (~10), nunca um arquivo concatenado.
5. **Criação:** `POST /v1/voices/add` com `remove_background_noise=true`.

```bash
curl -X POST https://api.elevenlabs.io/v1/voices/add -H "xi-api-key: $KEY" \
  -F "name=Nome" -F "remove_background_noise=true" \
  -F "files=@a1.wav" -F "files=@a2.wav" ...
```
Re-treinar a mesma voz: `POST /v1/voices/{voice_id}/edit` (mesmos campos).

---

## 6. Geração — parâmetros validados

**Modelo:** `eleven_multilingual_v2`
⚠️ **NÃO usar `eleven_v3`** — ele dramatiza e **inventa sotaque** (apareceu um "carioca fantasma" que não existia).

| Tom | stability | similarity_boost | style | Quando usar |
|---|---|---|---|---|
| `empolgada` | 0.40 | 0.90 | 0.35 | fast food, delivery, promoção, público jovem |
| `media` | 0.55 | 0.90 | 0.15 | família, tradição, acolhedor *(padrão)* |
| `calma` | 0.70 | 0.90 | 0.10 | premium, sofisticado, ticket alto |

`use_speaker_boost: true` sempre. Output: `mp3_44100_128`.

---

## 7. Camada de pronúncia (abrasileirar)

Aplicar **só no texto que vai ao motor**. A copy do time permanece intacta.

| Armadilha | Correção | Status |
|---|---|---|
| `delivery` | **`delíveri`** | ✅ validado (erraram `delivéri` e `delivêri`) |
| `500g` | `quinhentos gramas` | ✅ validado |
| `Seo Venâncio` | `Seu Venâncio` (Seo = Seu, não "Céu") | ✅ validado |
| `catupiry` | `catupirí` (oxítona) | ✅ validado |
| `self service` | `sélfi sérvice` | ⚠️ a confirmar |
| `Valença 1` | `Valença um` | números por extenso |
| Nomes sem acento | acentuar p/ tônica correta (ex.: `Eurípes`) | — |

**Regra:** achar a grafia em PT que reproduz a fala real. Referência: pronúncia do Google Tradutor em português. Iterar com o Lucas quando houver dúvida.

---

## 8. Acabamento de áudio (já embutido no `narrar.py`)

**Domador de picos (sempre):** evita estouros tipo o que apareceu na palavra "Reúna".
```
acompressor=threshold=-16dB:ratio=3.5:attack=8:release=180:makeup=1.5,alimiter=limit=0.9
```

**Ritmo enxuto (Lucas pediu "mais rápido" em dois clientes seguidos):**
```
silenceremove=stop_periods=-1:stop_duration=0.15:stop_threshold=-34dB:stop_silence=0.10
+ atempo=1.10 (empolgada/média) ou 1.12 (calma)
```

⚠️ **Bug de ffmpeg que custou uma rodada:** o corte tem que vir **antes** do `-i`.
`ffmpeg -ss A -to B -i in.wav -af atempo=F out.wav`
Com `-ss/-to` depois do `-i`, o corte age na saída e **anula o filtro**. Sempre conferir se a duração do pedaço mudou.

---

## 9. ❌ O que foi REPROVADO — não repetir

### 9.1 Esculpir "swing" de tempo cortando o áudio em pedaços
Tentativa de recriar a variação de velocidade do Francis cortando o áudio e aplicando `atempo` diferente por trecho.
**Veredito do Lucas:** *"aceleração ridícula no começo, freada brusca no meio, horrorosas, MUITO robótico"*.
Cada corte cria artefato e degrau audível. **A prosódia natural do modelo é o que temos** — foi suficiente para a Vitória.

### 9.2 Hipóteses testadas e descartadas no clone do Francis
| # | Hipótese | Resultado |
|---|---|---|
| 1 | Pouco material de treino | testado com 1,7 / 4,2 / 4,7 min — não resolveu |
| 2 | Música de fundo no treino | demucs aplicado; vídeos do CEO já eram limpos — não resolveu |
| 3 | Arquivo concatenado vs separados | refeito com separados — não resolveu |
| 4 | Swing de tempo por trecho | **piorou muito** — reprovado |
| 5 | `loudnorm` achatando a dinâmica | **medido e refutado** (4,6 dB vs 4,7 dB cru) |
| 6 | Parâmetros de geração (0.28→0.55) | nenhum resolveu |

### 9.3 Medições que NÃO funcionam
- **`silencedetect` para detectar música de fundo:** dá falso positivo com fala contínua. O teste certo é separar com demucs e medir o RMS do stem `no_vocals` (< −50 dB = limpo).
- **Detector de pitch/F0 caseiro para identificar locutor:** reprovou na calibração (voz masculina conhecida mediu mais alto que a feminina conhecida). Não usar.
- **Comparar wpm entre áudios com segmentações diferentes:** trechos < 2s dão leituras infladas (263, 300, 429 wpm) e poluem a estatística. Filtrar `duração >= 2s`.

---

## 10. Estrutura de pastas

```
~/Comendo/Projetos/agente ia clonar voz/
├── _vozes-treino/
│   ├── vitoria/                    10 áudios de WhatsApp (fonte que deu certo)
│   ├── lucas-voicememos/           9 Voice Memos do Lucas
│   └── francis-ceo/                8 vídeos + ROTEIRO DE GRAVACAO - Francis.md
└── clientes/
    ├── <Nome do Cliente>/
    │   ├── APROVADO - ....mp3      versões aprovadas (raiz)
    │   └── testes/                 iterações
```

**Convenção:** saída sempre em `clientes/<Cliente>/`. Iterações em `testes/`, aprovados na raiz com prefixo `APROVADO`.

---

## 11. Clientes entregues

| Cliente | Voz | Tom | Status |
|---|---|---|---|
| Seo Venâncio | Vitória + voz do Lucas | média | ✅ aprovado |
| De Vitis Pizza | Vitória | empolgada + ritmo rápido | ✅ aprovado |
| Zenko | Vitória | calma, +12% e +20% | ✅ aprovado (duas versões) |
| Cantinho | Vitória | empolgada / média | ⏳ aguardando escolha do Lucas |

---

## 12. ⏳ Pendências

### 12.1 Voz do Francis (prioridade — é pra campanha de captação)
**Bloqueio:** o clone soa robótico ("fala todas as palavras do mesmo jeito, sem humanização").

**Causa provável:** a fonte é **áudio extraído de vídeo produzido** (já passou por compressão, EQ e nivelamento na edição). A Vitória foi clonada de **voz crua de microfone** — e o resultado foi excelente. Essa é a única variável nunca testada.

**Próximo passo:** o Francis gravar 2–3 min seguindo o roteiro em
`_vozes-treino/francis-ceo/ROTEIRO DE GRAVACAO - Francis.md`
(6 blocos de ~30s com energias diferentes — natural, copy de captação, empolgado, explicativo, números, e improviso livre).

**Plano B:** Professional Voice Cloning — exige upgrade para plano **Creator**. Já há **41,9 min** de material do Francis baixado do perfil, acima do mínimo de 30 min do PVC.

### 12.2 Outras
- Cantinho: confirmar tom escolhido e a pronúncia de `sélfi sérvice`
- Vozes femininas adicionais: Lucas mencionou que enviará áudios de outras narradoras

---

## 13. Perfil de referência

- **Instagram:** `@comendoporcampinas` (546K seguidores) — conteúdo narrado pelo Francis (`@francis.s.medeiros`)
- Reels públicos podem ser baixados com `yt-dlp` **sem login**

---

## 14. Memórias do projeto

Em `~/Comendo/Projetos/memory/` (symlink em `~/.claude/projects/-Users-franca-Comendo-Projetos/memory/`):

- **`padrao-narracao-onboarding.md`** — receita técnica completa, parâmetros, camada de pronúncia, acabamento, o que foi reprovado
- **`automacao-narracao-onboarding.md`** — o projeto, voice_ids, status do Francis, hipóteses descartadas
- `copy-lead-comendo-esqueleto.md` · `ganchos-adspogere-validados.md` · `brand-comendo-marketing.md`

---

## 15. Regras de trabalho com o Lucas (importantes)

1. **Nunca reescrever a copy do time.** Ela entra verbatim.
2. **Ele prefere narração enxuta e ágil** — pediu "mais rápido" em clientes seguidos. Acabamento acelerado é padrão.
3. **Quando a medição diz "está igual" e o ouvido dele diz "não está", o ouvido está certo.** Procurar a causa em outra dimensão em vez de defender o número.
4. **Não inventar complexidade.** A solução que funcionou (Vitória) é simples: clone limpo + params padrão + ajuste uniforme. Toda a elaboração extra que foi adicionada no Francis piorou o resultado.
5. Entregas longas vão para arquivo, não impressas no chat.
