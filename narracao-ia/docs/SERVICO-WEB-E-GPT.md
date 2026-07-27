# Serviço de narração — página web + GPT personalizado

O `servidor.py` expõe o **mesmo motor** (`scripts/narrar.py`) em duas pontas:

- **Página web** — o time cola a copy, escolhe voz e tom, e baixa o MP3.
  Não exige saber Claude nem ChatGPT.
- **API JSON** — para o **GPT personalizado** (Action) e outras integrações.

> Um serviço só, uma chave só. O time nunca disputa login do Fish Audio,
> porque quem fala com o Fish é o servidor, não as pessoas.

---

## 1. Rodar localmente (teste)

```bash
export FISH_API_KEY=...                 # ou ELEVENLABS_API_KEY
export NARRA_WEB_TOKEN=umtokenqualquer  # senha compartilhada do time
export FFMPEG_BIN=~/.local/bin/ffmpeg
python3 narracao-ia/servidor.py
```
Abra `http://127.0.0.1:8080/?t=umtokenqualquer`.

## 2. Colocar no ar (produção)

O serviço é **stdlib puro** — não precisa instalar nada. Em qualquer provedor
(Render, Railway, Fly, VPS, ou o mesmo servidor da automação de relatórios):

| Variável | Valor |
|---|---|
| `FISH_API_KEY` | chave do Fish Audio |
| `NARRA_WEB_TOKEN` | uma senha longa, compartilhada com o time |
| `NARRA_PUBLIC_URL` | `https://seu-dominio` (entra nos links e no openapi) |
| `NARRA_HOST` | `0.0.0.0` |
| `PORT` | a porta que o provedor injetar |
| `NARRA_MOTOR` | `fish` (padrão) ou `elevenlabs` |

Comando de start: `python3 narracao-ia/servidor.py`

⚠️ **ffmpeg:** sem ele o acabamento (domador de picos + ritmo) não roda — o
áudio sai cru, mas **não falha**. Para ter o acabamento, instale o ffmpeg no
servidor e aponte `FFMPEG_BIN`.

### O link que o time usa
```
https://seu-dominio/?t=<NARRA_WEB_TOKEN>
```
Basta salvar nos favoritos. Sem cadastro, sem login individual.

---

## 3. Configurar o GPT personalizado (ChatGPT)

1. No ChatGPT: **Explorar GPTs → Criar → Configurar**.
2. Em **Instruções**, cole:

   > Você gera narrações da Comendo MKT. Quando o usuário enviar uma copy,
   > chame a action `gerarNarracao` com o texto **exatamente como recebido**
   > (VERBATIM — nunca reescreva, nunca "melhore", nunca mude o ponto de vista).
   > Antes de chamar, pergunte a **voz** e o **tom** se não vierem informados.
   > Tons: `empolgada` (promoção, fast food, público jovem), `media`
   > (acolhedor, família — padrão) e `calma` (premium, ticket alto).
   > Ao receber a resposta, entregue o **link do MP3** ao usuário.

3. Em **Actions → Criar nova action**:
   - **Schema:** cole o conteúdo de `https://seu-dominio/openapi.json`
   - **Autenticação:** *API Key* → tipo **Custom** → nome do header `X-API-Key`
     → valor: o `NARRA_WEB_TOKEN`
4. Salvar. Teste pedindo: *"gera uma narração pro Cantinho, voz Vitória, tom
   empolgada"* + a copy.

> **Limitação real do ChatGPT:** uma Action devolve texto/JSON, não arquivo.
> Por isso o GPT responde com um **link** para o MP3 (hospedado pelo serviço),
> e não com o áudio anexado. Na página web o download é direto.

---

## 4. Rotas

| Rota | Para quê |
|---|---|
| `GET /?t=<token>` | página web do time |
| `POST /api/narrar` | gera o áudio (header `X-API-Key`) |
| `GET /audio/<arquivo>.mp3` | baixa/toca o áudio |
| `GET /openapi.json` | schema para a Action do GPT |
| `GET /saude` | healthcheck (motor e vozes ativas) |

### Exemplo de chamada
```bash
curl -X POST https://seu-dominio/api/narrar \
  -H "Content-Type: application/json" -H "X-API-Key: $NARRA_WEB_TOKEN" \
  -d '{"texto":"Sua copy aqui","voz":"vitoria","tom":"empolgada","cliente":"Cantinho"}'
```
Resposta:
```json
{"url":"https://seu-dominio/audio/Cantinho-vitoria-empolgada-ab12cd34.mp3",
 "duracao":17.2,"texto_narrado":"Sua copy já abrasileirada"}
```

---

## 5. Segurança — o que considerar

- O `NARRA_WEB_TOKEN` é **uma senha compartilhada**. Quem tiver o link gera
  áudio (e gasta crédito). Trate como senha interna; troque se vazar.
- Os MP3 gerados ficam acessíveis por URL a quem souber o nome do arquivo
  (nome inclui um id aleatório). Não coloque conteúdo sigiloso.
- As chaves (`FISH_API_KEY`, `ELEVENLABS_API_KEY`) ficam **só no servidor** —
  nunca chegam ao navegador nem ao ChatGPT.
