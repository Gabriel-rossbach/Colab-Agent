#!/usr/bin/env python3
"""
Deploy SEQUENCIAL COM PIPELINE: instala um, enquanto instala o próximo já começa.
Corrige o gateway auth (--auth none).
"""

import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

MAQUINAS = [m.strip() for m in os.getenv("MAQUINAS", "cpu1,cpu2,cpu3").split(",")]
CHAVE_NVIDIA = os.getenv("NVIDIA_API_KEY")

if not CHAVE_NVIDIA:
    sys.exit("❌ NVIDIA_API_KEY não definida no .env")

# Comando COM FIX DO GATEWAY AUTH
COMANDO_REMOTO = f"""
set -euo pipefail

echo "===== [$(hostname)] Deploy iniciado ====="

# 1. OpenClaw
if ! command -v openclaw &> /dev/null; then
    echo "[*] Instalando OpenClaw..."
    curl -fsSL https://openclaw.ai/install.sh | bash
    export PATH="$HOME/.openclaw/bin:$PATH"
else
    echo "[*] OpenClaw já instalado."
fi

# 2. Config NVIDIA
echo "[*] Configurando NVIDIA..."
openclaw config set models.providers.nvidia.baseUrl "https://integrate.api.nvidia.com/v1"
openclaw config set models.providers.nvidia.api "openai-completions"
openclaw config set agents.defaults.model "nvidia/nemotron-3.5-lightning-30b-a3b"

# 3. Auth key
echo "[*] Registrando API key..."
echo '{CHAVE_NVIDIA}' | openclaw models auth paste-api-key --provider nvidia || true

# 4. Plugin web-search
echo "[*] Criando plugin web-search..."
mkdir -p /root/openclaw-plugins/web-search/src

cat > /root/openclaw-plugins/web-search/package.json << 'PKGEOF'
{{
  "name": "openclaw-plugin-web-search",
  "version": "0.1.0",
  "type": "module",
  "private": true,
  "scripts": {{
    "build": "tsc -p tsconfig.json",
    "plugin:build": "npm run build && openclaw plugins build --entry ./dist/index.js"
  }},
  "peerDependencies": {{ "openclaw": ">=2026.5.17" }},
  "dependencies": {{ "typebox": "^1.1.38" }},
  "devDependencies": {{ "openclaw": "latest", "typescript": "7.0.2", "vitest": "^3.2.0" }},
  "openclaw": {{
    "extensions": ["./dist/index.js"],
    "compat": {{ "pluginApi": ">=2026.5.17" }},
    "build": {{ "openclawVersion": "2026.9.8" }}
  }}
}}
PKGEOF

cat > /root/openclaw-plugins/web-search/tsconfig.json << 'TSEOF'
{{
  "compilerOptions": {{
    "target": "ES2022",
    "module": "NodeNext",
    "moduleResolution": "NodeNext",
    "strict": true,
    "declaration": true,
    "rootDir": "src",
    "outDir": "dist",
    "skipLibCheck": true
  }},
  "include": ["src/index.ts", "src/duckduckgo-search.d.ts"]
}}
TSEOF

cat > /root/openclaw-plugins/web-search/src/duckduckgo-search.d.ts << 'DTEOF'
declare module 'duckduckgo-search' {{
  export interface DDGSResult {{ title: string; href: string; body: string; }}
  export class DDGS {{ text(query: string, options?: {{ max_results?: number }}): Promise<DDGSResult[]>; }}
}}
DTEOF

cat > /root/openclaw-plugins/web-search/src/index.ts << 'IDXEOF'
import {{ Type }} from "typebox";
import {{ defineToolPlugin }} from "openclaw/plugin-sdk/tool-plugin";

export default defineToolPlugin({{
  id: "web-search",
  name: "Web Search",
  description: "Add Web Search tools to OpenClaw via DuckDuckGo.",
  tools: (tool) => [
    tool({{
      name: "web_search",
      description: "Search the web via DuckDuckGo and return results.",
      parameters: Type.Object({{
        query: Type.String({{ description: "Search query string." }}),
        max_results: Type.Optional(Type.Integer({{ description: "Maximum number of results (default: 5).", minimum: 1, maximum: 20 }})),
      }}),
      execute: async ({{ query, max_results = 5 }}) => {{
        const {{ DDGS }} = await import("duckduckgo-search");
        try {{
          const ddgs = new DDGS();
          const results = await ddgs.text(query, {{ max_results }});
          return results;
        }} catch (error) {{
          return [{{ error: String(error) }}];
        }}
      }},
    }}),
  ],
}});
IDXEOF

# 5. Build plugin (parte pesada - roda em background)
echo "[*] Instalando deps e buildando plugin..."
cd /root/openclaw-plugins/web-search
npm install duckduckgo-search > /dev/null 2>&1
npm run plugin:build

# 6. Gateway COM AUTH NONE + instala plugin
echo "[*] Iniciando gateway (auth none) e instalando plugin..."
openclaw gateway run --dev --force --allow-unconfigured --auth none &
GW_PID=$!
sleep 8
openclaw plugins install /root/openclaw-plugins/web-search --force --accept-capabilities

# 7. Teste
echo "[*] Testando agente..."
openclaw agent exec \
  "Use web_search para buscar 'OpenClaw AI agent' e me dê 2 resultados com título e URL" \
  --model nvidia/nemotron-3.5-lightning-30b-a3b --local-model-lean

# Mata gateway
kill $GW_PID 2>/dev/null || true

echo "===== [$(hostname)] Deploy concluído ====="
"""

def deploy_na_maquina(maquina: str) -> tuple[str, bool, str]:
    print(f"🚀 [{maquina}] Iniciando deploy...")
    try:
        result = subprocess.run(
            ["colab", "ssh", "-s", maquina],
            input=COMANDO_REMOTO,
            text=True,
            timeout=900,  # 15 min
            capture_output=True,
        )
        if result.returncode == 0:
            print(f"✅ [{maquina}] SUCESSO")
            return maquina, True, ""
        else:
            err = result.stderr[-800:] if result.stderr else "unknown"
            print(f"❌ [{maquina}] FALHOU: {err[:200]}...")
            return maquina, False, err[:300]
    except subprocess.TimeoutExpired:
        print(f"⏰ [{maquina}] TIMEOUT (15 min)")
        return maquina, False, "timeout"
    except Exception as e:
        print(f"❌ [{maquina}] ERRO: {e}")
        return maquina, False, str(e)


def main():
    print(f"🎯 Alvos: {', '.join(MAQUINAS)}")
    print("⚡ Modo PIPELINE: inicia próximo após 60s (install pesado sobreposto)\n")

    resultados = {}
    with ThreadPoolExecutor(max_workers=len(MAQUINAS)) as executor:
        futures = {}
        for i, m in enumerate(MAQUINAS):
            if i > 0:
                print(f"⏳ Aguardando 60s antes de iniciar {m} (pipeline)...")
                time.sleep(60)  # Pipeline: overlap install pesado
            futures[executor.submit(deploy_na_maquina, m)] = m

        for fut in as_completed(futures):
            maquina, ok, err = fut.result()
            resultados[maquina] = (ok, err)

    print("\n" + "="*60)
    print("📋 RESUMO FINAL")
    for m, (ok, err) in resultados.items():
        status = "✅ SUCESSO" if ok else f"❌ FALHA ({err})"
        print(f"  {m}: {status}")

    if all(ok for ok, _ in resultados.values()):
        print("\n🎉 Todas prontas!")
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()