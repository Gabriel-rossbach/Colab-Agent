#!/usr/bin/env python3
"""
Gera fleet plan JSON válido a partir de pedido em linguagem natural.
Usa Ollama local (gpt-oss:20b) ou endpoint OpenAI-compatível.
Pode rodar o planner em máquina remota Colab (ex: cpu6 GPU) via SSH.
"""

import argparse
import asyncio
import base64
import json
import os
import re
import sys
import subprocess
from pathlib import Path
from typing import Any, Optional


class PlannerCancelled(Exception):
    """Planejamento cancelado cooperativamente pelo orquestrador."""


def _cancel_requested(cancel_path: str | Path | None) -> bool:
    return cancel_path is not None and Path(cancel_path).exists()


def _validar_nome_maquina(maquina: str) -> None:
    if not re.fullmatch(r"cpu[1-6]", maquina):
        raise ValueError(f"Nome de máquina inválido: {maquina!r}")


def _validar_flags_gpu(flags: str) -> None:
    if flags and not re.fullmatch(r"--gpu (t4|l4|a100)", flags):
        raise ValueError("Flags de GPU permitidas: --gpu t4, --gpu l4 ou --gpu a100")


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
                raise PlannerCancelled(f"Cancelamento solicitado em {descricao}")
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


async def _limpar_planner_remoto(maquina: str, callback_log=None) -> None:
    """Melhor esforço: encerra o planejamento remoto sem desligar a sessão."""
    if callback_log:
        callback_log(f"🧹 {maquina}: encerrando planejamento remoto após cancelamento...")
    proc = await asyncio.create_subprocess_shell(
        f"colab ssh -s {maquina}",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    proc.stdin.write(
        b'pkill -f "ollama serve" 2>/dev/null || true\n'
        b'pkill -f "ollama pull" 2>/dev/null || true\n'
        b"exit\n"
    )
    proc.stdin.close()
    try:
        await asyncio.wait_for(proc.wait(), timeout=15)
    except asyncio.TimeoutError:
        await _encerrar_processo(proc)


# Reuse validation logic
sys.path.insert(0, str(Path(__file__).parent))
from validate_fleet_plan import (
    validar_plano_json,
    etiquetas_esperadas,
    MAX_MAQUINAS,
    MAX_POR_MAQUINA,
    MAX_TAREFAS,
)

# ─── PLANNER SKILL (prompt de sistema) ────────────────────────────
SKILL_PLANEJADOR = """\
Você é um planejador. Recebe um pedido e devolve uma lista de tarefas no formato:
[cpuN] [tarefaK] prompt

Regras:
- Máquinas: cpu1 a cpu5 (cpu6 é GPU do planner, NÃO use para tarefas)
- Máximo 2 tarefas por máquina (tarefa1, tarefa2)
- Distribua equilibrado: 1 tarefa → cpu1; 2-4 tarefas → cpu1 e cpu2; 5+ → cpu1, cpu2, cpu3...
- Cada prompt: "Use web_search para pesquisar [o que o pedido pediu]. Traga em português."
- Se pedir browser/login/screenshot: "Use browser para [ação específica]."
- IMPORTANTE: Cada tarefa deve ter um QUERY DIFERENTE. Se o pedido pede "5 plugins", crie ângulos diferentes:
  * tarefa1: "plugins de navegação para OpenClaw"
  * tarefa2: "extensões de navegação OpenClaw disponíveis"
  * tarefa3: "como instalar plugins no OpenClaw"
  * tarefa4: "melhores plugins OpenClaw para navegação web"
- Responda SÓ com as linhas de tarefas. Sem introdução, markdown ou explicação.

Exemplo:
Pedido: pesquisa 5 carros rápidos e 5 motos rápidas
[cpu1] [tarefa1] Use web_search para pesquisar os 5 carros mais rápidos. Traga em português.
[cpu2] [tarefa1] Use web_search para pesquisar as 5 motos mais rápidas. Traga em português.

Exemplo 2 (uma categoria, vários ângulos):
Pedido: pesquise 5 plugins de navegação para OpenClaw
[cpu1] [tarefa1] Use web_search para pesquisar plugins de navegação para OpenClaw. Traga em português.
[cpu1] [tarefa2] Use web_search para pesquisar extensões de navegação OpenClaw disponíveis. Traga em português.
[cpu2] [tarefa1] Use web_search para pesquisar como instalar plugins no OpenClaw. Traga em português.
[cpu2] [tarefa2] Use web_search para pesquisar melhores plugins OpenClaw para navegação web. Traga em português.
"""

# ─── SCRIPT PLANNER REMOTO (para rodar no cpu6 via SSH) ───────────────
SCRIPT_PLANNER_REMOTO = r"""
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


def montar_mensagens(pedido: str, browser_enabled: bool = True) -> list[dict]:
    disponibilidade = (
        "Browser HABILITADO: pode criar tarefas 'Use browser para ...' quando a ação exigir página real, login, formulário ou captura."
        if browser_enabled
        else "Browser DESABILITADO nesta run: não crie tarefas com browser/login/screenshot; use somente web_search."
    )
    return [
        {"role": "system", "content": SKILL_PLANEJADOR},
        {"role": "user", "content": f"Pedido:\n{pedido}\n\n{disponibilidade}"},
    ]


def extrair_linhas(texto: str) -> list[str]:
    linhas = []
    for bruta in texto.splitlines():
        linha = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s+", "", bruta.strip())
        if linha and not linha.startswith("```"):
            linhas.append(linha)
    return linhas


def parse_linhas(linhas: list[str]) -> list[dict]:
    """Converte linhas [cpuN] [tarefaK] prompt → lista de dicts."""
    PADRAO = re.compile(r"^\[cpu(\d+)\]\s*\[tarefa(\d+)\]\s*(\S.*)$", re.IGNORECASE)
    tarefas = []
    for linha in linhas:
        m = PADRAO.match(linha)
        if not m:
            continue
        tarefas.append({
            "cpu": int(m.group(1)),
            "task": int(m.group(2)),
            "prompt": m.group(3).strip(),
        })
    return tarefas


def chamar_ollama(mensagens: list[dict], modelo: str = "gpt-oss:20b") -> str | None:
    """Chama Ollama local e retorna texto da resposta."""
    payload = {
        "model": modelo,
        "messages": mensagens,
        "stream": False,
        "options": {"temperature": 0.2, "num_ctx": 4096, "num_predict": 4096},
    }
    if modelo.startswith("gpt-oss"):
        payload["think"] = "low"

    try:
        import urllib.request
        import urllib.error

        req = urllib.request.Request(
            "http://localhost:11434/api/chat",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = json.load(resp)
            return data.get("message", {}).get("content", "")
    except urllib.error.HTTPError as e:
        print(f"❌ Ollama HTTP {e.code}: {e.read().decode('utf-8', errors='replace')}", file=sys.stderr)
    except Exception as e:
        print(f"❌ Erro chamando Ollama: {e}", file=sys.stderr)
    return None


async def garantir_maquina_remota(
    maquina: str,
    callback_log=None,
    flags: str = "",
    cancel_path: str | Path | None = None,
) -> None:
    """Garante que a sessão Colab existe, criando se necessário."""
    _validar_nome_maquina(maquina)
    _validar_flags_gpu(flags)
    if _cancel_requested(cancel_path):
        raise PlannerCancelled("Cancelamento solicitado antes de preparar o planner")
    if callback_log:
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
        if callback_log:
            callback_log(f"✅ {maquina} online.")
        return

    if _cancel_requested(cancel_path):
        raise PlannerCancelled("Cancelamento solicitado antes de criar o planner")
    if callback_log:
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
    if proc_new.returncode != 0:
        raise RuntimeError(f"Falha ao criar {maquina}: {texto_saida[-500:]}")
    for linha in texto_saida.splitlines()[-5:]:
        if callback_log:
            callback_log(linha)

    if callback_log:
        callback_log("⏳ Aguardando boot (15s)...")
    for _ in range(15):
        if _cancel_requested(cancel_path):
            raise PlannerCancelled("Cancelamento solicitado durante boot do planner")
        await asyncio.sleep(1)


async def chamar_ollama_remoto(
    maquina: str,
    mensagens: list[dict],
    modelo: str = "gpt-oss:20b",
    callback_log=None,
    flags_gpu: str = "",
    cancel_path: str | Path | None = None,
) -> str | None:
    """Chama Ollama em máquina Colab remota via SSH e retorna texto da resposta."""
    _validar_nome_maquina(maquina)
    _validar_flags_gpu(flags_gpu)
    if _cancel_requested(cancel_path):
        raise PlannerCancelled("Cancelamento solicitado antes da chamada remota")
    # Prepara requisição
    requisicao = {
        "model": modelo,
        "messages": mensagens,
        "stream": False,
        "options": {"temperature": 0.2, "num_ctx": 4096, "num_predict": 4096},
    }
    if modelo.startswith("gpt-oss"):
        requisicao["think"] = "low"
    req_b64 = base64.b64encode(
        json.dumps(requisicao, ensure_ascii=False).encode("utf-8")
    ).decode("ascii")

    # Gera script
    script = (
        SCRIPT_PLANNER_REMOTO
        .replace("__MODELO__", modelo)
        .replace("__REQ_B64__", req_b64)
    )

    # Garante que a máquina existe (cria se necessário)
    await garantir_maquina_remota(
        maquina,
        flags=flags_gpu,
        callback_log=callback_log,
        cancel_path=cancel_path,
    )

    if callback_log:
        callback_log(f"🔗 Conectando em {maquina} para planejamento...")

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
    plano_b64 = None
    while True:
        if _cancel_requested(cancel_path):
            await _encerrar_processo(proc)
            try:
                await _limpar_planner_remoto(maquina, callback_log)
            except Exception as exc:
                if callback_log:
                    callback_log(f"⚠️ {maquina}: falha na limpeza do planner: {exc}")
            raise PlannerCancelled("Cancelamento solicitado durante o planejamento remoto")
        try:
            linha = await asyncio.wait_for(proc.stdout.readline(), timeout=1)
        except asyncio.TimeoutError:
            continue
        if not linha:
            break
        texto = linha.decode("utf-8", errors="replace").rstrip()
        linhas.append(texto)

        if texto == "PLANO_B64_INICIO":
            escondendo = True
        if not escondendo and callback_log:
            callback_log(f"   [{maquina}] {texto}")
        if texto == "PLANO_B64_FIM":
            escondendo = False

    await proc.wait()

    # Extrai plano base64 das linhas
    capturando = False
    for linha in linhas:
        if linha == "PLANO_B64_INICIO":
            capturando = True
            continue
        if linha == "PLANO_B64_FIM":
            break
        if capturando and plano_b64 is None:
            plano_b64 = linha.strip()

    if plano_b64:
        try:
            return base64.b64decode(plano_b64).decode("utf-8")
        except Exception as e:
            if callback_log:
                callback_log(f"❌ Erro decodificando plano: {e}")
    return None


def gerar_plano(
    pedido: str,
    modelo: str,
    max_tentativas: int = 4,
    planner_machine: Optional[str] = None,
    callback_log=None,
    flags_gpu: str = "",
    browser_enabled: bool = True,
    cancel_path: str | Path | None = None,
) -> dict | None:
    """
    Gera plano válido.
    
    Args:
        pedido: Pedido em linguagem natural
        modelo: Modelo Ollama (ex: gpt-oss:20b)
        max_tentativas: Tentativas de correção
        planner_machine: Se None, usa Ollama local. Se "cpu6", usa SSH remoto.
        callback_log: Função de log opcional (para uso remoto)
        flags_gpu: Flags para criação da máquina GPU (ex: "--gpu t4")
    """
    mensagens = montar_mensagens(pedido, browser_enabled)
    _validar_flags_gpu(flags_gpu)

    for tentativa in range(1, max_tentativas + 1):
        if _cancel_requested(cancel_path):
            raise PlannerCancelled("Cancelamento solicitado antes da próxima tentativa do planner")
        if callback_log:
            callback_log(f"🧠 Tentativa {tentativa}/{max_tentativas} com {modelo}...")
        else:
            print(f"🧠 Tentativa {tentativa}/{max_tentativas} com {modelo}...", file=sys.stderr)

        if planner_machine:
            # Modo remoto: roda no cpu6 via SSH
            resposta = asyncio.run(
                chamar_ollama_remoto(
                    planner_machine,
                    mensagens,
                    modelo,
                    callback_log,
                    flags_gpu,
                    cancel_path,
                )
            )
        else:
            # Modo local: chama Ollama em localhost
            resposta = chamar_ollama(mensagens, modelo)

        if not resposta:
            continue

        if callback_log:
            callback_log("📄 Resposta do modelo:")
            for linha in resposta.splitlines():
                callback_log(f"   {linha}")
        else:
            print("📄 Resposta do modelo:", file=sys.stderr)
            for linha in resposta.splitlines():
                print(f"   {linha}", file=sys.stderr)

        linhas = extrair_linhas(resposta)
        tarefas = parse_linhas(linhas)

        if not tarefas:
            msg = "⚠️ Nenhuma tarefa parseada da resposta"
            if callback_log:
                callback_log(msg)
            else:
                print(msg, file=sys.stderr)
            continue

        plan = {"request": pedido, "tasks": tarefas}
        ok, erros = validar_plano_json(plan, pedido, browser_enabled)

        if ok:
            total = len(tarefas)
            msg = f"✅ Plan válido: {total} tarefa(s) em {len(set(t['cpu'] for t in tarefas))} máquina(s)"
            if callback_log:
                callback_log(msg)
            else:
                print(msg, file=sys.stderr)
            return plan

        msg = "⚠️ Plan inválido:"
        if callback_log:
            callback_log(msg)
            for e in erros:
                callback_log(f"   - {e}")
        else:
            print(msg, file=sys.stderr)
            for e in erros:
                print(f"   - {e}", file=sys.stderr)

        # Feedback pro modelo corrigir com exemplo de distribuição correta
        total_tarefas = len(tarefas)
        esperadas = etiquetas_esperadas(total_tarefas)
        exemplo = ", ".join(f"[cpu{c}] [tarefa{t}]" for c, t in esperadas)
        
        mensagens.append({"role": "assistant", "content": resposta})
        mensagens.append({"role": "user", "content": 
            f"Corrija o plano. Erros:\n" + "\n".join(f"- {e}" for e in erros) +
            f"\n\nLembre-se: para {total_tarefas} tarefas, use EXATAMENTE estas etiquetas na ordem:\n{exemplo}\n" +
            f"- Máximo 2 tarefas por máquina (tarefa1, tarefa2)\n" +
            f"- Máquinas em ordem: cpu1, cpu2, cpu3... (sem pular)\n" +
            f"- Não repita prompts\n" +
            f"- Uma tarefa por categoria pedida"})

    return None


def main():
    parser = argparse.ArgumentParser(description="Gera fleet plan JSON a partir de linguagem natural")
    parser.add_argument("--out", required=True, help="Arquivo de saída (ex: /tmp/fleet-plan.json)")
    parser.add_argument("--request", required=True, help="Pedido em linguagem natural")
    parser.add_argument("--model", default=os.getenv("MODELO_PLANEJADOR", "gpt-oss:20b"), help="Modelo Ollama")
    parser.add_argument("--max-tentativas", type=int, default=2)
    parser.add_argument("--planner-machine", help="Máquina Colab para rodar planner (ex: cpu6). Se omitido, usa Ollama local.")
    parser.add_argument("--flags-gpu", default=os.getenv("FLAGS_GPU", "--gpu t4"), help="Flags GPU para criar planner machine (ex: --gpu t4)")
    args = parser.parse_args()

    plan = gerar_plano(args.request, args.model, args.max_tentativas, args.planner_machine, flags_gpu=args.flags_gpu)
    if not plan:
        sys.exit("❌ Falha ao gerar plan válido após todas as tentativas")

    # Garante diretório
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)

    print(f"📄 Plan salvo em {args.out}")
    print(json.dumps(plan, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()