# Colab Agent Fleet

**Fleet distribuída de pesquisa web: planejador em GPU + lane de execução em CPU no Google Colab.**

## Visão geral

O Colab Agent Fleet orquestra uma **arquitetura de duas lanes** para pesquisa web em paralelo:

```
┌─────────────────────────────────────────────────────────────┐
│  PLANNER (cpu6, GPU)                                        │
│  - Ollama local (gpt-oss:20b)                               │
│  - Congela o plano, valida a estrutura, distribui tarefas   │
└─────────────────────────────────────────────────────────────┘
                            │
        ┌───────────────────┼───────────────────┐
        ▼                   ▼                   ▼
   ┌─────────┐         ┌─────────┐         ┌─────────┐
   │  cpu1   │         │  cpu2   │         │  cpu3   │  ...
   │ OpenClaw│         │ OpenClaw│         │ OpenClaw│
   │+web_search        │+web_search       │+web_search
   └────┬────┘         └────┬────┘         └────┬────┘
        │                   │                   │
        └───────────────────┼───────────────────┘
                            ▼
                   ┌─────────────────┐
                   │  Results JSONL  │
                   │  + Gates + MD   │
                   └─────────────────┘
```

## Funcionalidades

- **Lane de planejamento** (GPU): LLM local via Ollama — grátis, privado, sem chaves de API
- **Lane de execução** (fleet de CPU): 5 runtimes Colab com OpenClaw + plugin web_search
- **Humano no loop**: os painéis TUI e Web mostram o plano → o usuário confirma → a fleet dispara
- **Promotion gate implementado**: taxa mínima de sucesso das tarefas
- **Reprodutível**: plano da fleet em JSON, captura de contexto, saídas redactadas
- **Skill OpenClaw**: instalável via `openclaw skills install`

## Painel Web na Oracle

O painel Flutter Web usa uma API Spring Boot same-origin e o motor Python existente. Ele preserva o fluxo de planejamento em cpu6, confirmação humana, execução em cpu1–cpu5, seis painéis de máquina, logs, browser opcional, cancelamento e resultados.

```bash
cp .env.example .env
# Preencha NVIDIA_API_KEY e FLEET_API_TOKEN somente no servidor.
docker compose -f deploy/compose.yaml --env-file .env build
docker compose -f deploy/compose.yaml --env-file .env run --rm --entrypoint colab backend login
docker compose -f deploy/compose.yaml --env-file .env up -d
```

Esses comandos preparam a infraestrutura, mas não criam uma pesquisa. Consulte [implantação e operação do painel web](docs/codex/web-deployment.md) para TLS, autenticação, limites e Nginx alternativo. O Compose não publica a porta interna do backend, e a chave NVIDIA não é enviada ao navegador.

## Início rápido

### 1. Instalar como Skill do OpenClaw

```bash
mkdir -p "$CODEX_HOME/skills"
git clone https://github.com/seu-usuario/colab-agent-fleet.git
rsync -a colab-agent-fleet/skill/colab_agent_fleet/ "$CODEX_HOME/skills/colab-agent-fleet/"
```

### 2. Configurar o ambiente

```bash
cp .env.example .env
# Edite o .env com suas chaves:
# NVIDIA_API_KEY=nvapi-xxx
# MODELO_PLANEJADOR=gpt-oss:20b
# MAQUINAS=cpu1,cpu2,cpu3,cpu4,cpu5
```

### 3. Criar as sessões Colab

```bash
# Fleet de CPU (5 sessões)
for m in cpu1 cpu2 cpu3 cpu4 cpu5; do colab new -s $m; done

# Planejador em GPU (1 sessão)
colab new -s cpu6 --gpu t4
```

### 4. Rodar a pesquisa

**Interativo (Dashboard TUI):**
```bash
python3 -m colab_agent_fleet.dashboard
# Digite o pedido → revise o plano → digite "continuar" → acompanhe a fleet rodar
```

**Headless (CI/Automação):**
```bash
# Gerar plano
python3 -m colab_agent_fleet.scripts.init_fleet_plan.py \
  --out /tmp/plan.json \
  --request "pesquise 5 plugins de navegação para OpenClaw"

# Validar plano
python3 -m colab_agent_fleet.scripts.validate_fleet_plan.py \
  --plan /tmp/plan.json \
  --request "pesquise 5 plugins de navegação para OpenClaw"

# Executar a fleet
python3 -m colab_agent_fleet.scripts.run_fleet.py \
  --plan /tmp/plan.json \
  --out /tmp/run \
  --auto-confirm

# Renderizar relatório
python3 -m colab_agent_fleet.scripts.render_fleet_summary.py \
  --results /tmp/run.jsonl \
  --gates /tmp/run_gates.json \
  --request "pesquise 5 plugins de navegação para OpenClaw" \
  --out /tmp/report.md
```

## Requisitos

- Python 3.11+
- CLI `colab` autenticada (`pip install colab-cli && colab login`)
- Chave de API da NVIDIA para o Nemotron (obtenha em https://integrate.api.nvidia.com)
- Ollama com `gpt-oss:20b` no cpu6 (ou altere `MODELO_PLANEJADOR`)

## Estrutura do projeto

```
.
├── skill/colab_agent_fleet/          # Skill OpenClaw
│   ├── SKILL.md                      # Manifesto da skill
│   ├── agents/openai.yaml            # Config do agente (Nemotron + web_search)
│   ├── scripts/                      # Scripts executáveis
│   │   ├── init_fleet_plan.py        # LN → plano da fleet validado
│   │   ├── run_fleet.py              # Executa o plano na fleet Colab
│   │   ├── validate_fleet_plan.py    # Validador standalone
│   │   ├── render_fleet_summary.py   # JSONL → relatório markdown
│   │   ├── capture_fleet_context.py  # Contexto de reprodutibilidade
│   │   └── fleet_public_safety.py    # Helpers de redação (redaction)
│   └── references/                   # Docs detalhados
│       ├── fleet-architecture.md
│       ├── plan-spec.md
│       ├── colab-operations.md
│       ├── openclaw-integration.md
│       ├── promotion-gates.md
│       ├── dashboard-tui.md
│       └── public-safety.md
├── backend/                          # API Spring Boot e supervisor do worker
├── frontend/                         # Painel Flutter Web
├── deploy/                           # Docker, Compose, Caddy e Nginx
├── fleet_worker.py                   # Adaptador JSON Lines Java ↔ Python
├── docs/codex/                       # Orientação para agentes Codex
├── tests/                            # Testes unitários + integração opt-in
├── dashboard.py                      # Orquestrador TUI (raiz)
├── stop_all.py                       # Limpa todas as sessões Colab
├── pyproject.toml                    # Config do pacote
└── .env.example                      # Modelo de variáveis de ambiente
```

## Documentação

| Doc | Descrição |
|-----|-----------|
| `skill/colab_agent_fleet/references/fleet-architecture.md` | Arquitetura, modos de falha, fluxo de dados |
| `skill/colab_agent_fleet/references/plan-spec.md` | Schema JSON do plano da fleet, regras de distribuição |
| `skill/colab_agent_fleet/references/promotion-gates.md` | Gate de sucesso, customização e limites |
| `skill/colab_agent_fleet/references/public-safety.md` | Redefinição (redaction), prevenção de vazamento |
| `docs/codex/overview.md` | Início rápido do Codex, arquivos-chave |
| `docs/codex/architecture.md` | Decisões de design, trade-offs |
| `docs/codex/workflow.md` | Workflow padrão, comandos, troubleshooting |

## Licença

Apache-2.0 — veja `LICENSE` para detalhes.

## Segurança

Veja `SECURITY.md` para reporte de vulnerabilidades e práticas de segurança.
