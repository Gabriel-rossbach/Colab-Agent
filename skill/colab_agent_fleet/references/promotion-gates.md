# Referência dos promotion gates

## Finalidade

Os promotion gates garantem a **qualidade das evidências** antes que os resultados sejam considerados "promovidos" (prontos para uso/relatório). Eles rodam pós-execução sobre os resultados agregados da fleet.

## Gates padrão

```python
PROMOTION_GATES_DEFAULTS = {
    "min_unique_sources": 3,      # Mínimo de domínios distintos nos resultados
    "max_dup_ratio": 0.15,        # Fração máxima de resultados duplicados
    "min_chars_per_result": 200,  # Conteúdo mínimo por resultado
    "min_success_ratio": 0.7,     # Mínimo de 70% das tarefas devem ter sucesso
}
```

## Lógica dos gates

### 1. Gate de taxa de sucesso
```python
successful = sum(1 for r in results if r.get("sucesso"))
ratio = successful / len(results)
pass = ratio >= min_success_ratio
```

### 2. Gate de fontes únicas
```python
# Extrai domínios das URLs dos resultados
domains = set()
for r in successful_results:
    for result in parse_results(r["saida_bruta"]):
        domains.add(urlparse(result["url"]).netloc)
pass = len(domains) >= min_unique_sources
```

### 3. Gate de taxa de duplicatas
```python
# Compara títulos/URLs dos resultados por similaridade
all_results = flatten([parse_results(r["saida_bruta"]) for r in successful_results])
unique = dedup(all_results, threshold=0.9)  # 90% de similaridade = duplicata
dup_ratio = 1 - (len(unique) / len(all_results))
pass = dup_ratio <= max_dup_ratio
```

### 4. Gate de profundidade do conteúdo
```python
# Cada resultado precisa de conteúdo substantial
pass = all(len(r.get("snippet", "")) >= min_chars_per_result for r in unique_results)
```

## Saída dos gates

```json
{
  "total_tasks": 8,
  "successful": 7,
  "gate_pass": true,
  "gates_config": {...},
  "details": {
    "min_success_ratio": 0.7,
    "actual_ratio": 0.875,
    "unique_sources": 5,
    "min_unique_sources": 3,
    "dup_ratio": 0.08,
    "max_dup_ratio": 0.15,
    "avg_chars": 450,
    "min_chars_per_result": 200
  }
}
```

## Gates customizados (via JSON em `--gates`)

```bash
python3 run_fleet.py --plan plan.json --out /tmp/run \
  --gates '{"min_unique_sources": 5, "min_success_ratio": 0.8}'
```

## Integração com CI

```yaml
# .github/workflows/validate-fleet.yml
- name: Rodar a fleet com gates
  run: |
    python3 -m colab_agent_fleet.scripts.run_fleet \
      --plan fleet-plan.json \
      --out /tmp/fleet-run \
      --auto-confirm \
      --gates '{"min_success_ratio": 0.8}'
```

## Tratamento de falhas

| Gate reprovado | Ação |
|----------------|------|
| Taxa de sucesso < 70% | Repetir as tarefas que falharam (re-rodar com o mesmo plano) |
| Fontes únicas < 3 | Expandir as queries de busca; adicionar mais tarefas |
| Taxa de duplicatas > 15% | Aumentar a diversidade das queries no prompt do planejador |
| Profundidade < 200 caracteres | Ajustar o prompt para pedir mais detalhes |

## Bundle de promoção

Quando todos os gates passam, gere o bundle de promoção:

```bash
python3 -m colab_agent_fleet.scripts.render_fleet_summary \
  --results /tmp/run.jsonl \
  --gates /tmp/run_gates.json \
  --request "pedido original" \
  --out /tmp/promotion_bundle.md
```

O bundle inclui:
- Status pass/fail dos gates com as métricas
- Resultados por máquina
- Principais fontes por domínio
- Redactado para compartilhamento público
