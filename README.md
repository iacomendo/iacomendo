# Comendo MKT — Monorepo

Este repositório reúne **dois projetos** da Comendo Marketing, cada um na sua
própria pasta. Config compartilhada (Claude Code, `.env`, `.gitignore`) fica na
raiz.

| Pasta | Projeto | O que é |
|---|---|---|
| [`narracao-ia/`](narracao-ia/) | **Narração por IA** | Transforma copy do time em narração com voz humana clonada (ElevenLabs), para onboarding e captação. Comando `/comendo-narracao`. |
| [`relatorios-automaticos/`](relatorios-automaticos/) | **Automação de Relatórios** | Relatórios semanais de tráfego pago no WhatsApp do cliente (Dashgoo + Meta Ads) + auditoria. |

Cada pasta tem seu próprio `README.md` com os detalhes.

---

## Estrutura

```
/ (raiz)
├── .claude/            config do Claude Code (skills, hook de sessão, settings)
├── .env.example        template de variáveis dos DOIS projetos (copie p/ .env)
├── .env                segredos reais — NUNCA versionado (gitignore)
├── .gitignore
├── narracao-ia/        » Narração por IA (ElevenLabs)
│   ├── scripts/        narrar.py + wrapper narra
│   ├── clientes/       saídas por cliente (aprovados na raiz; testes/ ignorado)
│   ├── docs/           HANDOFF-NARRACAO, GUIA-OPERADOR, MIGRACAO-CONTA
│   └── README.md
└── relatorios-automaticos/   » Automação de Relatórios
    ├── *.py            config, comendo_db, painel, relatorios_automacao, ...
    ├── Painel.command  atalho local do painel
    ├── requirements.txt
    ├── docs/           HANDOFF, OPERACAO-COMENDO-MKT, POP_META_ADS
    └── README.md
```

## Config compartilhada

- **Variáveis de ambiente:** um único `.env` na raiz cobre os dois projetos
  (copie de `.env.example`). Em produção/nuvem, defina como secrets do
  environment em vez de arquivo.
- **Claude Code:** `.claude/` fica na raiz (exigência da ferramenta). O hook
  `.claude/hooks/session-start.sh` auto-prepara cada sessão nova na web (instala
  ffmpeg, valida a `ELEVENLABS_API_KEY`).
