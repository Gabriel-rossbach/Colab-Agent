import os
import subprocess
import time

# Carrega variáveis do ambiente (NVIDIA_API_KEY, MAQUINA)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Define a máquina alvo (cpu1 ou cpu2)
MAQUINA = os.getenv("MAQUINA", "cpu2") 
CHAVE_NVIDIA = os.getenv("NVIDIA_API_KEY")

if not CHAVE_NVIDIA:
    raise SystemExit(
        "❌ Variável NVIDIA_API_KEY não definida.\n"
        "Crie um arquivo .env na mesma pasta com:\n"
        "  NVIDIA_API_KEY=nvapi-sua-chave-aqui\n"
        "Ou exporte no terminal: export NVIDIA_API_KEY=nvapi-..."
    )

def garantir_maquina(maquina):
    print(f"🔍 Verificando sessões ativas para {maquina}...")
    dresultado = subprocess.run("colab sessions", shell=True, capture_output=True, text=True)
    resultado = dresultado.stdout.lower()
    
    marcador_sessao = f"[{maquina.lower()}]"
    
    if resultado.count(marcador_sessao) > 0:
        print(f"✅ Máquina '{maquina}' já está online. Pulando criação.")
    else:
        print(f"⚠️ Máquina '{maquina}' não encontrada. Criando nova instância na nuvem...")
        subprocess.run(f"colab new -s {maquina}", shell=True)
        print("⏳ Aguardando 15 segundos para o boot completo do contêiner...")
        time.sleep(15)

comando_remoto = f"""
echo '[1/5] Preparando dependências do sistema para o Navegador...'
if ! command -v chromium-browser &> /dev/null; then
    sudo apt-get update > /dev/null 2>&1
    sudo apt-get install -y chromium-browser libnss3 > /dev/null 2>&1
else
    echo '✅ Chromium já instalado.'
fi

echo '[2/5] Verificando instalação do OpenClaw...'
if ! command -v openclaw &> /dev/null; then
    echo 'Instalando OpenClaw via script oficial...'
    curl -fsSL https://openclaw.ai/install.sh | bash
else
    echo '✅ OpenClaw já está instalado.'
fi

pkill -f "openclaw gateway" || true

echo '[3/5] Verificando Plugins de Busca e Navegação...'
PLUGINS=$(openclaw plugins list 2>/dev/null || true)

if echo "$PLUGINS" | grep -q "duckduckgo"; then
    echo "✅ Plugin DuckDuckGo já está instalado."
else
    echo "Baixando Plugin DuckDuckGo..."
    openclaw plugins install @openclaw/duckduckgo-plugin --force || true
fi

if echo "$PLUGINS" | grep -q "browser"; then
    echo "✅ Plugin Browser já está instalado."
else
    echo "Baixando Plugin Browser..."
    openclaw plugins install @openclaw/browser-plugin --force || openclaw plugins install clawhub:browser --force || true
fi

openclaw config set tools.web.search.provider "duckduckgo" || true

echo '[4/5] Configurando provedor NVIDIA NIMs e Subindo o Gateway...'
openclaw config set models.providers.nvidia.baseUrl "https://integrate.api.nvidia.com/v1"
openclaw config set models.providers.nvidia.api "openai-completions"
openclaw config set agents.defaults.model "nvidia/nemotron-3.5-lightning-30b-a3b"
openclaw config set agents.defaults.timeoutSeconds 1800
echo '{CHAVE_NVIDIA}' | openclaw models auth paste-api-key --provider nvidia || true

# Sobe o gateway limpo em background
nohup openclaw gateway run --dev --force --allow-unconfigured --auth none --bind loopback > /tmp/gateway.log 2>&1 &

echo '⏳ Aguardando 10 segundos para o Gateway carregar as ferramentas...'
sleep 10

echo '[5/5] Disparando Agente NVIDIA (Tática Sniper via Snippets)...'
openclaw agent exec "Faça uma pesquisa no web_search para acessar diretamente a URL: https://docs.openclaw.ai/pt-BR/tools/browser-login . O navegador deve renderizar a página completa para passar por bloqueios. Me traga um resumo prático de como funciona o recurso de login no browser." \
    --model nvidia/nemotron-3.5-lightning-30b-a3b

exit
"""

def iniciar_missao():c
    garantir_maquina(MAQUINA)
    print(f"\n🚀 Conectando e executando deploy focado na {MAQUINA}...")
    subprocess.run(["colab", "ssh", "-s", MAQUINA], input=comando_remoto, text=True)

if __name__ == "__main__":
    iniciar_missao()