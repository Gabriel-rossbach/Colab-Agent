# Promotion Gates Reference

## Purpose

Promotion gates ensure **evidence quality** before results are considered "promoted" (ready for use/report). They run post-execution on aggregated fleet results.

## Default Gates

```python
PROMOTION_GATES_DEFAULTS = {
    "min_unique_sources": 3,      # Minimum distinct domains in results
    "max_dup_ratio": 0.15,        # Max fraction of duplicate results
    "min_chars_per_result": 200,  # Minimum content per result
    "min_success_ratio": 0.7,     # Min 70% tasks must succeed
}
```

## Gate Logic

### 1. Success Ratio Gate
```python
successful = sum(1 for r in results if r.get("sucesso"))
ratio = successful / len(results)
pass = ratio >= min_success_ratio
```

### 2. Unique Sources Gate
```python
# Extract domains from result URLs
domains = set()
for r in successful_results:
    for result in parse_results(r["saida_bruta"]):
        domains.add(urlparse(result["url"]).netloc)
pass = len(domains) >= min_unique_sources
```

### 3. Duplicate Ratio Gate
```python
# Compare result titles/URLs for similarity
all_results = flatten([parse_results(r["saida_bruta"]) for r in successful_results])
unique = dedup(all_results, threshold=0.9)  # 90% similarity = duplicate
dup_ratio = 1 - (len(unique) / len(all_results))
pass = dup_ratio <= max_dup_ratio
```

### 4. Content Depth Gate
```python
# Each result must have substantial content
pass = all(len(r.get("snippet", "")) >= min_chars_per_result for r in unique_results)
```

## Gate Output

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

## Custom Gates (via `--gates` JSON)

```bash
python3 run_fleet.py --plan plan.json --out /tmp/run \
  --gates '{"min_unique_sources": 5, "min_success_ratio": 0.8}'
```

## CI Integration

```yaml
# .github/workflows/validate-fleet.yml
- name: Run fleet with gates
  run: |
    python3 -m colab_agent_fleet.scripts.run_fleet \
      --plan fleet-plan.json \
      --out /tmp/fleet-run \
      --auto-confirm \
      --gates '{"min_success_ratio": 0.8}'
```

## Failure Handling

| Gate Failed | Action |
|-------------|--------|
| Success ratio < 70% | Retry failed tasks (re-run with same plan) |
| Unique sources < 3 | Expand search queries; add more tasks |
| Dup ratio > 15% | Increase query diversity in planner prompt |
| Content depth < 200 chars | Adjust prompt to request more detail |

## Promotion Bundle

When all gates pass, generate promotion bundle:

```bash
python3 -m colab_agent_fleet.scripts.render_fleet_summary \
  --results /tmp/run.jsonl \
  --gates /tmp/run_gates.json \
  --request "original request" \
  --out /tmp/promotion_bundle.md
```

Bundle includes:
- Gate pass/fail status with metrics
- Per-machine task results
- Top sources by domain
- Redacted for public sharing