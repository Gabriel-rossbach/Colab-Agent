# OpenClaw Integration Reference

## Plugin: web-search

### Installation (Local Plugin)
```bash
# Create plugin structure
mkdir -p /root/openclaw-plugins/web-search/src

# Write plugin files (see skill/colab-agent-fleet/scripts/ for template)
# package.json, tsconfig.json, src/index.ts, src/duckduckgo-search.d.ts

# Build
cd /root/openclaw-plugins/web-search
npm install duckduckgo-search
npm run plugin:build

# Install
openclaw plugins install /root/openclaw-plugins/web-search --force --accept-capabilities
```

### Plugin Structure
```typescript
// src/index.ts
import { Type } from "typebox";
import { defineToolPlugin } from "openclaw/plugin-sdk/tool-plugin";

export default defineToolPlugin({
  id: "web-search",
  name: "Web Search",
  description: "Add Web Search tools to OpenClaw via DuckDuckGo.",
  tools: (tool) => [
    tool({
      name: "web_search",
      description: "Search the web via DuckDuckGo and return results.",
      parameters: Type.Object({
        query: Type.String({ description: "Search query string." }),
        max_results: Type.Optional(Type.Integer({ minimum: 1, maximum: 20 })),
      }),
      execute: async ({ query, max_results = 5 }) => {
        const { DDGS } = await import("duckduckgo-search");
        const ddgs = new DDGS();
        return await ddgs.text(query, { max_results });
      },
    }),
  ],
});
```

## Gateway Configuration

### For Embedded Agent Exec (Fast, No Network)
```bash
# No gateway needed for --local-model-lean
openclaw agent exec "prompt" --model nvidia/nemotron-3.5-lightning-30b-a3b --local-model-lean
```

### For Plugin Tools (Requires Gateway)
```bash
# Start gateway (dev mode, no auth, loopback only)
openclaw gateway run --dev --force --allow-unconfigured --auth none --bind loopback &

# Health-check
curl -sf http://localhost:19000/health

# Then run agent (will connect to gateway for tool calls)
openclaw agent exec "Use web_search para..." --model nvidia/nemotron-3.5-lightning-30b-a3b
```

### Gateway Flags Explained
| Flag | Purpose |
|------|---------|
| `--dev` | Dev config + workspace if missing |
| `--force` | Kill existing listener on port |
| `--allow-unconfigured` | Skip gateway.mode check |
| `--auth none` | No token/password required |
| `--bind loopback` | Only 127.0.0.1 (no external exposure) |

## Agent Exec Modes

| Mode | Flag | Gateway | Tools | Speed |
|------|------|---------|-------|-------|
| Embedded (lean) | `--local-model-lean` | No | Core only | Fastest |
| Embedded (full) | (none) | No | All local | Fast |
| Via Gateway | (default) | Yes | All (incl. plugins) | Slower |

**Fleet uses**: Embedded lean for speed, but **gateway must run** for plugin tools (web_search).

## NVIDIA NIMs Configuration

```bash
openclaw config set models.providers.nvidia.baseUrl "https://integrate.api.nvidia.com/v1"
openclaw config set models.providers.nvidia.api "openai-completions"
openclaw config set agents.defaults.model "nvidia/nemotron-3.5-lightning-30b-a3b"
openclaw config set agents.defaults.timeoutSeconds 1800

# Auth (one-time per session)
echo "$NVIDIA_API_KEY" | openclaw models auth paste-api-key --provider nvidia
```

## Common Issues

| Issue | Fix |
|-------|-----|
| `web_search is disabled` | Gateway not running OR plugin not installed OR plugin not enabled |
| `plugin tool name conflict` | Multiple plugins register same tool name; accept conflict or rename |
| `SQLite offline maintenance` | Wait or restart gateway; stagger launches |
| `gateway.mode missing` | `openclaw config set gateway.mode local` or use `--allow-unconfigured` |
| `auth required for plugins.enable` | Gateway needs auth; use `--auth none` for dev |

## Agent Config (agents/openai.yaml)
```yaml
model: "nvidia/nemotron-3.5-lightning-30b-a3b"
provider: "nvidia"
temperature: 0.2
max_tokens: 4096
execution:
  mode: "local"
  lean: true
  timeout_seconds: 1800
```