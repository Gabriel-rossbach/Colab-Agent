#!/usr/bin/env python3
"""Captura contexto da fleet em JSON privado, com redação de valores sensíveis."""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:  # Suporta tanto import pelo pacote quanto execução direta do script.
    from .fleet_public_safety import REDACTED, redact_env, redact_path, redact_text, sanitize_for_public
except ImportError:  # pragma: no cover - caminho usado por ``python arquivo.py``
    from fleet_public_safety import REDACTED, redact_env, redact_path, redact_text, sanitize_for_public


def _record_error(errors: list[str] | None, cmd: list[str], detail: str) -> None:
    if errors is not None:
        # O detalhe passa pelo mesmo pipeline de redação; não incluímos stdout
        # bruto nem variáveis de ambiente na mensagem.
        errors.append(f"{cmd[0]}: {redact_text(detail)}")


def run_cmd(cmd: list[str], errors: list[str] | None = None, cwd: str | None = None) -> str:
    """Executa um comando curto e registra falhas em vez de fingir sucesso."""
    kwargs: dict[str, Any] = {"capture_output": True, "text": True, "timeout": 30}
    if cwd is not None:
        kwargs["cwd"] = cwd
    try:
        completed = subprocess.run(cmd, **kwargs)
    except Exception as exc:
        _record_error(errors, cmd, f"{type(exc).__name__}: {exc}")
        return ""

    stdout = redact_text(getattr(completed, "stdout", "") or "")
    returncode = getattr(completed, "returncode", 0)
    if returncode:
        stderr = getattr(completed, "stderr", "") or ""
        detail = f"exit {returncode}"
        if stderr.strip():
            detail += f": {stderr.strip()}"
        _record_error(errors, cmd, detail)
    return stdout.strip()


def redact(text: str) -> str:
    """Compatibilidade com o nome antigo, delegando aos helpers comuns."""
    return redact_text(text)


def git_info(errors: list[str] | None = None, repo_root: str | Path = ".") -> dict[str, Any]:
    cwd = str(repo_root)
    before_status = len(errors) if errors is not None else 0
    status = run_cmd(["git", "status", "--porcelain"], errors, cwd)
    status_failed = errors is not None and len(errors) != before_status
    return {
        "commit": run_cmd(["git", "rev-parse", "HEAD"], errors, cwd),
        "branch": run_cmd(["git", "rev-parse", "--abbrev-ref", "HEAD"], errors, cwd),
        "dirty": None if status_failed else bool(status),
        "remote_url": redact_text(run_cmd(["git", "config", "--get", "remote.origin.url"], errors, cwd)),
    }


def env_info() -> dict[str, str]:
    """Inclui apenas presença/ausência e valores não sensíveis já redigidos."""
    keys = [
        "NVIDIA_API_KEY",
        "MODELO_PLANEJADOR",
        "MAQUINAS",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
    ]
    result: dict[str, str] = {}
    for key in keys:
        value = os.getenv(key)
        if not value:
            result[key] = "(not set)"
        else:
            result[key] = redact_env({key: value})[key]
    return result


def colab_sessions(errors: list[str] | None = None) -> list[dict[str, str]]:
    out = run_cmd(["colab", "sessions"], errors)
    sessions: list[dict[str, str]] = []
    for line in out.splitlines():
        if "[" in line and "]" in line:
            # Parse: [cpu1] m-xxx | Hardware: CPU | ...
            import re

            match = re.search(r"\[(\w+)\]\s+(\S+)\s+\|\s+Hardware:\s+(\w+)", line)
            if match:
                sessions.append(
                    {
                        "name": redact_text(match.group(1)),
                        # IDs nunca são publicados, mesmo se o formato mudar.
                        "id": REDACTED,
                        "hardware": redact_text(match.group(3)),
                    }
                )
    return sessions


def openclaw_version(errors: list[str] | None = None) -> str:
    return run_cmd(["openclaw", "--version"], errors) or "not installed"


def write_private_json(path: str | Path, payload: dict[str, Any]) -> None:
    """Cria/trunca o artefato com 0600 e reforça a permissão quando possível."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    try:
        os.chmod(destination, 0o600)
    except OSError:
        # Alguns sistemas de arquivos não suportam chmod; os.open já usou 0600.
        pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Captura contexto da fleet para reprodutibilidade")
    parser.add_argument("--out", required=True, help="Arquivo JSON de saída (privado)")
    parser.add_argument("--repo-root", default=".", help="Raiz do repo git")
    args = parser.parse_args(argv)

    errors: list[str] = []
    context = {
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "git": git_info(errors, args.repo_root),
        "env": env_info(),
        "colab_sessions": colab_sessions(errors),
        "openclaw_version": openclaw_version(errors),
        "python_version": sys.version.split()[0],
        "platform": sys.platform,
        "errors": errors,
    }
    # Última camada para campos adicionados no futuro; tipos desconhecidos não
    # são serializados via repr, que poderia vazar dados.
    public_context = sanitize_for_public(context)
    write_private_json(args.out, public_context)
    print(f"Context captured to {redact_path(args.out)} ({len(errors)} command error(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
