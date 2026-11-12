---
name: colab-agent-fleet
description: Colab Agent Fleet é uma skill pública do ClawHub para pesquisa web distribuída em runtimes CPU do Colab. Use quando o usuário falar "colab fleet", "pesquisa distribuída", "busca web paralela" ou quiser agentes multi-máquina coordenados com lane de planejamento (GPU) e lane de execução (fleet de CPU).
version: 0.1.0
homepage: https://github.com/seu-usuario/colab-agent-fleet
user-invocable: true
metadata: {"openclaw":{"homepage":"https://github.com/seu-usuario/colab-agent-fleet","skillKey":"colab-agent-fleet","requires":{"anyBins":["python3","colab"]}}}
---

# Colab Agent Fleet

Intenção de busca: `colab fleet`, `pesquisa distribuída`, `busca web paralela`, `orquestração de agentes multi-máquina`

## Objetivo

Transformar uma pergunta de pesquisa em uma campanha multi-máquina coordenada:

- **Lane de planejamento (GPU)**: LLM local (Ollama/gpt-oss) congela o plano, valida a estrutura e distribui as tarefas
- **Lane de execução (fleet de CPU)**: 5 runtimes Colab rodam agentes OpenClaw com a ferramenta web_search em paralelo
- **Captura de evidências**: cada tarefa retorna resultados estruturados (URLs, títulos, snippets) com dedup e gates de qualidade
- **Humano no loop**: o dashboard mostra o plano → o usuário confirma → a fleet dispara → resultados agregados

Esta skill é a **camada de orquestração**. Combine com suas próprias skills de busca/análise para trabalho específico de domínio.

## Use esta skill quando

- o usuário quiser pesquisa web paralela em múltiplos IPs (o Colab dá 5+ IPs limpos)
- a tarefa precisar de um planejador que gere distribuições de tarefas estruturadas e validadas
- o workflow incluir agentes OpenClaw com a ferramenta web_search no Colab
- você precisar de um dashboard TUI para monitorar o status da fleet e aprovar os disparos
- o usuário quiser campanhas de pesquisa reproduzíveis com promotion gates

Se o objetivo principal for pesquisa profunda em máquina única, use um loop de agente mais simples.

## Início rápido

1. **Instale a skill** (do ClawHub ou local):
   ```bash
   mkdir -p "$CODEX_HOME/skills"
   rsync -a skill/colab-agent-fleet/ "$CODEX_HOME/skills/colab-agent-fleet/"
   ```

2. **Configure o ambiente** (`.env` na raiz do projeto):
   ```bash
   NVIDIA_API_KEY=nvapi-xxx          # para o Nemotron na lane de execução
   MAQUINAS=cpu1,cpu2,cpu3,cpu4,cpu5 # sessões Colab alvo
   MODELO_PLANEJADOR=gpt-oss:20b     # modelo Ollama no cpu6 (GPU)
   ```

3. **Abra o dashboard** (humano no loop):
   ```bash
   python3 -m colab_agent_fleet.dashboard
   # ou rode o orquestrador diretamente:
   python3 -m colab_agent_fleet.orchestrator "pesquise 5 plugins de navegação para OpenClaw"
   ```

4. **Ou use os scripts diretamente** para CI/automação:
   ```bash
   # Gerar um plano validado
   python3 {baseDir}/scripts/init_fleet_plan.py \
     --out /tmp/fleet-plan.json \
     --request "pesquise 5 plugins de navegação para OpenClaw"

   # Executar o plano (exige CLI do Colab autenticada)
   python3 {baseDir}/scripts/run_fleet.py \
     --plan /tmp/fleet-plan.json \
     --auto-confirm
   ```

## Arquitetura

```
┌─────────────────────────────────────────────────────────────┐
│  ORQUESTRADOR (local)                                       │
│  - Recebe o pedido em linguagem natural                     │
│  - Chama o Planejador (cpu6/GPU) → plano da fleet validado  │
│  - Mostra o plano na TUI → usuário confirma                 │
│  - Dispara a fleet em paralelo via colab ssh                 │
│  - Agrega os resultados e aplica os promotion gates         │
└─────────────────────────────────────────────────────────────┘
                            │
        ┌───────────────────┼───────────────────┐
        ▼                   ▼                   ▼
   ┌─────────┐         ┌─────────┐         ┌─────────┐
   │ cpu1    │         │ cpu2    │         │ cpu3    │  ...
   │ OpenClaw│         │ OpenClaw│         │ OpenClaw│
   │+web_search        │+web_search       │+web_search
   └────┬────┘         └────┬────┘         └────┬────┘
        │                   │                   │
        └───────────────────┼───────────────────┘
                            ▼
                   ┌─────────────────┐
                   │  Results JSONL  │
                   │  + Promotion    │
                   └─────────────────┘
```

## Regras de operação

### Regras de planejamento

- Um pedido → um **plano da fleet** (JSON validado)
- O planejador (lane GPU) gera SOMENTE tarefas no formato: `[cpuN] [tarefaK] prompt`
- Cada máquina tem no máx. 2 tarefas (tarefa1, tarefa2); máquinas usadas em ordem (cpu1, cpu2...)
- Pedidos simples (2–4 tarefas): 2 máquinas, dividindo as tarefas. 5+ tarefas: mínimo de máquinas, 2 por máquina
- Sem nomes inventados, sem ângulos extras (segurança, navegação etc.) a menos que o usuário peça
- O plano deve passar em `validar_plano()` antes de qualquer máquina iniciar

### Regras de execução

- Cada máquina de CPU roda setup idêntico: OpenClaw + NVIDIA NIMs + plugin web_search
- Agentes rodam via `openclaw agent exec` com `--local-model-lean` pela velocidade
- Gateway inicia com `--auth none --bind loopback` para acesso local às ferramentas
- Resultados capturados como JSONL; cada tarefa retorna evidência estruturada
- Problemas de lock no SQLite são mitigados espaçando os disparos (pipeline: escalonamento de 60s)

### Regras de evidência e promoção

- Cada tarefa deve retornar: query, results[title, url, snippet], timestamp, machine
- Dedup na fleet: similaridade de URL + título > 0.9 = duplicata
- Promotion gates (configuráveis):
  - `min_unique_sources`: mínimo de domínios distintos (default 3)
  - `max_dup_ratio`: fração máxima de duplicatas (default 0.15)
  - `min_chars_per_result`: conteúdo mínimo por resultado (default 200)
- Resultados só são promovidos se os gates passarem; senão, são marcados para revisão

### Regras de distribuição pública

- Use `{baseDir}` ao apontar para scripts/references empacotados
- Mantenha segredos, tokens, URLs privadas e IDs de sessão Colab fora do bundle da skill
- Especializações privadas (prompts customizados, alvos internos) → skill de override local
- Todos os scripts devem passar em `python3 -m py_compile` e `pytest -q`

## Referências

Leia somente a referência que corresponde à tarefa:

- `references/fleet-architecture.md`
  - Arquitetura completa, separação de lanes, modos de falha
- `references/plan-spec.md`
  - Schema JSON do plano da fleet, regras de validação, algoritmo de distribuição
- `references/colab-operations.md`
  - Padrões da CLI Colab, gerenciamento de sessões, formas GPU/CPU, quirks de SSH
- `references/openclaw-integration.md`
  - Setup do plugin OpenClaw, config do gateway, modos de agent exec, registro de ferramentas
- `references/promotion-gates.md`
  - Gates de qualidade de evidência, lógica de dedup, formato do bundle de promoção
- `references/dashboard-tui.md`
  - Padrões da TUI Textual, streaming de logs, fluxos de confirmação, logs maximizáveis
- `references/public-safety.md`
  - Checklist de publicação para OpenClaw/ClawHub, prevenção de vazamento

## Scripts empacotados

- `scripts/init_fleet_plan.py`
  - Gera um JSON de plano da fleet validado a partir de um pedido em linguagem natural
  - Usa Ollama local (gpt-oss) ou endpoint compatível com OpenAI para o planejamento
  - Gera o plano com tarefas distribuídas conforme as regras; sai com código não-zero se inválido
- `scripts/run_fleet.py`
  - Executa um plano da fleet validado nas máquinas Colab
  - Cuida do escalonamento do pipeline, health-check do gateway e agregação de resultados
  - Aplica os promotion gates; grava resultados JSONL + resumo em markdown
- `scripts/validate_fleet_plan.py`
  - Validador standalone do JSON do plano da fleet (usado em CI)
  - Checa estrutura, regras de distribuição, qualidade dos prompts, ausência de nomes inventados
- `scripts/render_fleet_summary.py`
  - Renderiza resumo em markdown a partir do JSONL de resultados com redação pública
  - Mostra estatísticas por máquina, pass/fail dos gates, principais fontes
- `scripts/capture_fleet_context.py`
  - Captura estado do git, env (redactado), status das sessões Colab, versão do OpenClaw
  - Rode antes do disparo para registro de reprodutibilidade
- `scripts/fleet_public_safety.py`
  - Helpers locais puros para redação de caminhos, URLs, env e comandos
  - Sem I/O de rede; usado por outros scripts para saída pública segura

## Agentes

- `agents/openai.yaml` — config do agente OpenClaw para a lane de execução (Nemotron + web_search)
