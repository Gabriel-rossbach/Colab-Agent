#!/usr/bin/env python3
"""
Validador de fleet plan — standalone, usado em CI e por outros scripts.
Portado de plano.py validar_plano() com adaptações para fleet JSON.
"""

import json
import re
import difflib
import sys
from pathlib import Path
from typing import Any

# ─── CONSTANTES ────────────────────────────────────────────────────
MAX_MAQUINAS = 5
MAX_POR_MAQUINA = 2
MAX_TAREFAS = MAX_MAQUINAS * MAX_POR_MAQUINA  # 10
MIN_CARACTERES = 40
LIMIAR_QUASE_IGUAL = 0.985
PALAVRAS_EXTRAS = ("segurança", "seguranca", "seguro", "cuidado")

PADRAO_LINHA = re.compile(r"^\[cpu(\d+)\]\s*\[tarefa(\d+)\]\s*(\S.*)$", re.IGNORECASE)
PADRAO_ASPAS = re.compile(r'"([^"]{2,40})"')


def _rotulo(cpu: int, k: int) -> str:
    return f"[cpu{cpu}] [tarefa{k}]"


def _normalizar(texto: str) -> str:
    return re.sub(r"\s+", " ", texto.lower()).strip()


def etiquetas_esperadas(total: int) -> list[tuple[int, int]]:
    """Etiquetas certas para N tarefas na ordem de execução."""
    if total <= 0:
        return []
    if total == 1:
        maquinas = 1
    elif total <= 4:
        maquinas = 2
    else:
        maquinas = -(-total // MAX_POR_MAQUINA)  # teto
    base, sobra = divmod(total, maquinas)
    tamanhos = [base + 1] * sobra + [base] * (maquinas - sobra)
    return [(cpu, k) for cpu, tamanho in enumerate(tamanhos, start=1) for k in range(1, tamanho + 1)]


def validar_plano_json(plan: dict[str, Any], request: str = "") -> tuple[bool, list[str]]:
    """
    Valida um fleet plan JSON.
    Espera: {"tasks": [{"cpu": 1, "task": 1, "prompt": "..."}, ...], ...}
    """
    erros = []

    # Estrutura básica
    if "tasks" not in plan:
        erros.append("campo 'tasks' ausente no plan")
        return False, erros

    tasks = plan["tasks"]
    if not isinstance(tasks, list):
        erros.append("'tasks' deve ser uma lista")
        return False, erros

    total = len(tasks)
    if total == 0:
        erros.append("plan vazio: nenhuma tarefa")
        return False, erros
    if total > MAX_TAREFAS:
        erros.append(f"máximo {MAX_TAREFAS} tarefas; recebido {total}")

    # Validar cada tarefa
    recebidas = []
    for i, t in enumerate(tasks):
        if not isinstance(t, dict):
            erros.append(f"tarefa {i}: deve ser objeto")
            continue
        cpu = t.get("cpu")
        task_num = t.get("task")
        prompt = t.get("prompt", "").strip()

        if not isinstance(cpu, int) or not 1 <= cpu <= MAX_MAQUINAS:
            erros.append(f"{_rotulo(cpu, task_num)}: cpu{cpu} não existe; use só de cpu1 a cpu{MAX_MAQUINAS}")
            continue
        if not isinstance(task_num, int) or not 1 <= task_num <= MAX_POR_MAQUINA:
            erros.append(
                f"{_rotulo(cpu, task_num)}: a numeração recomeça em 1 em cada máquina; "
                f"cada máquina tem só tarefa1 e tarefa{MAX_POR_MAQUINA}"
            )
            continue
        if len(prompt) < MIN_CARACTERES:
            erros.append(f"{_rotulo(cpu, task_num)}: prompt curto demais ({len(prompt)} < {MIN_CARACTERES})")
        # Tarefas de browser usam browser tool, não web_search
        is_browser = any(kw in prompt.lower() for kw in ("browser", "navegador", "chromium", "playwright", "screenshot", "login", "formulário", "clicar", "clique"))
        if "web_search" not in prompt.lower() and not is_browser:
            erros.append(f"{_rotulo(cpu, task_num)}: o prompt não manda usar web_search nem browser")
        # Also check for "Web_search" or "WEB_SEARCH" variants
        # (already covered by .lower())

        recebidas.append((cpu, task_num, prompt))

    if not recebidas:
        return False, erros

    # Duplicatas de etiqueta
    vistos = set()
    for cpu, k, _ in recebidas:
        if (cpu, k) in vistos:
            erros.append(f"{_rotulo(cpu, k)} aparece mais de uma vez")
        vistos.add((cpu, k))

    # Etiquetas esperadas para este total
    if total <= MAX_TAREFAS:
        esperadas = etiquetas_esperadas(total)
        if sorted(vistos) != sorted(esperadas):
            certas = ", ".join(_rotulo(c, k) for c, k in esperadas)
            erros.append(f"as etiquetas não batem com {total} tarefas. Use exatamente estas: {certas}")

    # Regras de prompt
    request_lower = request.lower()
    request_sem_aspas = bool(request.strip()) and '"' not in request
    for cpu, k, prompt in recebidas:
        rot = _rotulo(cpu, k)
        if request_sem_aspas and PADRAO_ASPAS.search(prompt):
            erros.append(f"{rot}: colocou um nome entre aspas que o pedido não trouxe (nome inventado)")
        for palavra in PALAVRAS_EXTRAS:
            if palavra in prompt.lower() and palavra not in request_lower:
                erros.append(f"{rot}: acrescentou '{palavra}', que o pedido não trouxe")
                break

    # Quase-duplicatas
    for i in range(len(recebidas)):
        for j in range(i):
            cpu_a, k_a, prompt_a = recebidas[j]
            cpu_b, k_b, prompt_b = recebidas[i]
            a, b = _normalizar(prompt_a), _normalizar(prompt_b)
            if a == b:
                erros.append(f"{_rotulo(cpu_b, k_b)} repete exatamente {_rotulo(cpu_a, k_a)}")
            elif difflib.SequenceMatcher(None, a, b).ratio() >= LIMIAR_QUASE_IGUAL:
                erros.append(f"{_rotulo(cpu_b, k_b)} quase igual a {_rotulo(cpu_a, k_a)}; mude o ângulo")

    return len(erros) == 0, erros


def validar_arquivo(caminho: Path, request: str = "") -> tuple[bool, list[str]]:
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            plan = json.load(f)
    except Exception as e:
        return False, [f"falha ao ler JSON: {e}"]
    return validar_plano_json(plan, request)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Valida fleet plan JSON")
    parser.add_argument("--plan", required=True, help="Caminho do fleet-plan.json")
    parser.add_argument("--request", default="", help="Pedido original (para checar nomes inventados)")
    args = parser.parse_args()

    ok, erros = validar_arquivo(Path(args.plan), args.request)
    if ok:
        print("✅ Plan válido")
        sys.exit(0)
    else:
        print("❌ Plan inválido:")
        for e in erros:
            print(f"  - {e}")
        sys.exit(1)