# Colab Agent Fleet — Visão geral para o Codex

## O que este repo faz

O **Colab Agent Fleet** orquestra uma **lane de planejamento (GPU)** + **lane de execução (fleet de CPU)** para pesquisa web distribuída:

1. **Planejador** (cpu6, GPU): Ollama local (gpt-oss:20b) recebe linguagem natural → gera plano da fleet validado
2. **Fleet** (cpu1–5, CPU): cada uma roda OpenClaw com plugin web_search → pesquisas web em paralelo
3. **Gates** → critérios de promoção (taxa de sucesso, fontes únicas, dedup, profundidade do conteúdo)
4. **Dashboard** → TUI com humano no loop para aprovar o plano e monitorar

## Início rápido para o Codex

```bash
# 1. Instalar a skill localmente
mkdir -p "$CODEX_HOME/skills"
rsync -a skill/colab-agent-fleet/ "$CODEX_HOME/skills/colab-agent-fleet/"

# 2. Configurar o ambiente
cp .env.example .env
# Edite o .env com sua NVIDIA_API_KEY

# 3. Rodar o dashboard (TUI)
python3 -m colab_agent_fleet.dashboard

# Ou rodar headless
python3 -m colab_agent_fleet.scripts.init_fleet_plan.py \
  --out /tmp/plan.json \
  --request "pesquise 5 plugins de navegação para OpenClaw"
python3 -m colab_agent_fleet.scripts.run_fleet.py \
  --plan /tmp/plan.json \
  --out /tmp/run \
  --auto-confirm
```

## Verificação padrão (rodar antes de commitar)

```bash
# 1. Checagem de sintaxe de todos os scripts
python3 -m py_compile skill/colab-agent-fleet/scripts/*.py

# 2. Testes unitários
python3 -m pytest tests/ -q

# 3. Scan de segurança pública
python3 skill/colab-agent-fleet/scripts/fleet_public_safety.py --scan .

# 4. Validar plano de exemplo
python3 skill/colab-agent-fleet/scripts/validate_fleet_plan.py \
  --plan tests/fixtures/valid_plan.json \
  --request "pesquise 5 carros mais rápidos e 5 motos mais rápidas"
```

## Arquivos-chave para agentes Codex

| Arquivo | Finalidade |
|---------|------------|
| `skill/colab-agent-fleet/SKILL.md` | Manifesto da skill, uso, regras, lista de scripts |
| `skill/colab-agent-fleet/scripts/init_fleet_plan.py` | Planejador: LN → JSON de plano validado |
| `skill/colab-agent-fleet/scripts/run_fleet.py` | Executor: roda o plano na fleet Colab |
| `skill/colab-agent-fleet/scripts/validate_fleet_plan.py` | Validador: verificador de plano standalone |
| `skill/colab-agent-fleet/scripts/render_fleet_summary.py` | Relatórios: JSONL + gates → markdown |
| `skill/colab-agent-fleet/references/plan-spec.md` | Schema JSON do plano e regras de distribuição |
| `skill/colab-agent-fleet/references/fleet-architecture.md` | Arquitetura, modos de falha, fluxo de dados |
| `skill/colab-agent-fleet/references/openclaw-integration.md` | Plugin OpenClaw, gateway, config do agente |
| `skill/colab-agent-fleet/references/promotion-gates.md` | Lógica dos gates, customização, integração com CI |

## Tarefas comuns para o Codex

### Adicionar novo gate de promoção
1. Edite `run_fleet.py` → `PROMOTION_GATES_DEFAULTS` + `aplicar_gates()`
2. Atualize `promotion-gates.md` com a lógica
3. Adicione teste em `tests/test_gates.py`

### Mudar o modelo do planejador
1. Edite `init_fleet_plan.py` → default de `MODELO_PLANEJADOR`
2. Atualize o Quick Start do `SKILL.md`
3. Teste com `gpt-oss:20b` e `llama3.1:8b`

### Adicionar novo doc de referência
1. Crie `references/novo-topico.md`
2. Adicione na seção References do `SKILL.md`
3. Linke a partir dos scripts relevantes

### Modificar o Dashboard
1. Edite `dashboard.py` (na raiz do repo, não na skill)
2. Atualize `dashboard-tui.md`
3. Teste com `python3 -m textual.testing` em modo headless

## Pegadinhas (gotchas) para o Codex

| Problema | Prevenção |
|----------|-----------|
| Lock do SQLite no lançamento paralelo | Pipeline escalonado (60s) no `run_fleet.py` |
| Gateway não está pronto | Loop de health-check (30×2s) no script de deploy |
| Plugin não carregou | Instalação explícita + `--accept-capabilities` |
| colab ssh 429 | Serialize o SSH; não paralelize a mesma máquina |
| Segredos nos logs | Use `fleet_public_safety.py` em todas as saídas |
| Validação do plano falha | Veja `plan-spec.md` para as regras de distribuição |
