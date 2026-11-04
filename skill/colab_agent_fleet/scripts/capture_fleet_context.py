#!/usr/bin/env python3
"""
Captura contexto da fleet antes do lançamento: git, env (redacted), Colab sessions, OpenClaw version.
Output: JSON machine-readable para reprodutibilidade.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


def run_cmd(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=30).stdout.strip()
    except Exception:
        return ""


def redact(text: str) -> str:
    """Remove secrets, tokens, private URLs from text."""
    patterns = [
        (r"(nvapi-[A-Za-z0-9_-]{20,})", "nvapi-***REDACTED***"),
        (r"(sk-[A-Za-z0-9_-]{20,})", "sk-***REDACTED***"),
        (r"(gh[ps]_[A-Za-z0-9_-]{20,})", "gh***REDACTED***"),
        (r"(https?://[^\s]*?[?&](?:api[_-]?key|token|secret|password)=[^&\s]+)", r"\1***REDACTED***"),
        (r"(colab\.ssh\s+-s\s+\w+)", "colab ssh -s ***"),
    ]
    for pat, repl in patterns:
        text = re.sub(pat, repl, text, flags=re.IGNORECASE)
    return text


def git_info() -> dict[str, Any]:
    return {
        "commit": run_cmd(["git", "rev-parse", "HEAD"]),
        "branch": run_cmd(["git", "rev-parse", "--abbrev-ref", "HEAD"]),
        "dirty": bool(run_cmd(["git", "status", "--porcelain"])),
        "remote_url": redact(run_cmd(["git", "config", "--get", "remote.origin.url"])),
    }


def env_info() -> dict[str, str]:
    """Variáveis de ambiente relevantes (redacted)."""
    keys = [
        "NVIDIA_API_KEY",
        "MODELO_PLANEJADOR",
        "MAQUINAS",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
    ]
    return {k: redact(os.getenv(k, "")) or "(not set)" for k in keys}


def colab_sessions() -> list[dict]:
    out = run_cmd(["colab", "sessions"])
    sessions = []
    for line in out.splitlines():
        if "[" in line and "]" in line:
            # Parse: [cpu1] m-xxx | Hardware: CPU | ...
            import re
            m = re.search(r"\[(\w+)\]\s+(\S+)\s+\|\s+Hardware:\s+(\w+)", line)
            if m:
                sessions.append({
                    "name": m.group(1),
                    "id": m.group(2),
                    "hardware": m.group(3),
                })
    return sessions


def openclaw_version() -> str:
    return run_cmd(["openclaw", "--version"]) or "not installed"


def main():
    parser = argparse.ArgumentParser(description="Captura contexto da fleet para reprodutibilidade")
    parser.add_argument("--out", required=True, help="Arquivo JSON de saída")
    parser.add_argument("--repo-root", default=".", help="Raiz do repo git")
    args = parser.parse_args()

    # Muda para repo root se especificado
    if args.repo_root != ".":
        os.chdir(args.repo_root)

    context = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "git": git_info(),
        "env": env_info(),
        "colab_sessions": colab_sessions(),
        "openclaw_version": openclaw_version(),
        "python_version": sys.version.split()[0],
        "platform": sys.platform,
    }

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(context, f, ensure_ascii=False, indent=2)

    print(f"✅ Context captured to {args.out}")


if __name__ == "__main__":
    main()