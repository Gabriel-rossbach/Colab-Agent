import os
import json
import base64
import shlex
import asyncio
from dotenv import load_dotenv

from plano import (
    MODELO_PLANEJADOR,
    extrair_resposta,
    mensagem_de_correcao,
    montar_mensagens,
    validar_plano,
)

load_dotenv()
CHAVE_NVIDIA = os.getenv("NVIDIA_API_KEY")

if not CHAVE_NVIDIA:
    raise SystemExit("❌ Variável NVIDIA_API_KEY não definida no arquivo .env.")

# Confirme a sintaxe com: colab new --help
FLAGS_GPU = "--gpu t4"
MAX_TENTATIVAS = 2

# Máquinas de pesquisa (cpu1 a cpu5). O prompt vai em base64: o shell não interpreta nada.
SCRIPT_AGENTE = r"""
echo '[1/4] Verificando OpenClaw...'
if ! command -v openclaw &> /dev/null; then
    curl -fsSL https://openclaw.ai/install.sh | bash
fi

echo 'Encerrando Gateways antigos...'
pkill -f "openclaw gateway" || true
sleep 2

echo '[2/4] Verificando plugins...'
PLUGINS=$(openclaw plugins list 2>/dev/null || true)
if ! echo "$PLUGINS" | grep -q "duckduckgo"; then
    openclaw plugins install @openclaw/duckduckgo-plugin --force || true
fi
openclaw config set tools.web.search.provider "duckduckgo" || true

echo '[3/4] Configurando NVIDIA...'
openclaw config set models.providers.nvidia.baseUrl "https://integrate.api.nvidia.com/v1"
openclaw config set models.providers.nvidia.api "openai-completions"
openclaw config set agents.defaults.model "nvidia/nemotron-3.5-lightning-30b-a3b"
openclaw config set agents.defaults.timeoutSeconds 1800
echo __CHAVE__ | openclaw models auth paste-api-key --provider nvidia || true

echo 'Iniciando Gateway...'
nohup openclaw gateway run --dev --force --allow-unconfigured --auth none --bind loopback > /tmp/gateway.log 2>&1 &
sleep 10

echo '[4/4] Disparando agente...'
echo '__PROMPT_B64__' | base64 -d > /tmp/missao.txt
openclaw agent exec "$(cat /tmp/missao.txt)" --model nvidia/nemotron-3.5-lightning-30b-a3b
RC=$?
echo "AGENTE_EXIT=$RC"
[ "$RC" -eq 0 ] && echo MISSAO_OK
exit
"""

# Máquina com GPU (cpu6). Mantém o Ollama no ar e devolve a resposta do modelo em base64.
SCRIPT_PLANNER = r"""
echo '[cpu6] GPU:'
nvidia-smi -L || echo '⚠️ Sem GPU: o modelo vai rodar na CPU, bem mais lento'

if ! command -v ollama &> /dev/null; then
    echo '[cpu6] Instalando Ollama...'
    apt-get update > /dev/null 2>&1 && apt-get install -y zstd > /dev/null 2>&1
    curl -fsSL https://ollama.com/install.sh | sh
fi

if ! curl -s http://localhost:11434/api/tags > /dev/null; then
    echo '[cpu6] Subindo o servidor do modelo...'
    nohup ollama serve > /tmp/ollama.log 2>&1 &
    for i in $(seq 1 30); do
        curl -s http://localhost:11434/api/tags > /dev/null && break
        sleep 2
    done
fi

if ! ollama list | grep -q "__MODELO__"; then
    echo '[cpu6] Baixando __MODELO__ (na VM nova pode levar alguns minutos)...'
    ollama pull __MODELO__ > /tmp/pull.log 2>&1 || echo '⚠️ Falha no download (veja /tmp/pull.log)'
fi

echo '__REQ_B64__' | base64 -d > /tmp/req.json

python3 - << 'PY'
import base64, json, urllib.request, urllib.error
corpo = open('/tmp/req.json', 'rb').read()
texto = None
try:
    resposta = urllib.request.urlopen(
        urllib.request.Request(
            "http://localhost:11434/api/chat",
            data=corpo,
            headers={"Content-Type": "application/json"},
        ),
        timeout=900,
    )
    texto = json.load(resposta)["message"]["content"]
except urllib.error.HTTPError as e:
    print("ERRO_MODELO:", e.code, e.read().decode("utf-8", errors="replace"))
except Exception as e:
    print("ERRO_MODELO:", e)
print("PLANO_B64_INICIO")
if texto is not None:
    print(base64.b64encode(texto.encode("utf-8")).decode("ascii"))
print("PLANO_B64_FIM")
PY
exit
"""


def gerar_comando_bash(prompt: str) -> str:
    prompt_b64 = base64.b64encode(prompt.encode("utf-8")).decode("ascii")
    return (
        SCRIPT_AGENTE
        .replace("__PROMPT_B64__", prompt_b64)
        .replace("__CHAVE__", shlex.quote(CHAVE_NVIDIA))
    )


def gerar_comando_planner(mensagens: list[dict]) -> str:
    requisicao = {
        "model": MODELO_PLANEJADOR,
        "messages": mensagens,
        "stream": False,
        "options": {"temperature": 0.2, "num_ctx": 4096, "num_predict": 4096},
    }
    # "think" só é aceito por modelos com raciocínio (gpt-oss). Nos outros, o Ollama devolve 400.
    if MODELO_PLANEJADOR.startswith("gpt-oss"):
        requisicao["think"] = "low"
    req_b64 = base64.b64encode(
        json.dumps(requisicao, ensure_ascii=False).encode("utf-8")
    ).decode("ascii")
    return (
        SCRIPT_PLANNER
        .replace("__MODELO__", MODELO_PLANEJADOR)
        .replace("__REQ_B64__", req_b64)
    )


async def garantir_maquina(maquina: str, callback_log, flags: str = "") -> None:
    callback_log(f"🔍 Verificando sessões ativas para {maquina}...")
    proc = await asyncio.create_subprocess_shell(
        "colab sessions",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    if f"[{maquina.lower()}]" in stdout.decode("utf-8", errors="replace").lower():
        callback_log(f"✅ {maquina} online.")
        return

    callback_log(f"⚠️ {maquina} offline. Criando instância...")
    proc_new = await asyncio.create_subprocess_shell(
        f"colab new -s {maquina} {flags}".strip(),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    saida, _ = await proc_new.communicate()
    for linha in saida.decode("utf-8", errors="replace").splitlines()[-5:]:
        callback_log(linha)
    callback_log("⏳ Aguardando boot (15s)...")
    await asyncio.sleep(15)


async def rodar_script(maquina: str, script: str, callback_log) -> str:
    proc = await asyncio.create_subprocess_shell(
        f"colab ssh -s {maquina}",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    proc.stdin.write(script.encode("utf-8"))
    proc.stdin.close()

    linhas = []
    escondendo = False
    while True:
        linha = await proc.stdout.readline()
        if not linha:
            break
        texto = linha.decode("utf-8", errors="replace").rstrip()
        linhas.append(texto)

        # O bloco base64 do planejador é guardado, mas não vai para o log
        if texto == "PLANO_B64_INICIO":
            escondendo = True
        if not escondendo:
            callback_log(texto)
        if texto == "PLANO_B64_FIM":
            escondendo = False

    await proc.wait()
    return "\n".join(linhas)


async def executar_agente(maquina: str, prompt: str, callback_log) -> bool:
    await garantir_maquina(maquina, callback_log)
    callback_log(f"\n🚀 Injetando missão na {maquina}...")
    saida = await rodar_script(maquina, gerar_comando_bash(prompt), callback_log)
    concluiu = any(linha.strip() == "MISSAO_OK" for linha in saida.splitlines())
    if concluiu:
        callback_log(f"\n[+] Missão concluída na {maquina}.")
    else:
        callback_log(f"\n[✗] {maquina} não confirmou o fim da missão. Veja o log acima.")
    return concluiu


async def pedir_ao_modelo(mensagens: list[dict], callback_log):
    saida = await rodar_script("cpu6", gerar_comando_planner(mensagens), callback_log)
    return extrair_resposta(saida)


async def planejar(pedido: str, callback_log):
    await garantir_maquina("cpu6", callback_log, flags=FLAGS_GPU)

    mensagens = montar_mensagens(pedido)
    for tentativa in range(1, MAX_TENTATIVAS + 1):
        callback_log(f"\n🧠 Montando o plano com {MODELO_PLANEJADOR} (tentativa {tentativa}/{MAX_TENTATIVAS})...")
        resposta = await pedir_ao_modelo(mensagens, callback_log)
        if resposta is None:
            callback_log("⚠️ Não recebi resposta do modelo. Veja o erro acima.")
            continue

        callback_log("📄 Resposta do modelo:")
        for linha in resposta.splitlines():
            callback_log(f"   {linha}")

        plano, erros = validar_plano(resposta, pedido)
        if not erros:
            total = sum(len(itens) for itens in plano.values())
            callback_log(f"✅ Plano verificado: {total} tarefa(s) em {len(plano)} máquina(s).")
            return plano

        callback_log("⚠️ Plano fora das regras:")
        for erro in erros:
            callback_log(f"   - {erro}")
        mensagens = mensagens + [
            {"role": "assistant", "content": resposta},
            {"role": "user", "content": mensagem_de_correcao(erros)},
        ]

    callback_log("❌ Plano inválido após todas as tentativas. Nenhuma máquina de pesquisa foi ligada.")
    return None