# Architecture Decisions

## 1. Two-Lane Separation (Planning vs Execution)

**Decision**: Separate GPU planner (local LLM) from CPU execution fleet (NVIDIA NIMs).

**Rationale**:
- Planning is latency-sensitive but low-throughput → local Ollama (free, private, no API keys)
- Execution is throughput-sensitive, needs structured output + tools → NVIDIA NIMs (fast, reliable, web_search)
- Cost: GPU only for seconds; CPUs for minutes

**Alternatives Considered**:
- Single lane with API planner (OpenAI/Anthropic) → rejected: API keys, cost, latency
- All local (Ollama for everything) → rejected: Nemotron better for structured tool use

## 2. Colab as Infrastructure

**Decision**: Use Google Colab free tier (CPU) + optional GPU for planner.

**Rationale**:
- 5+ clean public IPs (natural rate-limit distribution)
- Free compute for research workloads
- Ephemeral = no persistent state management
- SSH access via `colab` CLI

**Trade-offs**:
- Session startup ~2-3 min cold
- 12h max runtime (free tier)
- SQLite lock issues on parallel gateway starts → mitigated by pipeline stagger

## 3. OpenClaw Plugin for web_search

**Decision**: Custom TypeScript plugin (`web-search`) using `duckduckgo-search`, not `@openclaw/duckduckgo-plugin`.

**Rationale**:
- Official plugin may not exist / version mismatch
- Full control over tool schema, execution, error handling
- No registry dependency; installs from local path

**Plugin Interface**:
```typescript
tool({
  name: "web_search",
  parameters: { query: string, max_results?: number },
  execute: async ({ query, max_results = 5 }) => DDGS().text(query, { max_results })
})
```

## 4. Gateway Per Machine (Not Shared)

**Decision**: Each CPU machine runs its own gateway (`--auth none --bind loopback`).

**Rationale**:
- Plugin tools require gateway
- Shared gateway = single point of failure + auth complexity
- Loopback bind = no external exposure
- Dev mode = no persistent config needed

## 5. Fleet Plan as JSON (Not YAML/TOML)

**Decision**: Fleet plan = JSON with strict schema (`plan-spec.md`).

**Rationale**:
- Machine-readable for validation (`validate_fleet_plan.py`)
- Easy to generate from LLM (JSON mode)
- Schema versionable
- CI-friendly

## 6. Pipeline Stagger (60s Between Machines)

**Decision**: Launch machines sequentially with 60s delay, not fully parallel.

**Rationale**:
- SQLite "offline maintenance" errors when 5 gateways start simultaneously
- 60s stagger = ~5 min total launch vs 2 min parallel, but 99% success vs 40%
- Acceptable for research workloads (not real-time)

## 7. Human-in-the-Loop Confirmation

**Decision**: Dashboard requires explicit "continuar" before fleet launch.

**Rationale**:
- Colab compute costs money (compute units)
- Prevents accidental launches from bad plans
- Allows plan review (promotion gates preview)

## 8. Embedded Lean Agent Exec

**Decision**: Use `openclaw agent exec --local-model-lean` for speed.

**Rationale**:
- No gateway round-trip for core reasoning
- Gateway only needed for plugin tools (web_search)
- 2-3x faster than full gateway mode

## 9. Base64 for Prompt Injection

**Decision**: Pass prompts via `base64 -d` to avoid shell escaping hell.

**Rationale**:
- Prompts contain quotes, $(), backticks, newlines
- Base64 = zero escaping issues
- Simple: `echo 'b64' | base64 -d > /tmp/missao.txt`

## 10. Markdown Summary with Redaction

**Decision**: Final output = markdown summary + JSONL raw + gates JSON, all redacted.

**Rationale**:
- Human-readable report
- Machine-readable for downstream
- Safe for public sharing (no secrets, private URLs)
- `fleet_public_safety.py` ensures consistency