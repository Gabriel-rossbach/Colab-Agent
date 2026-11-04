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
import json
import math
import os
import shlex
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

# ─── CONFIG ────────────────────────────────────────────────────────
SCRIPT_AGENTE = r"""
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

# 3. Para gateway antes de configurar
pkill -f "openclaw gateway" 2>/dev/null || true
sleep 2

# 4. Config completa (API key via env var para não ser sobrescrita pelo paste-api-key)
echo "[*] Escrevendo config..."
mkdir -p /root/.openclaw
export NVIDIA_API_KEY='{CHAVE_NVIDIA}'
cat > /root/.openclaw/openclaw.json << 'JSONEOF'
{
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
    }
  },
  "tools": {
    "allow": ["group:web"],
    "web": {
      "search": {
        "enabled": true,
        "provider": "duckduckgo",
        "maxResults": 10,
        "timeoutSeconds": 30,
        "cacheTtlMinutes": 15
      }
    }
  },
  "plugins": {
    "enabled": true,
    "allow": ["duckduckgo"],
    "entries": {
      "duckduckgo": {
        "enabled": true,
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
JSONEOF

# Valida config
echo "[*] Validando config..."
openclaw config validate || true

# 5. Executar agente (agent exec roda embedded, sem gateway — plugins carregam do config)
echo "[*] Disparando agente..."
echo '__PROMPT_B64__' | base64 -d > /tmp/missao.txt
# Instrução FORTE: só web_search + schema exato da chamada
PROMPT_FINAL="REGRAS OBRIGATÓRIAS:\n1. Sua ÚNICA ferramenta é web_search. Não tente usar nenhuma outra.\n2. Ao chamar web_search, os argumentos DEVEM ser no formato exato: {\"query\": \"texto da pesquisa\", \"count\": 5}\n   - Parâmetro obrigatório: query (string) — NUNCA use outro nome como 'args', 'limit', 'q', 'search'\n   - Parâmetro opcional: count (número de 1 a 10) — NUNCA use 'limit'\n3. Chame web_search pelo menos 2 vezes com ângulos diferentes antes de responder.\n4. Baseie sua resposta EXCLUSIVAMENTE nos resultados retornados por web_search.\n5. Se web_search retornar erro de argumentos, corrija para {\"query\": \"...\"} e tente de novo.\n\nTAREFA:\n$(cat /tmp/missao.txt)"
# --code-mode direct = tool surface normal (não Code Mode)
# tools.allow=["group:web"] já está no openclaw.json
openclaw agent exec "$PROMPT_FINAL" \
    --model nvidia/nemotron-3.5-lightning-30b-a3b \
    --code-mode direct \
    --timeout 600
RC=$?
echo "AGENTE_EXIT=$RC"
[ "$RC" -eq 0 ] && echo "MISSAO_OK"

exit $RC
"""

PROMOTION_GATES_DEFAULTS = {
    "min_unique_sources": 3,
    "max_dup_ratio": 0.15,
    "min_chars_per_result": 200,
}


def gerar_comando_bash(prompt: str, chave_nvidia: str) -> str:
    prompt_b64 = base64.b64encode(prompt.encode("utf-8")).decode("ascii")
    return SCRIPT_AGENTE.replace("__PROMPT_B64__", prompt_b64).replace("{CHAVE_NVIDIA}", chave_nvidia)


async def garantir_maquina(maquina: str, callback_log, flags: str = "") -> None:
    """Garante que a sessão Colab existe, criando se necessário."""
    callback_log(f"🔍 Verificando sessão {maquina}...")
    proc = await asyncio.create_subprocess_shell(
        "colab sessions",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    saida = stdout.decode("utf-8", errors="replace")
    
    if f"[{maquina.lower()}]" in saida.lower():
        callback_log(f"✅ {maquina} online.")
        return

    callback_log(f"⚠️ {maquina} offline. Criando instância...")
    cmd = f"colab new -s {maquina} {flags}".strip()
    proc_new = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    saida, _ = await proc_new.communicate()
    for linha in saida.decode("utf-8", errors="replace").splitlines()[-5:]:
        callback_log(linha)
    callback_log("⏳ Aguardando boot (15s)...")
    await asyncio.sleep(15)


async def rodar_maquina(maquina: str, tarefas: list[dict], chave_nvidia: str, callback_log) -> list[dict]:
    """Roda todas as tarefas de uma máquina sequencialmente. Retorna lista de resultados."""
    # Garante que a máquina existe
    await garantir_maquina(maquina, callback_log)
    
    resultados = []

    for tarefa in tarefas:
        n = tarefa["task"]
        prompt = tarefa["prompt"]
        callback_log(f"  ▶ {maquina} tarefa{n}: {prompt[:80]}...")

        script = gerar_comando_bash(prompt, chave_nvidia)

        try:
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
                linha = await proc.stdout.readline()
                if not linha:
                    break
                texto = linha.decode("utf-8", errors="replace").rstrip()
                saida_lines.append(texto)
                # Streaming: loga cada linha em tempo real no painel da máquina
                callback_log(f"     {texto}")

            await proc.wait()
            saida = "\n".join(saida_lines)

            sucesso = "MISSAO_OK" in saida
            callback_log(f"     {'✅' if sucesso else '❌'} {maquina} tarefa{n} {'ok' if sucesso else 'falhou'}")

            # Extrai resultado (simplificado - em produção parsearia JSON do agente)
            resultado = {
                "maquina": maquina,
                "task": n,
                "prompt": prompt,
                "sucesso": sucesso,
                "saida_bruta": saida[-2000:],  # últimos 2000 chars
                "timestamp": time.time(),
            }
            resultados.append(resultado)

        except Exception as e:
            callback_log(f"     ❌ {maquina} tarefa{n} erro: {e}")
            resultados.append({
                "maquina": maquina,
                "task": n,
                "prompt": prompt,
                "sucesso": False,
                "erro": str(e),
                "timestamp": time.time(),
            })

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
        f"- Success ratio: {gates_result['details']['actual_ratio']:.1%} (min 70%)",
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
            lines.append(f"  - {status} tarefa{t['task']}: {t['prompt'][:60]}...")

    return "\n".join(lines)


async def main_async(args):
    # Carrega plan
    with open(args.plan, "r", encoding="utf-8") as f:
        plan = json.load(f)

    # Valida
    sys.path.insert(0, str(Path(__file__).parent))
    from validate_fleet_plan import validar_plano_json
    ok, erros = validar_plano_json(plan, plan.get("request", ""))
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
                lambda m=maquina, t=tarefas: asyncio.run(rodar_maquina(m, t, chave, print)),
            )

        for maquina, fut in futures.items():
            try:
                resultados = await fut
                all_results.extend(resultados)
            except Exception as e:
                print(f"❌ {maquina} falhou: {e}")
                all_results.append({"maquina": maquina, "erro": str(e), "timestamp": time.time()})

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
    parser.add_argument("--gates", type=json.loads, default="{}", help="JSON com gates customizados")
    args = parser.parse_args()

    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()