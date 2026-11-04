import os
import shlex
import subprocess

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

MAQUINA = os.getenv("MAQUINA", "cpu2") 
CHAVE_NVIDIA = os.getenv("NVIDIA_API_KEY")
URL = "https://docs.openclaw.ai/pt-BR/tools/browser-login"

if not CHAVE_NVIDIA:
    raise SystemExit("❌ Variável NVIDIA_API_KEY não definida.")

# Modelo e Template do script Bash usando marcadores simples em vez de f-string
SCRIPT_TEMPLATE = r"""
echo '[1/4] Instalando dependências e Playwright...'
pip install -q playwright
playwright install --with-deps chromium

echo '[2/4] Executando scraper...'
cat << 'EOF' > /tmp/scraper.py
import sys
from playwright.sync_api import sync_playwright

url = sys.argv[1] if len(sys.argv) > 1 else ""
if url:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(2000)
            print(page.inner_text("body")[:5000])
        except Exception as e:
            print(f"Erro ao acessar: {e}")
        finally:
            browser.close()
EOF

python3 /tmp/scraper.py __URL__ > /tmp/conteudo_pagina.txt

echo '[3/4] Montando Prompt da Missão...'
{
  echo "Com base exclusivamente no conteúdo abaixo extraído da documentação, resuma em português como funciona o login no browser:"
  echo ""
  cat /tmp/conteudo_pagina.txt
} > /tmp/prompt_final.md

echo '[4/4] Configurando NVIDIA e Disparando OpenClaw...'
openclaw config set models.providers.nvidia.baseUrl "https://integrate.api.nvidia.com/v1"
openclaw config set models.providers.nvidia.api "openai-completions"
echo __CHAVE__ | openclaw models auth paste-api-key --provider nvidia || true

openclaw agent --agent main --local \
    --model nvidia/nemotron-3.5-lightning-30b-a3b \
    --message-file /tmp/prompt_final.md

exit
"""

def iniciar_missao():
    print(f"Iniciando missão na {MAQUINA}...\n")
    script_preparado = (
        SCRIPT_TEMPLATE
        .replace("__URL__", shlex.quote(URL))
        .replace("__CHAVE__", shlex.quote(CHAVE_NVIDIA))
    )
    subprocess.run(["colab", "ssh", "-s", MAQUINA], input=script_preparado, text=True)

if __name__ == "__main__":
    iniciar_missao()

    