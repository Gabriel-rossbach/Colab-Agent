# Referência dos promotion gates

## Gate implementado nesta versão

O único gate calculado atualmente é a **taxa de sucesso das tarefas**:

```python
PROMOTION_GATES_DEFAULTS = {
    "min_success_ratio": 0.7,
}
```

A validação usa `ceil(total * min_success_ratio)`, garantindo que uma taxa exatamente no limite seja aceita e que uma lista vazia reprove o gate. O worker web também expõe `gatePass` no evento `run.result`.

## Saída dos gates

```json
{
  "total_tasks": 8,
  "successful": 7,
  "gate_pass": true,
  "gates_config": {"min_success_ratio": 0.7},
  "details": {
    "min_success_ratio": 0.7,
    "actual_ratio": 0.875,
    "min_required": 6
  }
}
```

## Personalização

Somente `min_success_ratio` é reconhecido pela implementação atual:

```bash
python3 skill/colab_agent_fleet/scripts/run_fleet.py \
  --plan plan.json \
  --out /tmp/run \
  --auto-confirm \
  --gates '{"min_success_ratio": 0.8}'
```

## O que não está implementado

`min_unique_sources`, `max_dup_ratio` e `min_chars_per_result` não são calculados por `aplicar_gates()` nesta versão e não devem ser descritos como gates ativos em documentação pública. Eles podem ser adicionados no futuro com testes e métricas reais.

## Tratamento de falha

Se o gate reprovar, revise `results.json` e `summary.md` no diretório privado da run. Não há rerun automático: tarefas de browser podem causar efeitos externos, então uma nova tentativa exige decisão humana explícita.
