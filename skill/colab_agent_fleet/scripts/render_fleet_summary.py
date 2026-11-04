#!/usr/bin/env python3"
"""
Renderiza markdown summary a partir de results JSONL + gates JSON.
Usado para relatório final público (com redaction).
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def carregar_jsonl(caminho: Path) -> list[dict]:
    resultados = []
    with open(caminho, "r", encoding="utf-8") as f:
        for linha in f:
            linha = linha.strip()
            if linha:
                resultados.append(json.loads(linha))
    return resultados


def carregar_json(caminho: Path) -> dict:
    with open(caminho, "r", encoding="utf-8") as f:
        return json.load(f)


def render(resultados: list[dict], gates: dict, request: str) -> str:
    lines = [
        f"# Fleet Research Summary",
        f"",
        f"**Request:** {request}",
        f"**Generated:** {__import__('time').strftime('%Y-%m-%d %H:%M:%S')}",
        f"",
        f"## Promotion Gates: {'✅ PASS' if gates.get('gate_pass') else '❌ FAIL'}",
        f"- Total tasks: {gates.get('total_tasks', 0)}",
        f"- Successful: {gates.get('successful', 0)}",
        f"- Success ratio: {gates.get('details', {}).get('actual_ratio', 0):.1%}",
        f"",
        f"## Results by Machine",
    ]

    by_machine = {}
    for r in resultados:
        by_machine.setdefault(r.get("maquina", "unknown"), []).append(r)

    for maquina in sorted(by_machine):
        tasks = by_machine[maquina]
        ok = sum(1 for t in tasks if t.get("sucesso"))
        lines.append(f"### {maquina} ({ok}/{len(tasks)} ✅)")
        for t in tasks:
            status = "✅" if t.get("sucesso") else "❌"
            lines.append(f"- {status} **tarefa{t['task']}**: {t['prompt'][:100]}")

    # Footer with redaction notice
    lines.extend([
        "",
        "---",
        "*This summary was generated from machine-readable run artifacts. ",
        "All secrets, private URLs, and internal identifiers have been redacted.*"
    ])

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Render fleet summary markdown")
    parser.add_argument("--results", required=True, help="results.jsonl")
    parser.add_argument("--gates", required=True, help="gates.json")
    parser.add_argument("--request", default="", help="Original request text")
    parser.add_argument("--out", required=True, help="Output markdown file")
    args = parser.parse_args()

    resultados = carregar_jsonl(Path(args.results))
    gates = carregar_json(Path(args.gates))

    md = render(resultados, gates, args.request)

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(md)

    print(f"✅ Summary rendered to {args.out}")


if __name__ == "__main__":
    main()