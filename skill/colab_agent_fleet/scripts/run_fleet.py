#!/usr/bin/env python3
"""
Executa um fleet plan validado nas máquinas Colab.
- Pipeline staggered (60s entre máquinas) para evitar SQLite lock
- Health-check do gateway antes de disparar agente
- Agrega resultados JSONL + aplica promotion gates
- Gera markdown summary
"""

import argparse
import asyncio
import base64
import inspect
import json
import math
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any


class FleetCancelled(Exception):
    """Execução cancelada cooperativamente pelo orquestrador."""


def _cancel_requested(cancel_path: str | Path | None) -> bool:
    return cancel_path is not None and Path(cancel_path).exists()


def _validar_nome_maquina(maquina: str) -> None:
    if not re.fullmatch(r"cpu[1-6]", maquina):
        raise ValueError(f"Nome de máquina inválido: {maquina!r}")


async def _emit_event(event_callback, **event) -> None:
    if event_callback is None:
        return
    resultado = event_callback(event)
    if inspect.isawaitable(resultado):
        await resultado


async def _encerrar_processo(proc) -> None:
    if proc.returncode is not None:
        return
    try:
        proc.terminate()
    except ProcessLookupError:
        return
    try:
        await asyncio.wait_for(proc.wait(), timeout=5)
    except (asyncio.TimeoutError, ProcessLookupError):
        try:
            proc.kill()
        except ProcessLookupError:
            return
        await proc.wait()


async def _comunicar_com_timeout(
    proc,
    timeout: int,
    descricao: str,
    cancel_path: str | Path | None = None,
):
    communication = asyncio.create_task(proc.communicate())
    deadline = asyncio.get_running_loop().time() + timeout
    try:
        while True:
            if _cancel_requested(cancel_path):
                await _encerrar_processo(proc)
                await communication
                raise FleetCancelled(f"Cancelamento solicitado em {descricao}")
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                await _encerrar_processo(proc)
                await communication
                raise RuntimeError(f"Timeout de {timeout}s em {descricao}")
            try:
                return await asyncio.wait_for(
                    asyncio.shield(communication),
                    timeout=min(1, remaining),
                )
            except asyncio.TimeoutError:
                pass
    except asyncio.CancelledError:
        await _encerrar_processo(proc)
        await communication
        raise


async def _limpar_processos_remotos(maquina: str, callback_log) -> None:
    """Melhor esforço: encerra agente/gateway sem desligar a sessão Colab."""
    callback_log(f"🧹 {maquina}: limpando processos remotos após cancelamento...")
    proc = await asyncio.create_subprocess_shell(
        f"colab ssh -s {maquina}",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    proc.stdin.write(
        b'pkill -f "openclaw agent" 2>/dev/null || true\n'
        b'pkill -f "openclaw[- ]gateway" 2>/dev/null || true\n'
        b"exit\n"
    )
    proc.stdin.close()
    try:
        await asyncio.wait_for(proc.wait(), timeout=15)
    except asyncio.TimeoutError:
        await _encerrar_processo(proc)
        callback_log(f"⚠️ {maquina}: limpeza remota excedeu o tempo limite.")


# ─── CONFIG ────────────────────────────────────────────────────────
def build_script_agente(use_browser: bool) -> str:
    """Gera o script do agente com ou sem browser tool. JSON gerado via json.dumps para ser válido."""
    import json as _json

    browser_install = r"""
# Browser tool (Google Chrome)
if [ "{use_browser_str}" = "true" ]; then
    echo "[*] Instalando Google Chrome..."
    wget -q https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
    apt-get update -qq && apt-get install -y -qq ./google-chrome-stable_current_amd64.deb > /dev/null 2>&1
    echo "[*] Browser pronto."
fi
""".replace("{use_browser_str}", "true" if use_browser else "false")

    # Build config as Python dict, then dump to JSON
    config = {
        "models": {
            "providers": {
                "nvidia": {
                    "baseUrl": "https://integrate.api.nvidia.com/v1",
                    "api": "openai-completions",
                    "apiKey": "$NVIDIA_API_KEY"
                }
            }
        },
        "agents": {
            "defaults": {
                "model": "nvidia/nemotron-3.5-lightning-30b-a3b",
                "timeoutSeconds": 1800
            },
            "entries": {
                "main": {
                    "tools": {
                        "allow": ["group:web", "browser"]
                    }
                }
            }
        },
        "gateway": {
            "mode": "local",
            "bind": "loopback",
            "port": 3456,
            "auth": {"mode": "token", "token": "opencrawl-fleet-token"}
        },
        "tools": {
            "allow": ["group:web"],
        },
        "plugins": {
            "enabled": True,
            "allow": ["duckduckgo"],
            "entries": {
                "duckduckgo": {
                    "enabled": True,
                    "config": {
                        "webSearch": {
                            "region": "br-pt",
                            "safeSearch": "moderate"
                        }
                    }
                }
            }
        }
    }

    if use_browser:
        config["tools"]["allow"] = ["*"]  # allow all tools including browser plugin tools
        config["agents"]["entries"]["main"]["tools"]["allow"] = ["*"]
        config["tools"]["web"] = {
            "search": {
                "enabled": True,
                "provider": "duckduckgo",
                "maxResults": 10,
                "timeoutSeconds": 30,
                "cacheTtlMinutes": 15
            },
            "fetch": {
                "enabled": True,
                "maxCharsCap": 30000
            }
        }
        config["browser"] = {
            "enabled": True,
            "defaultProfile": "openclaw",
            "headless": True,
            "noSandbox": True,
            "profiles": {
                "openclaw": {
                    "driver": "openclaw",
                    "engine": "chromium",
                    "cdpPort": 9222
                }
            }
        }
        # Add browser plugin to config
        config["plugins"]["allow"].append("browser")
        config["plugins"]["entries"]["browser"] = {
            "enabled": True,
            "config": {}
        }
    else:
        config["tools"]["web"] = {
            "search": {
                "enabled": True,
                "provider": "duckduckgo",
                "maxResults": 10,
                "timeoutSeconds": 30,
                "cacheTtlMinutes": 15
            }
        }

    config_json = _json.dumps(config, indent=2)

    use_browser_str = "true" if use_browser else "false"

    tool_rules = r"""
FERRAMENTAS DISPONÍVEIS:
1. web_search — pesquisa rápida, fatos públicos, múltiplas fontes (DuckDuckGo)
2. browser — navegação real com Chromium (ID exato: "browser")

USO DA FERRAMENTA BROWSER (fluxo obrigatório para interagir com páginas):
1. {"action": "navigate", "url": "https://..."} — navega para a página
2. {"action": "snapshot"} — tira um snapshot da página que retorna REFS (IDs) de cada elemento clicável (botões, inputs, links)
3. {"action": "act", "kind": "type"/"click", "ref": "e12", "text": "..."} — usa os REFS do snapshot para digitar em campos e clicar em botões
   - Para preencher um campo: snapshot → achar o ref do input → act kind=type ref=eXX text="valor"
   - Para clicar num botão: snapshot → achar o ref do botão → act kind=click ref=eXX
4. {"action": "screenshot"} — tira screenshot visual
5. {"action": "text"} — extrai texto visível da página

RECUPERAÇÃO DE ERROS DO BROWSER (MUITO IMPORTANTE):
- Os REFS ficam INVÁLIDOS toda vez que a página muda (após navigate, act, screenshot ou re-render).
  NUNCA reutilize um ref de snapshot antigo — sempre faça snapshot de novo antes do próximo act.
- Se uma ação falhar com "Unknown ref ..." ou "timed out ... unknown outcome":
  1. NÃO repita a mesma ação com o mesmo ref.
  2. Faça {"action": "snapshot"} (ou {"action": "text"}) para ver o estado ATUAL da página.
  3. Use os refs NOVOS do snapshot para continuar.
- Se navigate der timeout: tente 1 vez de novo; se falhar de novo, faça snapshot para ver em que página o browser está.
- Se a MESMA ação falhar 2 vezes seguidas, pare de tentar e descreva o que aconteceu no relatório final.

EXEMPLO DE LOGIN:
- navigate url=https://site.com/login
- snapshot (pega refs: e5=campo email, e6=campo senha, e7=botão entrar)
- act kind=type ref=e5 text="email@exemplo.com"
- act kind=type ref=e6 text="senha123"
- act kind=click ref=e7
- navigate ou snapshot para ver a home após login

REGRAS DE USO:
- Use web_search SEMPRE que possível (mais rápido, leve, múltiplas fontes)
- Use browser SÓ quando necessário: login, formulários, clicar, screenshot, sites com JS pesado
- NÃO use browser para pesquisa simples de fatos públicos""" if use_browser else r"""
REGRAS OBRIGATÓRIAS:
1. Sua ÚNICA ferramenta é web_search. Não tente usar nenhuma outra.
2. Ao chamar web_search, os argumentos DEVEM ser no formato exato: {"query": "texto da pesquisa", "count": 5}
   - Parâmetro obrigatório: query (string) — NUNCA use outro nome como 'args', 'limit', 'q', 'search'
   - Parâmetro opcional: count (número de 1 a 10) — NUNCA use 'limit'
3. Chame web_search pelo menos 2 vezes com ângulos diferentes antes de responder.
4. Baseie sua resposta EXCLUSIVAMENTE nos resultados retornados por web_search.
5. Se web_search retornar erro de argumentos, corrija para {"query": "..."} e tente de novo."""

    browser_gateway_start = r"""
# Inicia gateway para browser tool (necessário para tool browser)
echo "[*] Parando gateway anterior se houver..."
pkill -9 -f "openclaw[- ]gateway" 2>/dev/null || true
sleep 3
echo "[*] Iniciando OpenClaw Gateway..."
export OPENCLAW_GATEWAY_TOKEN="opencrawl-fleet-token"
export OPENCLAW_CONFIG_PATH="/root/.openclaw/openclaw.json"
openclaw gateway --port 3456 --token "$OPENCLAW_GATEWAY_TOKEN" > /tmp/gateway.log 2>&1 &
GATEWAY_PID=$!
# Aguarda gateway ficar TOTALMENTE pronto (post-ready = todos os sidecars e plugins prontos)
# Num gateway novo leva ~60-75s até "post-ready.startup-maintenance" - se o agent rodar antes, o browser tool não aparece
echo "[*] Aguardando gateway ficar totalmente pronto..."
GATEWAY_READY=false
for i in $(seq 1 20); do
    sleep 5
    if strings /tmp/gateway.log 2>/dev/null | grep -q "post-ready.startup-maintenance"; then
        echo "[*] Gateway totalmente pronto após $((i*5))s (post-ready)"
        GATEWAY_READY=true
        break
    fi
done
if [ "$GATEWAY_READY" != "true" ]; then
    echo "[ERRO] Gateway não ficou pronto dentro do tempo limite."
    strings /tmp/gateway.log 2>/dev/null | tail -20 || true
    pkill -9 -f "openclaw[- ]gateway" 2>/dev/null || true
    exit 70
fi
# Verifica porta e plugins
if ss -tln 2>/dev/null | grep -q ":3456 "; then
    echo "[*] Gateway OK (porta 3456 ativa)."
else
    echo "[AVISO] Porta 3456 não está escutando!"
    strings /tmp/gateway.log | tail -20
fi
# Verifica se browser plugin carregou
echo "[*] Verificando plugins no gateway log..."
strings /tmp/gateway.log | grep "http server listening" || echo "[AVISO] Linha de plugins não encontrada"
""" if use_browser else ""

    return rf"""
set -euo pipefail
echo "===== [$(hostname)] Iniciando tarefa ====="

# 1. OpenClaw
if ! command -v openclaw &> /dev/null; then
    echo "[*] Instalando OpenClaw..."
    curl -fsSL https://openclaw.ai/install.sh | bash
    export PATH="$HOME/.openclaw/bin:$PATH"
else
    echo "[*] OpenClaw já instalado."
fi

# 2. Plugin web-search (usa plugin oficial @openclaw/duckduckgo-plugin)
echo "[*] Instalando plugin duckduckgo oficial..."
openclaw plugins install @openclaw/duckduckgo-plugin --force --accept-capabilities || true
openclaw plugins enable duckduckgo || true

# 2b. Browser plugin (necessário para ferramenta browser)
{browser_install}
# Instalar plugin de browser se habilitado
if [ "{use_browser_str}" = "true" ]; then
    echo "[*] Instalando plugin browser oficial..."
    openclaw plugins install @openclaw/browser-plugin --force --accept-capabilities || true
    openclaw plugins enable browser || true
fi

# 3. Para gateway antes de configurar
pkill -9 -f "openclaw[- ]gateway" 2>/dev/null || true
sleep 2

# 4. Config completa (API key via env var para não ser sobrescrita pelo paste-api-key)
echo "[*] Escrevendo config..."
mkdir -p /root/.openclaw
export NVIDIA_API_KEY="$(echo '__NVIDIA_KEY_B64__' | base64 -d)"
cat > /root/.openclaw/openclaw.json << 'JSONEOF'
{config_json}
JSONEOF

# Valida config
echo "[*] Validando config..."
openclaw config validate || true

# 5. Executar agente
echo "[*] Disparando agente..."
echo '__PROMPT_B64__' | base64 -d > /tmp/missao.txt
# Regras + tarefa vão para arquivo via heredoc com delimitador quoted ('PROMPTEOF'):
# assim aspas, $ e crases no texto são 100% literais e o bash NÃO interpreta nada
cat > /tmp/prompt_final.txt << 'PROMPTEOF'
{tool_rules}

TAREFA:
PROMPTEOF
cat /tmp/missao.txt >> /tmp/prompt_final.txt
PROMPT_FINAL="$(cat /tmp/prompt_final.txt)"

# --code-mode direct = tool surface normal (não Code Mode)
# tools.allow=["group:web"] já está no openclaw.json
{browser_gateway_start}
# Mesmo com falha do agente, registra o código e executa a limpeza do gateway.
set +e
if [ "{use_browser_str}" = "true" ]; then
    # Browser tool requer gateway - roda agent via gateway
    export OPENCLAW_GATEWAY_TOKEN="opencrawl-fleet-token"
    export OPENCLAW_CONFIG_PATH="/root/.openclaw/openclaw.json"
    # Verifica saúde do gateway antes de disparar agent
    echo "[*] Health check do gateway..."
    openclaw health 2>&1 | head -10 || true
    openclaw agent --message "$PROMPT_FINAL" \
        --model nvidia/nemotron-3.5-lightning-30b-a3b \
        --timeout 1800 \
        --verbose on
else
    # Sem browser: modo direto (embutido, mais rápido)
    OPENCLAW_CONFIG_PATH="/root/.openclaw/openclaw.json" openclaw agent exec "$PROMPT_FINAL" \
        --model nvidia/nemotron-3.5-lightning-30b-a3b \
        --code-mode direct \
        --timeout 1800
fi
RC=$?
set -e
echo "AGENTE_EXIT=$RC"
if [ "$RC" -eq 0 ]; then
    echo "MISSAO_OK"
fi

# Para gateway no final
pkill -9 -f "openclaw[- ]gateway" 2>/dev/null || true

exit $RC
"""

SCRIPT_AGENTE_NO_BROWSER = build_script_agente(False)
SCRIPT_AGENTE_WITH_BROWSER = build_script_agente(True)

PROMOTION_GATES_DEFAULTS = {
    # Somente gates realmente calculados ficam na configuração pública.
    "min_success_ratio": 0.7,
}


def gerar_comando_bash(prompt: str, chave_nvidia: str, use_browser: bool = False) -> str:
    prompt_b64 = base64.b64encode(prompt.encode("utf-8")).decode("ascii")
    script = SCRIPT_AGENTE_WITH_BROWSER if use_browser else SCRIPT_AGENTE_NO_BROWSER
    chave_b64 = base64.b64encode(chave_nvidia.encode("utf-8")).decode("ascii")
    return script.replace("__PROMPT_B64__", prompt_b64).replace("__NVIDIA_KEY_B64__", chave_b64)


async def garantir_maquina(
    maquina: str,
    callback_log,
    flags: str = "",
    event_callback=None,
    cancel_path: str | Path | None = None,
) -> None:
    """Garante que a sessão Colab existe, criando se necessário."""
    _validar_nome_maquina(maquina)
    if flags and not re.fullmatch(r"--gpu (t4|l4|a100)", flags):
        raise ValueError("Flags de GPU não permitidas")
    if _cancel_requested(cancel_path):
        raise FleetCancelled(f"Cancelamento solicitado antes de preparar {maquina}")

    await _emit_event(
        event_callback,
        type="machine.state",
        machine=maquina,
        state="PROVISIONING",
        message="Verificando sessão Colab",
    )
    callback_log(f"🔍 Verificando sessão {maquina}...")
    proc = await asyncio.create_subprocess_shell(
        "colab sessions",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await _comunicar_com_timeout(
        proc,
        60,
        "colab sessions",
        cancel_path,
    )
    if proc.returncode != 0:
        detalhe = (stderr or stdout).decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"Falha em colab sessions: {detalhe[-500:]}")
    saida = stdout.decode("utf-8", errors="replace")

    if f"[{maquina.lower()}]" in saida.lower():
        callback_log(f"✅ {maquina} online.")
        return

    if _cancel_requested(cancel_path):
        raise FleetCancelled(f"Cancelamento solicitado antes de criar {maquina}")
    callback_log(f"⚠️ {maquina} offline. Criando instância...")
    cmd = f"colab new -s {maquina} {flags}".strip()
    proc_new = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    saida, _ = await _comunicar_com_timeout(
        proc_new,
        240,
        f"criação de {maquina}",
        cancel_path,
    )
    texto_saida = saida.decode("utf-8", errors="replace")
    for linha in texto_saida.splitlines()[-5:]:
        callback_log(linha)
    if proc_new.returncode != 0:
        raise RuntimeError(f"Falha ao criar {maquina}: {texto_saida[-500:]}")

    callback_log("⏳ Aguardando boot (15s)...")
    for _ in range(15):
        if _cancel_requested(cancel_path):
            raise FleetCancelled(f"Cancelamento solicitado durante boot de {maquina}")
        await asyncio.sleep(1)


async def rodar_maquina(
    maquina: str,
    tarefas: list[dict],
    chave_nvidia: str,
    callback_log,
    use_browser: bool = False,
    event_callback=None,
    cancel_path: str | Path | None = None,
    max_tentativas: int | None = None,
) -> list[dict]:
    """Roda tarefas sequencialmente e emite estados estruturados opcionais."""
    _validar_nome_maquina(maquina)
    if max_tentativas is None:
        # Browser pode executar ações irreversíveis; não repetir por padrão.
        max_tentativas = 1 if use_browser else 2
    if not 1 <= max_tentativas <= 3:
        raise ValueError("max_tentativas deve estar entre 1 e 3")
    if _cancel_requested(cancel_path):
        raise FleetCancelled(f"Cancelamento solicitado antes de iniciar {maquina}")

    await garantir_maquina(
        maquina,
        callback_log,
        event_callback=event_callback,
        cancel_path=cancel_path,
    )
    resultados = []
    houve_falha = False

    for tarefa in tarefas:
        n = tarefa["task"]
        prompt = tarefa["prompt"]
        if _cancel_requested(cancel_path):
            raise FleetCancelled(f"Cancelamento solicitado antes de {maquina} tarefa{n}")

        callback_log(f"  ▶ {maquina} tarefa{n} iniciada.")
        script = gerar_comando_bash(prompt, chave_nvidia, use_browser)
        resultado = None

        for tentativa in range(1, max_tentativas + 1):
            proc = None
            estado = "RUNNING" if tentativa == 1 else "RETRYING"
            await _emit_event(
                event_callback,
                type="machine.state",
                machine=maquina,
                state=estado,
                task=n,
            )
            await _emit_event(
                event_callback,
                type="task.state",
                machine=maquina,
                task=n,
                attempt=tentativa,
                state=estado,
            )
            if tentativa > 1:
                callback_log(f"     🔁 Nova tentativa {tentativa}/{max_tentativas} da tarefa{n}...")

            try:
                if _cancel_requested(cancel_path):
                    raise FleetCancelled(f"Cancelamento solicitado em {maquina} tarefa{n}")
                proc = await asyncio.create_subprocess_shell(
                    f"colab ssh -s {maquina}",
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                )
                proc.stdin.write(script.encode("utf-8"))
                proc.stdin.close()

                saida_lines = []
                while True:
                    if _cancel_requested(cancel_path):
                        raise FleetCancelled(f"Cancelamento solicitado em {maquina} tarefa{n}")
                    try:
                        linha = await asyncio.wait_for(proc.stdout.readline(), timeout=1)
                    except asyncio.TimeoutError:
                        continue
                    if not linha:
                        break
                    texto = linha.decode("utf-8", errors="replace").rstrip()
                    saida_lines.append(texto)
                    callback_log(f"     {texto}")

                await proc.wait()
                saida = "\n".join(saida_lines)
                sucesso = proc.returncode == 0 and "MISSAO_OK" in saida
                callback_log(f"     {'✅' if sucesso else '❌'} {maquina} tarefa{n} {'ok' if sucesso else 'falhou'}")

                resultado = {
                    "maquina": maquina,
                    "task": n,
                    "prompt": prompt,
                    "sucesso": sucesso,
                    "saida_bruta": saida[-2000:],
                    "saida_completa": saida,
                    "timestamp": time.time(),
                    "tentativas": tentativa,
                }
                if sucesso:
                    break

            except FleetCancelled:
                await _emit_event(
                    event_callback,
                    type="machine.state",
                    machine=maquina,
                    state="CANCELLING",
                    task=n,
                )
                if proc is not None:
                    await _encerrar_processo(proc)
                try:
                    await _limpar_processos_remotos(maquina, callback_log)
                except Exception as exc:
                    callback_log(f"⚠️ {maquina}: falha na limpeza remota: {exc}")
                await _emit_event(
                    event_callback,
                    type="task.state",
                    machine=maquina,
                    task=n,
                    attempt=tentativa,
                    state="CANCELLED",
                )
                await _emit_event(
                    event_callback,
                    type="machine.state",
                    machine=maquina,
                    state="CANCELLED",
                    task=n,
                )
                raise
            except Exception as e:
                if proc is not None:
                    await _encerrar_processo(proc)
                callback_log(f"     ❌ {maquina} tarefa{n} erro: {e}")
                resultado = {
                    "maquina": maquina,
                    "task": n,
                    "prompt": prompt,
                    "sucesso": False,
                    "erro": str(e),
                    "timestamp": time.time(),
                    "tentativas": tentativa,
                }

        if resultado is not None:
            resultados.append(resultado)
            sucesso = bool(resultado.get("sucesso"))
            houve_falha = houve_falha or not sucesso
            await _emit_event(
                event_callback,
                type="task.state",
                machine=maquina,
                task=n,
                attempt=resultado.get("tentativas", max_tentativas),
                state="COMPLETED" if sucesso else "FAILED",
                message=resultado.get("erro"),
            )

    await _emit_event(
        event_callback,
        type="machine.state",
        machine=maquina,
        state="FAILED" if houve_falha else "COMPLETED",
    )
    return resultados


def aplicar_gates(resultados: list[dict], gates: dict) -> dict:
    """Aplica promotion gates aos resultados agregados."""
    sucessos = [r for r in resultados if r.get("sucesso")]
    total = len(resultados)
    ok = len(sucessos)

    min_ratio = gates.get("min_success_ratio", 0.7)
    # Use ceil to ensure we meet the minimum ratio
    min_required = max(1, math.ceil(total * min_ratio))
    gate_pass = ok >= min_required

    return {
        "total_tasks": total,
        "successful": ok,
        "gate_pass": gate_pass,
        "gates_config": gates,
        "details": {
            "min_success_ratio": min_ratio,
            "actual_ratio": ok / total if total > 0 else 0,
            "min_required": min_required,
        },
    }


def render_summary(resultados: list[dict], gates_result: dict, request: str) -> str:
    """Gera markdown summary."""
    lines = [
        f"# Fleet Run Summary",
        f"",
        f"**Request:** {request}",
        f"**Timestamp:** {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"",
        f"## Gates: {'✅ PASS' if gates_result['gate_pass'] else '❌ FAIL'}",
        f"- Total tasks: {gates_result['total_tasks']}",
        f"- Successful: {gates_result['successful']}",
        f"- Success ratio: {gates_result['details']['actual_ratio']:.1%} "
        f"(min {gates_result['details']['min_success_ratio']:.0%})",
        f"",
        f"## Per-Machine Results",
    ]

    by_machine = {}
    for r in resultados:
        by_machine.setdefault(r["maquina"], []).append(r)

    for maquina in sorted(by_machine):
        tasks = by_machine[maquina]
        ok = sum(1 for t in tasks if t.get("sucesso"))
        lines.append(f"### {maquina}: {ok}/{len(tasks)} ok")
        for t in tasks:
            status = "✅" if t.get("sucesso") else "❌"
            lines.append(f"  - {status} tarefa{t.get('task', '?')}: {t.get('prompt', '')[:60]}...")

    return "\n".join(lines)


async def main_async(args):
    # Carrega plan
    with open(args.plan, "r", encoding="utf-8") as f:
        plan = json.load(f)

    # Valida
    sys.path.insert(0, str(Path(__file__).parent))
    from validate_fleet_plan import validar_plano_json
    ok, erros = validar_plano_json(plan, plan.get("request", ""), args.browser)
    if not ok:
        sys.exit("❌ Plan inválido:\n" + "\n".join(f"  - {e}" for e in erros))

    # Agrupa por máquina
    by_cpu = {}
    for t in plan["tasks"]:
        by_cpu.setdefault(t["cpu"], []).append(t)

    maquinas = [f"cpu{cpu}" for cpu in sorted(by_cpu.keys())]
    tarefas_por_maquina = {f"cpu{cpu}": tarefas for cpu, tarefas in by_cpu.items()}

    # Chave NVIDIA
    chave = os.getenv("NVIDIA_API_KEY")
    if not chave:
        sys.exit("❌ NVIDIA_API_KEY não definida no ambiente")

    # Confirmação humana (se não --auto-confirm)
    if not args.auto_confirm:
        print("\n📋 Plano a executar:")
        for maquina in maquinas:
            for t in tarefas_por_maquina[maquina]:
                print(f"  [{maquina}] [tarefa{t['task']}] {t['prompt'][:80]}...")
        resp = input(f"\nLançar {len(maquinas)} máquina(s)? [continuar/cancelar]: ").strip().lower()
        if resp not in ("continuar", "sim", "s", "y", "yes"):
            print("🛑 Cancelado pelo usuário")
            return

    # Execução com pipeline stagger
    print(f"\n🚀 Iniciando fleet em {len(maquinas)} máquina(s) com pipeline 60s...")
    all_results = []

    with ThreadPoolExecutor(max_workers=len(maquinas)) as executor:
        loop = asyncio.get_event_loop()
        futures = {}

        for i, maquina in enumerate(maquinas):
            if i > 0:
                print(f"⏳ Aguardando 60s antes de {maquina} (pipeline stagger)...")
                await asyncio.sleep(60)

            tarefas = tarefas_por_maquina[maquina]
            futures[maquina] = loop.run_in_executor(
                executor,
                lambda m=maquina, t=tarefas: asyncio.run(
                    rodar_maquina(m, t, chave, print, use_browser=args.browser)
                ),
            )

        for maquina, fut in futures.items():
            try:
                resultados = await fut
                all_results.extend(resultados)
            except Exception as e:
                print(f"❌ {maquina} falhou: {e}")
                all_results.append({
                    "maquina": maquina,
                    "task": 0,
                    "prompt": "",
                    "sucesso": False,
                    "erro": str(e),
                    "timestamp": time.time(),
                })

    # Gates + Summary
    gates = {**PROMOTION_GATES_DEFAULTS, **(args.gates or {})}
    gates_result = aplicar_gates(all_results, gates)
    summary_md = render_summary(all_results, gates_result, plan.get("request", ""))

    # Outputs
    out_base = Path(args.out).with_suffix("")
    out_base.parent.mkdir(parents=True, exist_ok=True)

    # JSONL results
    with open(f"{out_base}.jsonl", "w", encoding="utf-8") as f:
        for r in all_results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # Gates result
    with open(f"{out_base}_gates.json", "w", encoding="utf-8") as f:
        json.dump(gates_result, f, ensure_ascii=False, indent=2)

    # Markdown summary
    with open(f"{out_base}_summary.md", "w", encoding="utf-8") as f:
        f.write(summary_md)

    print(f"\n📊 Resultados salvos em:")
    print(f"  {out_base}.jsonl")
    print(f"  {out_base}_gates.json")
    print(f"  {out_base}_summary.md")
    print(f"\n{summary_md}")

    if not gates_result["gate_pass"]:
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Executa fleet plan no Colab")
    parser.add_argument("--plan", required=True, help="fleet-plan.json validado")
    parser.add_argument("--out", required=True, help="Base path para outputs (ex: /tmp/run)")
    parser.add_argument("--auto-confirm", action="store_true", help="Pula confirmação humana")
    parser.add_argument("--browser", action="store_true", help="Habilita browser tool nos executores")
    parser.add_argument("--gates", type=json.loads, default="{}", help="JSON com gates customizados")
    args = parser.parse_args()

    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()