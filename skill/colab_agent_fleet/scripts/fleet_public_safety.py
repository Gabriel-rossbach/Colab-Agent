#!/usr/bin/env python3
"""
Helpers puros (sem I/O de rede) para redação de paths, URLs, env vars, comandos.
Usado por outros scripts para garantir output seguro para público.
"""

import os
import re
from pathlib import Path
from typing import Any

# ─── PATTERNS DE REDACTION ────────────────────────────────────────
# Order matters: more specific patterns first
SECRET_PATTERNS = [
    # API Keys (more specific first)
    (re.compile(r"(sk-ant-[A-Za-z0-9_-]+)"), "sk-ant-***REDACTED***"),
    (re.compile(r"(nvapi-[A-Za-z0-9_-]+)"), "nvapi-***REDACTED***"),
    (re.compile(r"(sk-[A-Za-z0-9_-]+)"), "sk-***REDACTED***"),
    (re.compile(r"(gh[ps]_[A-Za-z0-9_-]+)"), "***REDACTED***"),
    (re.compile(r"(glpat-[A-Za-z0-9_-]+)"), "***REDACTED***"),
    # URLs com secrets
    (re.compile(r"(https?://[^\s]*?[?&](?:api[_-]?key|token|secret|password|auth)=[^&\s]+)"),
     lambda m: m.group(1).split("=")[0] + "=***REDACTED***"),
    # Colab session IDs
    (re.compile(r"(m-s-[a-z0-9-]+)"), "m-s-***REDACTED***"),
    # Paths absolutos locais
    (re.compile(r"(/home/[a-z0-9_-]+)"), "/home/***"),
    (re.compile(r"(/root/[a-z0-9_/.-]+)"), "/root/***"),
    (re.compile(r"(/tmp/[a-z0-9_-]+)"), "/tmp/***"),
    # IPs privados
    (re.compile(r"\b(10\.\d{1,3}\.\d{1,3}\.\d{1,3})\b"), "10.***.***.***"),
    (re.compile(r"\b(192\.168\.\d{1,3}\.\d{1,3})\b"), "192.168.***.***"),
    (re.compile(r"\b(172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b"), "172.***.***.***"),
]


def redact_text(text: str) -> str:
    """Aplica todos os patterns de redaction no texto."""
    # Skip already redacted text
    if "***REDACTED***" in text:
        return text
    for pattern, repl in SECRET_PATTERNS:
        if callable(repl):
            text = pattern.sub(repl, text)
        else:
            text = pattern.sub(repl, text)
    return text


def redact_path(path: str | Path) -> str:
    """Redacta path absoluto mantendo só o basename ou path relativo seguro."""
    p = Path(path)
    try:
        # Resolve relative paths against cwd
        if not p.is_absolute():
            p = (Path.cwd() / p).resolve()
        # Tenta fazer relativo ao cwd
        rel = p.relative_to(Path.cwd())
        return str(rel)
    except ValueError:
        # Fora do cwd - usa path relativo ao home ou basename
        try:
            rel = p.relative_to(Path.home())
            return f"~/{rel}"
        except ValueError:
            return p.name


def redact_env(env_dict: dict[str, str]) -> dict[str, str]:
    """Redacta valores de dict de env vars."""
    sensitive_keywords = {"KEY", "TOKEN", "SECRET", "PASSWORD", "PASS", "PASSWD"}
    return {
        k: "***REDACTED***" if any(kw in k.upper() for kw in sensitive_keywords) else v
        for k, v in env_dict.items()
    }


def redact_command(cmd: str) -> str:
    """Redacta comando bash (remove secrets de argumentos)."""
    # Remove export VAR=secret
    cmd = re.sub(r'(export\s+\w+=)(\S+)', r'\1***REDACTED***', cmd)
    # Remove --flag secret
    cmd = re.sub(r'(--\w+\s+)(\S*key\S*|\S*token\S*|\S*secret\S*)', r'\1***REDACTED***', cmd, flags=re.IGNORECASE)
    return redact_text(cmd)


def sanitize_for_public(obj: Any) -> Any:
    """Recursively sanitize dict/list/str for public output."""
    if isinstance(obj, str):
        return redact_text(obj)
    elif isinstance(obj, dict):
        return {k: sanitize_for_public(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize_for_public(v) for v in obj]
    return obj


if __name__ == "__main__":
    # Quick self-test
    test_cases = [
        "export NVIDIA_API_KEY=nvapi-abc123def456ghi789",
        "curl -H 'Authorization: Bearer sk-abc123' https://api.openai.com/v1/models",
        "colab ssh -s cpu1 -- openclaw agent exec 'test'",
        "/home/apolo/ia/skill/colab-agent-fleet/scripts/test.py",
        "m-s-kkb-use1b2-b8jzjqfjmvfb",
        "10.0.0.5 and 192.168.1.100",
    ]

    for tc in test_cases:
        print(f"ORIG: {tc}")
        print(f"SAFE: {redact_text(tc)}")
        print()