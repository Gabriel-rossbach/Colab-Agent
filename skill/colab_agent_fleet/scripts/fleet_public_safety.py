#!/usr/bin/env python3
"""Redação e scan local de artefatos antes de uma publicação.

As regras cobrem formatos conhecidos e nomes de campos sensíveis. Elas reduzem
risco, mas não são uma garantia universal de que todo segredo foi encontrado.
"""

import argparse
import ipaddress
import math
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

REDACTED = "***REDACTED***"
# Um marcador temporário impede que uma substituição seja reconhecida pela
# próxima regex (por exemplo, sk-ant- seguido de sk-).
_PENDING_REDACTION = "\x00REDACTED\x00"

_SENSITIVE_FIELD_PARTS = {
    "auth",
    "authorization",
    "credential",
    "credentials",
    "key",
    "pass",
    "passwd",
    "password",
    "pwd",
    "secret",
    "session",
    "token",
}
_URL_EXTRA_SENSITIVE_NAMES = {"code", "sig", "signature", "state"}
_IP_PATTERN = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
_URL_PATTERN = re.compile(r"(?i)(?<![A-Za-z0-9])https?://[^\s<>\"']+")
_PRIVATE_IPV4_NETWORKS = tuple(
    ipaddress.ip_network(network)
    for network in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)
_PRIVATE_HOST_SUFFIXES = (".internal", ".local", ".lan", ".corp", ".home.arpa")


def _field_parts(name: object) -> set[str]:
    if not isinstance(name, str):
        return set()
    return {part for part in re.split(r"[^a-z0-9]+", name.lower()) if part}


# Para o scan, nomes genéricos demais (auth, pass, key) causam falsos positivos
# em código. A redação continua ampla; o scanner só alerta nomes inequivocamente
# sensíveis seguidos de um valor literal.
_SCAN_SENSITIVE_SUBSTRINGS = (
    "api_key",
    "apikey",
    "access_token",
    "accesstoken",
    "client_secret",
    "clientsecret",
    "private_key",
    "privatekey",
    "password",
    "passwd",
    "secret",
    "token",
    "credential",
    "authorization",
    "session_id",
    "sessionid",
)


def _is_scan_sensitive_field(name: object) -> bool:
    if not isinstance(name, str):
        return False
    normalized = re.sub(r"[^a-z0-9]", "", name.lower())
    return any(part in normalized for part in _SCAN_SENSITIVE_SUBSTRINGS)


def _is_sensitive_field(name: object) -> bool:
    """Identifica nomes sensíveis sem depender do formato do valor."""
    parts = _field_parts(name)
    if parts & _SENSITIVE_FIELD_PARTS:
        return True
    normalized = re.sub(r"[^a-z0-9]", "", name.lower()) if isinstance(name, str) else ""
    return normalized in {
        "apikey",
        "accesstoken",
        "clientsecret",
        "privatekey",
        "refreshtoken",
        "sessionid",
    }


def _replace_value(match: re.Match[str], value_group: str = "value") -> str:
    start = match.start(value_group) - match.start()
    return match.group(0)[:start] + _PENDING_REDACTION


def _redact_assignment(match: re.Match[str]) -> str:
    name = match.group("name")
    value = match.group("value")
    # Não apagar a palavra Bearer depois que a regra específica já tratou o
    # token; isso evita marcadores duplicados no header.
    if name.lower() == "authorization" and value.strip("'\"").lower() == "bearer":
        return match.group(0)
    # Regras específicas podem preservar um prefixo (ex.: sk-ant-). Não
    # reprocessar um valor já marcado evita perder esse prefixo.
    if _PENDING_REDACTION in value or value.strip("'\"") == REDACTED:
        return match.group(0)
    if _is_sensitive_field(name):
        return _replace_value(match)
    return match.group(0)


def _redact_url_query(match: re.Match[str]) -> str:
    name = match.group("name")
    normalized = re.sub(r"[^a-z0-9]", "", name.lower())
    if _is_sensitive_field(name) or normalized in _URL_EXTRA_SENSITIVE_NAMES:
        return _replace_value(match)
    return match.group(0)


def _parse_ipv4(value: str) -> ipaddress.IPv4Address | None:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return None
    return address if address.version == 4 else None


def _is_rfc1918(address: ipaddress.IPv4Address) -> bool:
    return any(address in network for network in _PRIVATE_IPV4_NETWORKS)


def _redact_ip(match: re.Match[str]) -> str:
    address = _parse_ipv4(match.group(0))
    if address is None:
        return match.group(0)
    if _is_rfc1918(address):
        if address in ipaddress.ip_network("10.0.0.0/8"):
            return "10.***.***.***"
        if address in ipaddress.ip_network("192.168.0.0/16"):
            return "192.168.***.***"
        return "172.***.***.***"
    if address.is_loopback or address.is_link_local or address.is_private:
        return "***.***.***.***"
    return match.group(0)


def _split_url_punctuation(url: str) -> tuple[str, str]:
    """Não consome pontuação de prosa/Markdown ao redor de uma URL."""
    suffix = ""
    while url:
        char = url[-1]
        matching_open = {")": "(", "]": "[", "}": "{"}.get(char)
        if char in ".,;!?" or (
            matching_open is not None and url.count(char) > url.count(matching_open)
        ):
            suffix = char + suffix
            url = url[:-1]
            continue
        break
    return url, suffix


def _url_details(url: str) -> tuple[str, str, bool]:
    """Retorna hostname, path e se a URL contém identificador de notebook."""
    try:
        parsed = urlsplit(url)
        hostname = (parsed.hostname or "").lower().rstrip(".")
    except ValueError:
        return "", "", False
    path = parsed.path.lower()
    notebook = (
        hostname == "colab.research.google.com" and path.startswith("/drive/")
    ) or (
        hostname == "drive.google.com"
        and (path.startswith("/file/d/") or path.startswith("/open"))
    )
    return hostname, path, notebook


def _is_loopback_hostname(hostname: str) -> bool:
    if hostname == "localhost" or hostname.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def _is_private_url(url: str) -> bool:
    hostname, _path, notebook = _url_details(url)
    if notebook or not hostname:
        return notebook
    if _is_loopback_hostname(hostname) or hostname.endswith(_PRIVATE_HOST_SUFFIXES):
        return True
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        # Hosts de compose/Kubernetes como ``backend`` são placeholders de
        # serviço. Redigir continua amplo; o scan exige sinais menos ambíguos.
        return False
    return address.is_private or address.is_loopback or address.is_link_local


def _redact_private_url(match: re.Match[str]) -> str:
    url, suffix = _split_url_punctuation(match.group(0))
    if not _is_private_url(url):
        return match.group(0)
    scheme = url.split(":", 1)[0].lower()
    return f"{scheme}://{_PENDING_REDACTION}{suffix}"


# A ordem importa: padrões específicos vêm antes dos genéricos. Todos usam o
# marcador temporário para que substituições sucessivas não dupliquem REDACTED.
SECRET_PATTERNS: list[tuple[re.Pattern[str], str | Callable[[re.Match[str]], str]]] = [
    (re.compile(r"(?<![A-Za-z0-9_-])sk-ant-[A-Za-z0-9_-]+"), "sk-ant-" + _PENDING_REDACTION),
    (re.compile(r"(?<![A-Za-z0-9_-])nvapi-[A-Za-z0-9_-]+"), "nvapi-" + _PENDING_REDACTION),
    (re.compile(r"(?<![A-Za-z0-9_-])sk-(?!ant-)[A-Za-z0-9_-]+"), "sk-" + _PENDING_REDACTION),
    (re.compile(r"(?<![A-Za-z0-9_-])gh[ps]_[A-Za-z0-9_-]+"), _PENDING_REDACTION),
    (re.compile(r"(?<![A-Za-z0-9_-])glpat-[A-Za-z0-9_-]+"), _PENDING_REDACTION),
    (re.compile(r"(?<![A-Za-z0-9_-])github_pat_[A-Za-z0-9_]+"), _PENDING_REDACTION),
    (_URL_PATTERN, _redact_private_url),
    (
        re.compile(r"(?i)(\bAuthorization\s*[:=]\s*Bearer\s+)([^\s'\"]+)"),
        lambda m: m.group(1) + _PENDING_REDACTION,
    ),
    (
        re.compile(
            r"(?i)(--(?=[A-Za-z0-9_-]*(?:key|token|secret|password|passwd|credential|auth))"
            r"[A-Za-z0-9][A-Za-z0-9_-]*\s*(?:=\s*|\s+)\s*)(?:'[^']*'|\"[^\"]*\"|\S+)"
        ),
        lambda m: m.group(1) + _PENDING_REDACTION,
    ),
    (
        re.compile(r"(?i)(\bexport\s+[A-Za-z_][A-Za-z0-9_]*\s*=\s*)(?:'[^']*'|\"[^\"]*\"|\S+)"),
        lambda m: m.group(1) + _PENDING_REDACTION,
    ),
    (
        re.compile(
            r"(?P<quote>['\"]?)(?P<name>\b[A-Za-z_][A-Za-z0-9_.-]*)(?P=quote)\s*[:=]\s*"
            r"(?P<value>'[^']*'|\"[^\"]*\"|[^\s&,;]+)"
        ),
        _redact_assignment,
    ),
    (
        re.compile(r"(?i)(?P<prefix>[?&](?P<name>[^=&#\s]+)=)(?P<value>[^&#\s]*)"),
        _redact_url_query,
    ),
    (
        re.compile(r"(?i)(https?://)([^/@\s]+)@"),
        lambda m: m.group(1) + _PENDING_REDACTION + "@",
    ),
    (re.compile(r"(?<![A-Za-z0-9_-])m-s-[a-z0-9-]+", re.IGNORECASE), "m-s-" + _PENDING_REDACTION),
    (
        re.compile(r"(?P<prefix>/(?:home|root|tmp|var/tmp|Users)/)[^\s'\"<>]+"),
        lambda m: m.group("prefix") + _PENDING_REDACTION,
    ),
    (
        re.compile(r"(?i)([A-Z]:\\Users\\)[^\s'\"<>]+"),
        lambda m: m.group(1) + _PENDING_REDACTION,
    ),
    (_IP_PATTERN, _redact_ip),
]


def redact_text(text: str) -> str:
    """Aplica todas as regras, inclusive quando já existe um marcador."""
    if not isinstance(text, str):
        text = str(text)
    for pattern, replacement in SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text.replace(_PENDING_REDACTION, REDACTED)


def redact_path(path: str | Path) -> str:
    """Mantém paths relativos ao cwd; fora dele, não expõe o caminho absoluto."""
    p = Path(path)
    try:
        if not p.is_absolute():
            p = (Path.cwd() / p).resolve()
        rel = p.relative_to(Path.cwd())
        return redact_text(str(rel))
    except (OSError, ValueError):
        try:
            rel = p.relative_to(Path.home())
            return redact_text(f"~/{rel}")
        except (OSError, ValueError):
            return redact_text(p.name)


def redact_env(env_dict: dict[str, str]) -> dict[str, str]:
    """Redige por nome do campo, mesmo quando o valor tem formato desconhecido."""
    safe: dict[str, str] = {}
    for key, value in env_dict.items():
        if _is_sensitive_field(key):
            safe[key] = REDACTED
        elif isinstance(value, str):
            safe[key] = redact_text(value)
        else:
            safe[key] = value
    return safe


def redact_command(cmd: str) -> str:
    """Redige exports, flags e headers sem executar o comando."""
    return redact_text(cmd)


def sanitize_for_public(obj: Any) -> Any:
    """Converte apenas tipos simples e containers para uma forma pública.

    Tipos desconhecidos viram um marcador, nunca ``repr(obj)`` (que poderia
    conter dados sensíveis). A redação é baseada em regras, não é proteção
    universal contra todo possível segredo.
    """
    if obj is None or isinstance(obj, (bool, int, float)):
        return obj
    if isinstance(obj, str):
        return redact_text(obj)
    if isinstance(obj, dict):
        result = {}
        for key, value in obj.items():
            safe_key = key if isinstance(key, (str, int, float, bool)) else str(type(key).__name__)
            result[safe_key] = REDACTED if _is_sensitive_field(key) else sanitize_for_public(value)
        return result
    if isinstance(obj, (list, tuple)):
        return [sanitize_for_public(value) for value in obj]
    return f"<redacted {type(obj).__name__}>"


# ─── SCAN LOCAL ───────────────────────────────────────────────────
# Diretórios gerados e caches não pertencem à superfície pública. Env locais e
# testes sintéticos têm exclusões separadas para não ler segredos reais.
_SCAN_EXCLUDED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "cache",
    ".cache",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    "node_modules",
    "target",
    "dist",
    "build",
}
_SCAN_BINARY_SUFFIXES = {
    ".7z",
    ".bmp",
    ".class",
    ".db",
    ".dll",
    ".dylib",
    ".exe",
    ".gif",
    ".gz",
    ".ico",
    ".jar",
    ".jpeg",
    ".jpg",
    ".pdf",
    ".png",
    ".p12",
    ".pfx",
    ".jks",
    ".keystore",
    ".pyc",
    ".so",
    ".sqlite",
    ".tar",
    ".wav",
    ".webp",
    ".whl",
    ".zip",
}
# Exemplos públicos já presentes no projeto. São valores exatos, não uma
# permissão para ignorar qualquer valor parecido com um placeholder.
_SCAN_PLACEHOLDERS = {
    "10.0.0.5",
    "192.168.1.100",
    "changeme",
    "dummy",
    "example",
    "m-s-kkb-use1b2-",
    "m-s-kkb-use1b2-b8jzjqfjmvfb",
    "m-s-id-de-sessao-secreto",
    "nvapi-abc123def456ghi789",
    "sk-abc123def456",
    "nvapi-chave-secreta-real",
    "opencrawl-fleet-token",
    "placeholder",
    "sample",
    "test",
    "your-key-here",
    "your_key_here",
}
_SCAN_PATH_PLACEHOLDER_USERS = {
    "alice",
    "bob",
    "example",
    "fleet",
    "seu-nome",
    "user",
    "username",
    "your-user",
}
_SCAN_PLACEHOLDER_WORDS = {
    "dummy",
    "exemplo",
    "example",
    "fake",
    "placeholder",
    "sample",
    "sintetica",
    "sintetico",
    "sintética",
    "sintético",
    "test",
    "teste",
}


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    kind: str


def _is_excluded_dir_name(name: str) -> bool:
    return name in _SCAN_EXCLUDED_DIRS or name.endswith(".egg-info")


def _is_local_env_file(path: Path) -> bool:
    name = path.name.lower()
    return name.startswith(".env") and name != ".env.example"


def _scan_excluded(path: Path) -> bool:
    if any(_is_excluded_dir_name(part) for part in path.parts):
        return True
    if _is_local_env_file(path):
        return True
    return path.suffix.lower() in _SCAN_BINARY_SUFFIXES


def _scan_allowlisted(path: Path, root: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        relative = Path(path.name)
    # Testes contêm vazamentos sintéticos deliberados. Não é uma permissão para
    # artefatos de execução ou outros arquivos fora dessas convenções.
    return (
        path.name == ".env.example"
        or "tests" in relative.parts
        or "test" in relative.parts
        or (path.name.startswith("test_") and path.suffix == ".py")
    )


def _is_placeholder(value: str) -> bool:
    cleaned = value.strip().strip("'\"").rstrip(",")
    lower = cleaned.lower()
    if not cleaned or lower in _SCAN_PLACEHOLDERS:
        return True
    # Prefixos conhecidos não escondem placeholders como SUA_CHAVE_AQUI.
    for prefix in (
        "sk-ant-",
        "nvapi-",
        "sk-",
        "ghp_",
        "ghs_",
        "glpat-",
        "github_pat_",
        "m-s-",
    ):
        if lower.startswith(prefix):
            return _is_placeholder(cleaned[len(prefix):])
    if lower.startswith(("$", "${", "%")) or "redacted" in lower:
        return True
    if lower.startswith(("your_", "your-", "sua_", "sua-", "replace_")):
        return True
    if "*" in cleaned or "..." in cleaned:
        return True
    words = {word for word in re.split(r"[^a-z0-9á-ú]+", lower) if word}
    if words & _SCAN_PLACEHOLDER_WORDS:
        return True
    return bool(re.fullmatch(r"(?:x+|\.+|-+)", lower))


def _is_placeholder_path(value: str) -> bool:
    match = re.match(r"/(?:home|Users)/([^/]+)", value)
    if match:
        # Reticências no restante do path não tornam um username real fictício.
        username = match.group(1).lower()
        return username in _SCAN_PATH_PLACEHOLDER_USERS or "*" in username
    return _is_placeholder(value)


def _entropy(value: str) -> float:
    counts = {char: value.count(char) for char in set(value)}
    length = len(value)
    return -sum((count / length) * math.log2(count / length) for count in counts.values())


def _looks_like_secret(value: str, *, prefixed: bool = False) -> bool:
    raw = value.strip()
    quoted = len(raw) >= 2 and raw[0] in "'\"" and raw[-1] == raw[0]
    value = raw.strip("'\"").rstrip(",").strip("`")
    if _is_placeholder(value):
        return False
    if prefixed:
        return len(value) >= 12
    # Expressões de código (os.getenv(...), token.trim(), ++revision) não são
    # valores literais. Evitar esses falsos positivos mantém o scan acionável.
    if any(char in value for char in "()[]{}<>") or value.startswith("+") or "\\" in value:
        return False
    # Atribuições como ``this.apiToken = apiToken`` copiam identificadores;
    # exigir aspas ou algum caractere não identificador para esse caso.
    if not quoted and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        return False
    if len(value) < 8 or len(set(value)) < 4:
        return False
    return _entropy(value) >= 2.7


_SCAN_VALUE_PATTERNS: list[tuple[str, re.Pattern[str], str, bool]] = [
    (
        "private-key",
        re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"),
        "",
        True,
    ),
    (
        "api-token",
        re.compile(
            r"(?<![A-Za-z0-9_-])(?P<value>(?:sk-ant-|nvapi-|sk-|gh[ps]_|glpat-|github_pat_)"
            r"[A-Za-z0-9_-]{8,}|AKIA[0-9A-Z]{16})"
        ),
        "value",
        True,
    ),
    (
        "bearer-token",
        re.compile(r"(?i)\bBearer\s+(?P<value>[A-Za-z0-9._~+/=-]{8,})"),
        "value",
        False,
    ),
    (
        "url-userinfo",
        re.compile(r"(?i)https?://(?P<value>[^/@\s]{8,})@"),
        "value",
        False,
    ),
    (
        "cli-secret",
        re.compile(
            r"(?i)--(?=[A-Za-z0-9_-]*(?:key|token|secret|password|passwd|credential|auth))"
            r"[A-Za-z0-9][A-Za-z0-9_-]*\s*(?:=\s*|\s+)\s*"
            r"(?P<value>'[^']{8,}'|\"[^\"]{8,}\"|[^\s&,;'\"]{8,})"
        ),
        "value",
        False,
    ),
    (
        "sensitive-assignment",
        re.compile(
            r"(?i)(?P<quote>['\"]?)\b(?P<name>[A-Za-z_][A-Za-z0-9_.-]*)(?P=quote)\s*[:=]\s*"
            r"(?P<value>'[^']{8,}'|\"[^\"]{8,}\"|[^\s&,;'\"]{8,})"
        ),
        "value",
        False,
    ),
    (
        "url-query-secret",
        re.compile(r"(?i)[?&](?P<name>[^=&#\s]+)=(?P<value>[^&#\s'\"]{8,})"),
        "value",
        False,
    ),
]


_SCAN_SESSION_PATTERN = re.compile(
    r"(?i)(?<![A-Za-z0-9_-])(?P<value>m-s-[a-z0-9-]+)"
)
_SCAN_PATH_PATTERN = re.compile(
    r"(?P<value>/(?:home|Users)/[A-Za-z0-9._*-]+(?:/[^\s'\"<>`]+)?)"
)


def _line_findings(line: str) -> list[str]:
    kinds: list[str] = []
    for kind, pattern, group, prefixed in _SCAN_VALUE_PATTERNS:
        for match in pattern.finditer(line):
            if kind == "sensitive-assignment" and not _is_scan_sensitive_field(match.group("name")):
                continue
            if kind == "url-query-secret":
                name = match.group("name")
                normalized = re.sub(r"[^a-z0-9]", "", name.lower())
                if not (_is_scan_sensitive_field(name) or normalized in _URL_EXTRA_SENSITIVE_NAMES):
                    continue
            value = match.group(group) if group else kind
            is_secret = kind == "private-key" or _looks_like_secret(value, prefixed=prefixed)
            if is_secret and kind not in kinds:
                kinds.append(kind)

    for match in _SCAN_SESSION_PATTERN.finditer(line):
        if _looks_like_secret(match.group("value"), prefixed=True):
            if "session-id" not in kinds:
                kinds.append("session-id")

    for match in _SCAN_PATH_PATTERN.finditer(line):
        value = match.group("value").rstrip(".,;:)")
        if not _is_placeholder_path(value) and "private-path" not in kinds:
            kinds.append("private-path")

    for match in _IP_PATTERN.finditer(line):
        value = match.group(0)
        address = _parse_ipv4(value)
        if (
            address is not None
            and (_is_rfc1918(address) or address.is_link_local)
            and not _is_placeholder(value)
            and "private-ip" not in kinds
        ):
            kinds.append("private-ip")

    for match in _URL_PATTERN.finditer(line):
        url, _suffix = _split_url_punctuation(match.group(0))
        if "*" in url or "..." in url:
            continue
        hostname, _path, _notebook = _url_details(url)
        # Loopback é um destino convencional de desenvolvimento, não um
        # identificador de infraestrutura privada publicado acidentalmente.
        if _is_loopback_hostname(hostname):
            continue
        if _is_private_url(url) and "private-url" not in kinds:
            kinds.append("private-url")
    return kinds


def _display_path(path: Path, root: Path) -> str:
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError:
        relative = path.name
    return redact_text(relative)


def scan_path(
    target: str | Path,
    *,
    max_file_bytes: int = 1_000_000,
    max_files: int = 5_000,
) -> list[Finding]:
    """Procura achados públicos prováveis sem retornar seus valores."""
    root = Path(target)
    if root.is_symlink() or _is_local_env_file(root):
        return []
    if root.is_dir() and _scan_excluded(root):
        return []
    if root.is_file():
        if _scan_excluded(root) or _scan_allowlisted(root, root.parent):
            return []
        candidates = [root]
        display_root = root.parent
    else:
        candidates = []
        display_root = root
        for current, dirs, files in os.walk(root, followlinks=False):
            dirs[:] = sorted(d for d in dirs if not _is_excluded_dir_name(d))
            current_path = Path(current)
            for name in sorted(files):
                path = current_path / name
                if path.is_symlink() or _scan_excluded(path) or _scan_allowlisted(path, root):
                    continue
                candidates.append(path)
                if len(candidates) >= max_files:
                    break
            if len(candidates) >= max_files:
                break

    findings: list[Finding] = []
    for path in candidates:
        try:
            if path.stat().st_size > max_file_bytes:
                continue
            with path.open("rb") as handle:
                raw = handle.read(max_file_bytes + 1)
            if len(raw) > max_file_bytes or b"\x00" in raw[:8192]:
                continue
            text = raw.decode("utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for line_number, line in enumerate(text.splitlines(), 1):
            for kind in _line_findings(line):
                findings.append(Finding(_display_path(path, display_root), line_number, kind))
    return findings


def _self_test() -> int:
    # Valores construídos em runtime não deixam segredos sintéticos no próprio
    # arquivo do scanner. Nenhum valor de teste é impresso.
    fake_key = "nvapi-" + ("a1" * 12)
    fake_token = "sk-" + ("b2" * 10)
    checks = [
        fake_key not in redact_text(fake_key),
        fake_token not in redact_command("--token " + fake_token),
        "secret" not in redact_text("https://example.test/?api_key=secret").lower(),
        redact_text(REDACTED + " " + fake_key).count(REDACTED) == 2,
        sanitize_for_public({"password": "formato-desconhecido"})["password"] == REDACTED,
    ]
    if not all(checks):
        print("self-test: FAIL", file=sys.stderr)
        return 1
    print(f"self-test: OK ({len(checks)} checks; nenhum valor sensível impresso)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Self-test ou scan local de achados públicos prováveis")
    parser.add_argument("--scan", metavar="CAMINHO", help="arquivo ou diretório a verificar")
    parser.add_argument("--max-file-bytes", type=int, default=1_000_000)
    parser.add_argument("--max-files", type=int, default=5_000)
    args = parser.parse_args(argv)
    if not args.scan:
        return _self_test()
    if args.max_file_bytes <= 0 or args.max_files <= 0:
        parser.error("limites devem ser positivos")

    target = Path(args.scan)
    if not target.exists():
        print(f"Caminho não encontrado: {redact_path(target)}", file=sys.stderr)
        return 2
    if _is_local_env_file(target):
        print(f"Scan recusado para env local: {redact_path(target)}", file=sys.stderr)
        return 2
    if target.is_symlink():
        print(f"Scan de symlink recusado: {redact_path(target)}", file=sys.stderr)
        return 2

    findings = scan_path(
        target,
        max_file_bytes=args.max_file_bytes,
        max_files=args.max_files,
    )
    for finding in findings:
        # Nunca imprimir a linha ou o valor que casou com a regra.
        print(f"{finding.path}:{finding.line}: possível achado público ({finding.kind})")
    if findings:
        print(f"Scan encontrou {len(findings)} ocorrência(s); nenhum valor foi exibido.")
        return 1
    print("Scan concluído: nenhum achado provável (regras não são garantia universal).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
