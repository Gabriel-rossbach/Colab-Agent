# Fleet Plan Specification

## JSON Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": ["request", "tasks"],
  "properties": {
    "request": {
      "type": "string",
      "description": "Original natural language request"
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

## Distribution Algorithm

Given `N` tasks (1 ≤ N ≤ 10):

| N | Machines Used | Distribution (tasks per machine) |
|---|---------------|----------------------------------|
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

**Rule**: Minimum machines, max 2 tasks per machine, machines used in order (cpu1, cpu2...).

## Validation Rules

1. **Structure**: All tasks have cpu (1-5), task (1-2), prompt (≥40 chars)
2. **Distribution**: Labels match exactly `etiquetas_esperadas(N)` for given N
3. **Uniqueness**: No duplicate (cpu, task) pairs
4. **Prompt quality**:
   - Contains "web_search"
   - No invented names (quoted strings not in original request)
   - No extra angles (security, navigation, coffee, etc.) unless requested
5. **Dedup**: No exact or near-duplicate prompts (ratio ≥ 0.985)

## Example Valid Plans

### 2 tasks (simple)
```json
{
  "request": "pesquise 5 carros mais rápidos e 5 motos mais rápidas",
  "tasks": [
    {"cpu": 1, "task": 1, "prompt": "Use web_search para pesquisar os 5 carros mais rápidos. Traga em português."},
    {"cpu": 2, "task": 1, "prompt": "Use web_search para pesquisar as 5 motos mais rápidas. Traga em português."}
  ]
}
```

### 5 tasks (complex)
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

## Invalid Patterns (Auto-Rejected)

| Pattern | Rejection Reason |
|---------|------------------|
| `cpu1 tarefa3` | task > 2 (numeração recomeça por máquina) |
| `cpu6 tarefa1` | cpu > 5 |
| 3 tasks on cpu1 | max 2 por máquina |
| cpu1, cpu3 (skip cpu2) | máquinas em ordem, sem pular |
| `"WebNav"` in prompt but not in request | nome inventado |
| "segurança" in prompt but not in request | ângulo extra não pedido |
| Two tasks with same prompt | duplicata exata |
| Two tasks 98% similar | quase duplicata |