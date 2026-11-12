# Guia de workflow

## Fluxo padrão de pesquisa

```
1. PEDIDO
   Usuário: "pesquise 5 plugins de navegação para OpenClaw"

2. PLANO (cpu6/GPU)
   → init_fleet_plan.py → fleet-plan.json (validado)
   → Mostra: 5 tarefas distribuídas em cpu1-cpu3

3. CONFIRMAÇÃO (Humano)
   → O dashboard mostra o plano
   → Usuário digita "continuar"

4. EXECUÇÃO (cpu1-5/CPU, paralelo com escalonamento)
   → Cada máquina: instala → gateway → agent exec → resultados
   → Logs são exibidos nos painéis da TUI

5. GATES (pós-processamento)
   → run_fleet.py aplica os promotion gates
   → Aprovado/reprovado com métricas

6. RELATÓRIO
   → render_fleet_summary.py → markdown + JSONL
   → Pronto para uso / compartilhamento
```

## Referência de comandos

### Gerar plano
```bash
# Interativo (com dashboard)
python3 -m colab_agent_fleet.dashboard

# Headless (CI/automação)
python3 -m colab_agent_fleet.scripts.init_fleet_plan.py \
  --out /tmp/plan.json \
  --request "sua pesquisa aqui" \
  --model gpt-oss:20b
```

### Validar plano
```bash
python3 -m colab_agent_fleet.scripts.validate_fleet_plan.py \
  --plan /tmp/plan.json \
  --request "sua pesquisa aqui"
```

### Executar a fleet
```bash
# Com confirmação
python3 -m colab_agent_fleet.scripts.run_fleet.py \
  --plan /tmp/plan.json \
  --out /tmp/run

# Auto-confirmação (CI)
python3 -m colab_agent_fleet.scripts.run_fleet.py \
  --plan /tmp/plan.json \
  --out /tmp/run \
  --auto-confirm \
  --gates '{"min_success_ratio": 0.8}'
```

### Renderizar resumo
```bash
python3 -m colab_agent_fleet.scripts.render_fleet_summary.py \
  --results /tmp/run.jsonl \
  --gates /tmp/run_gates.json \
  --request "pedido original" \
  --out /tmp/report.md
```

### Capturar contexto (antes da run)
```bash
python3 -m colab_agent_fleet.scripts.capture_fleet_context.py \
  --out /tmp/context.json \
  --repo-root .
```

## Variáveis de ambiente

| Var | Obrigatória | Default | Descrição |
|-----|-------------|---------|-----------|
| `NVIDIA_API_KEY` | Sim | - | Chave de API dos NVIDIA NIMs |
| `MODELO_PLANEJADOR` | Não | `gpt-oss:20b` | Modelo Ollama do planejador |
| `MAQUINAS` | Não | `cpu1,cpu2,cpu3,cpu4,cpu5` | Sessões Colab alvo |
| `FLAGS_GPU` | Não | `--gpu t4` | Flags de GPU para o cpu6 |

## Gerenciamento de sessões Colab

```bash
# Ver sesiones ativas
colab sessions

# Criar sessões que faltam
for m in cpu1 cpu2 cpu3 cpu4 cpu5; do colab new -s $m; done

# Criar sessão de GPU para o planejador
colab new -s cpu6 --gpu t4

# Parar todas
python3 stop_all.py
```

## Solução de problemas

| Sintoma | Correção |
|---------|----------|
| `web_search is disabled` | Verifique se o plugin está instalado e o gateway rodando |
| `SQLite offline maintenance` | Aguarde 30s; tente de novo; garanta o escalonamento do pipeline |
| `colab ssh 429` | Aguarde o SSH anterior fechar; serialize |
| `Gateway health-check timeout` | Aumente a espera; verifique `/tmp/gateway.log` |
| `Plugin not found` | Reinstale: `openclaw plugins install /root/openclaw-plugins/web-search --force --accept-capabilities` |
| `Rate limited` | O scraping HTML do DuckDuckGo tem limites; adicione delay ou reduza `max_results` |

## Exemplo de CI/CD

```yaml
# .github/workflows/fleet-research.yml
name: Pesquisa com a Fleet
on:
  workflow_dispatch:
    inputs:
      request:
        description: 'Pedido de pesquisa'
        required: true
      auto_confirm:
        type: boolean
        default: true

jobs:
  research:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Setup Python
        uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - name: Instalar dependências
        run: pip install -e . pytest textual colab-cli
      - name: Gerar plano
        env:
          MODELO_PLANEJADOR: gpt-oss:20b
        run: |
          python3 -m colab_agent_fleet.scripts.init_fleet_plan.py \
            --out /tmp/plan.json \
            --request "${{ github.event.inputs.request }}"
      - name: Validar plano
        run: |
          python3 -m colab_agent_fleet.scripts.validate_fleet_plan.py \
            --plan /tmp/plan.json \
            --request "${{ github.event.inputs.request }}"
      - name: Rodar a fleet
        env:
          NVIDIA_API_KEY: ${{ secrets.NVIDIA_API_KEY }}
        run: |
          python3 -m colab_agent_fleet.scripts.run_fleet.py \
            --plan /tmp/plan.json \
            --out /tmp/run \
            --auto-confirm
      - name: Subir relatório
        uses: actions/upload-artifact@v4
        with:
          name: fleet-report
          path: /tmp/run_summary.md
```
