# Referência de arquitetura da fleet

## Visão geral

O Colab Agent Fleet implementa uma **arquitetura de duas lanes** para pesquisa web distribuída:

```
┌─────────────────────────────────────────────────────────────────────┐
│                        ORQUESTRADOR (local)                         │
│  - Recebe o pedido em linguagem natural                             │
│  - Chama o Planejador (lane GPU) → plano da fleet validado          │
│  - Confirmação humana via TUI                                       │
│  - Dispara a fleet em paralelo via colab ssh                        │
│  - Agrega os resultados e aplica os promotion gates                 │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
             ┌────────────┐  ┌────────────┐  ┌────────────┐
             │   cpu1     │  │   cpu2     │  │   cpu3     │  ...
             │ OpenClaw   │  │ OpenClaw   │  │ OpenClaw   │
             │ + web_search│  │ + web_search│  │ + web_search│
             └─────┬──────┘  └─────┬──────┘  └─────┬──────┘
                   │               │               │
                   └───────────────┼───────────────┘
                                   ▼
                          ┌──────────────────┐
                          │  Results JSONL   │
                          │  + Gates + MD    │
                          └──────────────────┘
```

## Separação de lanes

| Lane | Máquina | Modelo | Finalidade |
|------|---------|--------|------------|
| **Planejamento** | cpu6 (GPU) | gpt-oss:20b (Ollama) | Congelar o plano, validar a estrutura, distribuir tarefas |
| **Execução** | cpu1–5 (CPU) | Nemotron 3.5 (NVIDIA NIMs) | Rodar web_search, retornar evidências estruturadas |

**Por que separar?**
- A lane de GPU roda LLM local (grátis, privado, sem chaves de API)
- A fleet de CPU usa NVIDIA NIMs (rápido, saída estruturada, ferramenta web_search)
- Otimização de custo: GPU só para o planejamento (segundos), CPUs para a execução paralela

## Modos de falha e mitigações

| Falha | Detecção | Mitigação |
|-------|----------|-----------|
| Lock do SQLite (`offline maintenance`) | Logs mostram "state undergoing offline maintenance" | Escalonamento do pipeline (60s entre os starts das máquinas) |
| Gateway não está pronto | Health-check curl falha | 30 tentativas × 2s de polling antes de disparar o agente |
| colab ssh 429 (sessão ocupada) | HTTP 429 na conexão SSH | Sequencial por máquina; retry com backoff |
| Plugin não carregou | `web_search is disabled` | Instalação explícita do plugin + restart do gateway por máquina |
| Rate limit (DuckDuckGo) | Resultados vazios / erros | 5 máquinas × IPs diferentes = distribuição natural |

## Fluxo de dados

1. **Pedido** → string em linguagem natural
2. **Plano** → JSON validado: `{"request": "...", "tasks": [{"cpu": 1, "task": 1, "prompt": "..."}]}`
3. **Disparo** → script bash por máquina via `colab ssh -s cpuN` (pipe via stdin)
4. **Execução** → cada máquina: instala OpenClaw → instala plugin → inicia gateway → roda o agente
5. **Coleta** → linhas JSONL por tarefa: `{maquina, task, prompt, sucesso, saida_bruta, timestamp}`
6. **Gate** → aplica as regras de promoção (taxa de sucesso, dedup, fontes mínimas)
7. **Relatório** → resumo em markdown + JSON dos gates + JSONL bruto

## Gates de promoção

Gates padrão (configuráveis via JSON em `--gates`):

```json
{
  "min_unique_sources": 3,
  "max_dup_ratio": 0.15,
  "min_chars_per_result": 200,
  "min_success_ratio": 0.7
}
```

A lógica dos gates roda pós-execução sobre os resultados agregados. Só contam as tarefas com `sucesso=true`.

## Limites de escala

| Recurso | Limite | Motivo |
|---------|--------|--------|
| Máx. de máquinas | 5 (cpu1–cpu5) | Limite típico do nível gratuito do Colab |
| Máx. de tarefas/máquina | 2 (tarefa1, tarefa2) | Contenção no SQLite, janela de contexto |
| Máx. de tarefas no total | 10 | 5 máquinas × 2 tarefas |
| Máx. de caracteres do plano/tarefa | 40 min | Garante prompts acionáveis |
| Tentativas do planejador | 2 | Equilibra qualidade e tempo |

## Fronteiras de segurança

- **Sem chaves de API no bundle da skill** → injetadas via env em tempo de execução
- **Sem URLs/caminhos privados** → redactados por `fleet_public_safety.py`
- **IDs de sessão Colab** → redactados nos logs
- **Gateway auth=none** → somente bind em loopback; sem exposição externa
- **Confirmação humana obrigatória** → sem disparo automático sem aprovação
