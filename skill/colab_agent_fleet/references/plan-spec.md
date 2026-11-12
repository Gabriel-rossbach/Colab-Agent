# Especificação do plano da fleet

## Schema JSON

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": ["request", "tasks"],
  "properties": {
    "request": {
      "type": "string",
      "description": "Pedido original em linguagem natural"
    },
    "tasks": {
      "type": "array",
      "minItems": 1,
      "maxItems": 10,
      "items": {
        "type": "object",
        "required": ["cpu", "task", "prompt"],
        "properties": {
          "cpu": {"type": "integer", "minimum": 1, "maximum": 5},
          "task": {"type": "integer", "minimum": 1, "maximum": 2},
          "prompt": {"type": "string", "minLength": 40}
        }
      }
    },
    "metadata": {
      "type": "object",
      "properties": {
        "planner_model": {"type": "string"},
        "generated_at": {"type": "string", "format": "date-time"},
        "validation_passed": {"type": "boolean"}
      }
    }
  }
}
```

## Algoritmo de distribuição

Dado `N` tarefas (1 ≤ N ≤ 10):

| N | Máquinas usadas | Distribuição (tarefas por máquina) |
|---|-----------------|------------------------------------|
| 1 | 1 | cpu1: [1] |
| 2 | 2 | cpu1: [1], cpu2: [1] |
| 3 | 2 | cpu1: [1,2], cpu2: [1] |
| 4 | 2 | cpu1: [1,2], cpu2: [1,2] |
| 5 | 3 | cpu1: [1,2], cpu2: [1,2], cpu3: [1] |
| 6 | 3 | cpu1: [1,2], cpu2: [1,2], cpu3: [1,2] |
| 7 | 4 | cpu1: [1,2], cpu2: [1,2], cpu3: [1,2], cpu4: [1] |
| 8 | 4 | cpu1: [1,2], cpu2: [1,2], cpu3: [1,2], cpu4: [1,2] |
| 9 | 5 | cpu1: [1,2], cpu2: [1,2], cpu3: [1,2], cpu4: [1,2], cpu5: [1] |
| 10 | 5 | cpu1: [1,2], cpu2: [1,2], cpu3: [1,2], cpu4: [1,2], cpu5: [1,2] |

**Regra**: mínimo de máquinas, máx. 2 tarefas por máquina, máquinas usadas em ordem (cpu1, cpu2...).

## Regras de validação

1. **Estrutura**: todas as tarefas têm cpu (1–5), task (1–2), prompt (≥40 caracteres)
2. **Distribuição**: os rótulos batem exatamente com `etiquetas_esperadas(N)` para o N dado
3. **Unicidade**: sem pares (cpu, task) duplicados
4. **Qualidade do prompt**:
   - Contém "web_search"
   - Sem nomes inventados (strings entre aspas que não estejam no pedido original)
   - Sem ângulos extras (segurança, navegação, café etc.) a menos que pedido
5. **Dedup**: sem prompts exatos ou quase duplicados (ratio ≥ 0.985)

## Exemplos de planos válidos

### 2 tarefas (simples)
```json
{
  "request": "pesquise 5 carros mais rápidos e 5 motos mais rápidas",
  "tasks": [
    {"cpu": 1, "task": 1, "prompt": "Use web_search para pesquisar os 5 carros mais rápidos. Traga em português."},
    {"cpu": 2, "task": 1, "prompt": "Use web_search para pesquisar as 5 motos mais rápidas. Traga em português."}
  ]
}
```

### 5 tarefas (complexo)
```json
{
  "request": "quero 5 plugins e 5 skills de navegação para o OpenClaw",
  "tasks": [
    {"cpu": 1, "task": 1, "prompt": "Use web_search para pesquisar um plugin para controlar o navegador no OpenClaw. Traga o que faz e como instalar, em português."},
    {"cpu": 1, "task": 2, "prompt": "Use web_search para pesquisar um plugin para ler e resumir páginas no OpenClaw. Traga o que faz e como instalar, em português."},
    {"cpu": 2, "task": 1, "prompt": "Use web_search para pesquisar um plugin para buscar e comparar resultados na web no OpenClaw. Traga o que faz e como instalar, em português."},
    {"cpu": 2, "task": 2, "prompt": "Use web_search para pesquisar um plugin para gerenciar abas e sessões no OpenClaw. Traga o que faz e como instalar, em português."},
    {"cpu": 3, "task": 1, "prompt": "Use web_search para pesquisar um plugin para extrair texto estruturado de páginas no OpenClaw. Traga o que faz e como instalar, em português."}
  ]
}
```

## Padrões inválidos (rejeitados automaticamente)

| Padrão | Motivo da rejeição |
|--------|--------------------|
| `cpu1 tarefa3` | task > 2 (a numeração recomeça por máquina) |
| `cpu6 tarefa1` | cpu > 5 |
| 3 tarefas na cpu1 | máx. 2 por máquina |
| cpu1, cpu3 (pular cpu2) | máquinas em ordem, sem pular |
| `"WebNav"` no prompt mas não no pedido | nome inventado |
| "segurança" no prompt mas não no pedido | ângulo extra não pedido |
| Duas tarefas com o mesmo prompt | duplicata exata |
| Duas tarefas 98% similares | quase duplicata |
