#!/usr/bin/env python3
"""Renderiza um resumo Markdown público a partir de artefatos de execução."""

import argparse
import html
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:  # Suporta import pelo pacote e execução direta do script.
    from .fleet_public_safety import redact_path, redact_text, sanitize_for_public
except ImportError:  # pragma: no cover - caminho usado por ``python arquivo.py``
    from fleet_public_safety import redact_path, redact_text, sanitize_for_public


_MARKDOWN_SPECIAL = re.compile(r"([\\`*_{}\[\]()#+\-.!|:])")


def carregar_jsonl(caminho: Path) -> list[dict[str, Any]]:
    resultados: list[dict[str, Any]] = []
    with caminho.open("r", encoding="utf-8") as handle:
        for line_number, linha in enumerate(handle, 1):
            linha = linha.strip()
            if not linha:
                continue
            try:
                item = json.loads(linha)
            except json.JSONDecodeError:
                raise ValueError(f"JSON inválido na linha {line_number}") from None
            if not isinstance(item, dict):
                raise ValueError(f"Resultado da linha {line_number} deve ser um objeto")
            resultados.append(item)
    return resultados


def carregar_json(caminho: Path) -> dict[str, Any]:
    with caminho.open("r", encoding="utf-8") as handle:
        try:
            data = json.load(handle)
        except json.JSONDecodeError:
            raise ValueError("Arquivo de gates não contém JSON válido") from None
    if not isinstance(data, dict):
        raise ValueError("Arquivo de gates deve conter um objeto")
    return data


def escape_markdown(value: str) -> str:
    """Escapa HTML e construções Markdown em texto vindo de artefatos."""
    text = " ".join(value.split())
    text = html.escape(text, quote=True)
    return _MARKDOWN_SPECIAL.sub(r"\\\1", text)


def _public_text(value: str) -> str:
    return escape_markdown(redact_text(value))


def _validate_results(resultados: list[dict[str, Any]]) -> None:
    if not isinstance(resultados, list):
        raise TypeError("results deve ser uma lista")
    for index, result in enumerate(resultados):
        if not isinstance(result, dict):
            raise TypeError(f"resultado {index} deve ser um objeto")
        if not isinstance(result.get("maquina", "unknown"), str):
            raise TypeError(f"resultado {index}: maquina deve ser string")
        task = result.get("task")
        if isinstance(task, bool) or not isinstance(task, (str, int)):
            raise TypeError(f"resultado {index}: task deve ser string ou inteiro")
        if not isinstance(result.get("prompt"), str):
            raise TypeError(f"resultado {index}: prompt deve ser string")
        if not isinstance(result.get("sucesso"), bool):
            raise TypeError(f"resultado {index}: sucesso deve ser booleano")


def _validate_gates(gates: dict[str, Any]) -> None:
    if not isinstance(gates, dict):
        raise TypeError("gates deve ser um objeto")
    if not isinstance(gates.get("gate_pass", False), bool):
        raise TypeError("gates.gate_pass deve ser booleano")
    for key in ("total_tasks", "successful"):
        value = gates.get(key, 0)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise TypeError(f"gates.{key} deve ser inteiro não negativo")
    details = gates.get("details", {})
    if not isinstance(details, dict):
        raise TypeError("gates.details deve ser um objeto")
    ratio = details.get("actual_ratio", 0)
    if isinstance(ratio, bool) or not isinstance(ratio, (int, float)):
        raise TypeError("gates.details.actual_ratio deve ser numérico")


def render(resultados: list[dict[str, Any]], gates: dict[str, Any], request: str) -> str:
    _validate_results(resultados)
    _validate_gates(gates)
    if not isinstance(request, str):
        raise TypeError("request deve ser string")

    # sanitize_for_public também documenta/aplica a allowlist de tipos comum;
    # request e prompts continuam passando por redact_text explicitamente.
    safe_request = sanitize_for_public(request)
    details = gates.get("details", {})
    lines = [
        "# Fleet Research Summary",
        "",
        f"**Request:** {_public_text(safe_request)}",
        f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
        "",
        f"## Promotion Gates: {'✅ PASS' if gates.get('gate_pass') is True else '❌ FAIL'}",
        f"- Total tasks: {gates.get('total_tasks', 0)}",
        f"- Successful: {gates.get('successful', 0)}",
        f"- Success ratio: {details.get('actual_ratio', 0):.1%}",
        "",
        "## Results by Machine",
    ]

    by_machine: dict[str, list[dict[str, Any]]] = {}
    for result in resultados:
        by_machine.setdefault(result.get("maquina", "unknown"), []).append(result)

    for maquina in sorted(by_machine):
        tasks = by_machine[maquina]
        ok = sum(1 for task in tasks if task.get("sucesso") is True)
        lines.append(f"### {_public_text(maquina)} ({ok}/{len(tasks)} ✅)")
        for task in tasks:
            status = "✅" if task.get("sucesso") is True else "❌"
            prompt = redact_text(task["prompt"])[:100]
            lines.append(f"- {status} **tarefa{_public_text(str(task['task']))}**: {_public_text(prompt)}")

    lines.extend(
        [
            "",
            "---",
            "*Generated from machine-readable run artifacts. Known sensitive values are "
            "redacted and untrusted text is escaped; this is not a guarantee that no secret "
            "is present.*",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render fleet summary markdown")
    parser.add_argument("--results", required=True, help="results.jsonl")
    parser.add_argument("--gates", required=True, help="gates.json")
    parser.add_argument("--request", default="", help="Original request text")
    parser.add_argument("--out", required=True, help="Output markdown file")
    args = parser.parse_args(argv)

    try:
        resultados = carregar_jsonl(Path(args.results))
        gates = carregar_json(Path(args.gates))
        md = render(resultados, gates, args.request)
    except (OSError, TypeError, ValueError) as exc:
        # Mensagens de validação são genéricas e não ecoam prompts ou segredos.
        print(f"Não foi possível renderizar: {exc}", file=sys.stderr)
        return 2

    destination = Path(args.out)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(md + "\n", encoding="utf-8")
    print(f"Summary rendered to {redact_path(destination)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
