# Referência de integração com o OpenClaw

## Plugin: web-search

### Instalação (plugin local)
```bash
# Criar a estrutura do plugin
mkdir -p /root/openclaw-plugins/web-search/src

# Escrever os arquivos do plugin (veja skill/colab-agent-fleet/scripts/ para o modelo)
# package.json, tsconfig.json, src/index.ts, src/duckduckgo-search.d.ts

# Build
cd /root/openclaw-plugins/web-search
npm install duckduckgo-search
npm run plugin:build

# Instalar
openclaw plugins install /root/openclaw-plugins/web-search --force --accept-capabilities
```

### Estrutura do plugin
```typescript
// src/index.ts
import { Type } from "typebox";
import { defineToolPlugin } from "openclaw/plugin-sdk/tool-plugin";

export default defineToolPlugin({
  id: "web-search",
  name: "Web Search",
  description: "Adiciona ferramentas de busca web ao OpenClaw via DuckDuckGo.",
  tools: (tool) => [
    tool({
      name: "web_search",
      description: "Busca na web via DuckDuckGo e retorna resultados.",
      parameters: Type.Object({
        query: Type.String({ description: "String da consulta de busca." }),
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

## Configuração do gateway

### Para agent exec embutido (rápido, sem rede)
```bash
# Não precisa de gateway para --local-model-lean
openclaw agent exec "prompt" --model nvidia/nemotron-3.5-lightning-30b-a3b --local-model-lean
```

### Para ferramentas de plugin (exige gateway)
```bash
# Inicia o gateway (modo dev, sem auth, somente loopback)
openclaw gateway run --dev --force --allow-unconfigured --auth none --bind loopback &

# Health-check
curl -sf http://localhost:19000/health

# Depois roda o agente (vai conectar ao gateway para as chamadas de ferramenta)
openclaw agent exec "Use web_search para..." --model nvidia/nemotron-3.5-lightning-30b-a3b
```

### Flags do gateway explicadas
| Flag | Finalidade |
|------|------------|
| `--dev` | Config de dev + workspace se faltar |
| `--force` | Mata o listener existente na porta |
| `--allow-unconfigured` | Pula a checagem de gateway.mode |
| `--auth none` | Sem token/senha obrigatório |
| `--bind loopback` | Só 127.0.0.1 (sem exposição externa) |

## Modos de agent exec

| Modo | Flag | Gateway | Ferramentas | Velocidade |
|------|------|---------|-------------|------------|
| Embutido (lean) | `--local-model-lean` | Não | Só core | Mais rápido |
| Embutido (full) | (nenhuma) | Não | Todas as locais | Rápido |
| Via gateway | (default) | Sim | Todas (incl. plugins) | Mais lento |

**A fleet usa**: embutido lean pela velocidade, mas **o gateway precisa estar rodando** para as ferramentas de plugin (web_search).

## Configuração dos NVIDIA NIMs

```bash
openclaw config set models.providers.nvidia.baseUrl "https://integrate.api.nvidia.com/v1"
openclaw config set models.providers.nvidia.api "openai-completions"
openclaw config set agents.defaults.model "nvidia/nemotron-3.5-lightning-30b-a3b"
openclaw config set agents.defaults.timeoutSeconds 1800

# Auth (uma vez por sessão)
echo "$NVIDIA_API_KEY" | openclaw models auth paste-api-key --provider nvidia
```

## Problemas comuns

| Problema | Correção |
|----------|----------|
| `web_search is disabled` | Gateway não está rodando OU plugin não instalado OU plugin não habilitado |
| `plugin tool name conflict` | Vários plugins registram a mesma ferramenta; aceite o conflito ou renomeie |
| `SQLite offline maintenance` | Aguarde ou reinicie o gateway; espace os disparos |
| `gateway.mode missing` | `openclaw config set gateway.mode local` ou use `--allow-unconfigured` |
| `auth required for plugins.enable` | O gateway exige auth; use `--auth none` em dev |

## Config do agente (agents/openai.yaml)
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
