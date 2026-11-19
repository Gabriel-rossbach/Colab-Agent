import json
import os
import stat
from datetime import datetime
from types import SimpleNamespace

import pytest

from skill.colab_agent_fleet.scripts import capture_fleet_context as capture
from skill.colab_agent_fleet.scripts.fleet_public_safety import REDACTED


def test_run_cmd_records_failure_and_redacts_error(monkeypatch):
    secret = "bearer-token-de-teste-123456"

    def fake_run(cmd, **kwargs):
        assert cmd[0] == "git"
        return SimpleNamespace(returncode=1, stdout="", stderr=f"Authorization: Bearer {secret}")

    monkeypatch.setattr(capture.subprocess, "run", fake_run)
    errors: list[str] = []
    assert capture.run_cmd(["git", "status"], errors) == ""
    assert len(errors) == 1
    assert secret not in errors[0]


def test_run_cmd_records_exception_without_real_command(monkeypatch):
    def fake_run(cmd, **kwargs):
        raise FileNotFoundError("comando ausente")

    monkeypatch.setattr(capture.subprocess, "run", fake_run)
    errors: list[str] = []
    assert capture.run_cmd(["colab", "sessions"], errors) == ""
    assert errors == ["colab: FileNotFoundError: comando ausente"]


def test_git_info_sanitizes_remote_and_reports_unknown_dirty(monkeypatch):
    secret = "remote-user-secret"

    def fake_run(cmd, errors=None, cwd=None):
        if "status" in cmd:
            return " M arquivo.py"
        if cmd[-1] == "HEAD" and cmd[1] == "rev-parse":
            return "abc123"
        if cmd[1] == "--abbrev-ref":
            return "main"
        if cmd[1] == "config":
            return f"https://user:{secret}@example.test/repo.git?token=token-url-secreto"
        raise AssertionError(cmd)

    monkeypatch.setattr(capture, "run_cmd", fake_run)
    info = capture.git_info([])
    assert info["dirty"] is True
    assert secret not in info["remote_url"]
    assert "token-url-secreto" not in info["remote_url"]
    assert REDACTED in info["remote_url"]

    def failing_status(cmd, errors=None, cwd=None):
        if "status" in cmd:
            errors.append("git: exit 128")
            return ""
        return "ok"

    errors: list[str] = []
    monkeypatch.setattr(capture, "run_cmd", failing_status)
    assert capture.git_info(errors)["dirty"] is None
    assert any("git" in error for error in errors)


def test_env_info_never_exposes_sensitive_values(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "valor-sensivel-desconhecido")
    monkeypatch.setenv("MAQUINAS", "/home/alice/private/machines")
    env = capture.env_info()
    assert env["NVIDIA_API_KEY"] == REDACTED
    assert "valor-sensivel-desconhecido" not in json.dumps(env)
    assert "alice" not in env["MAQUINAS"]


def test_colab_session_ids_are_always_redacted(monkeypatch):
    session_id = "m-s-id-de-sessao-secreto"

    def fake_run(cmd, errors=None, cwd=None):
        assert cmd == ["colab", "sessions"]
        return f"[cpu1] {session_id} | Hardware: CPU | Region: us"

    monkeypatch.setattr(capture, "run_cmd", fake_run)
    sessions = capture.colab_sessions([])
    assert sessions == [{"name": "cpu1", "id": REDACTED, "hardware": "CPU"}]
    assert session_id not in json.dumps(sessions)


def test_write_private_json_uses_owner_only_permissions(tmp_path):
    destination = tmp_path / "nested" / "context.json"
    capture.write_private_json(destination, {"ok": True, "token": REDACTED})
    data = json.loads(destination.read_text(encoding="utf-8"))
    assert data["ok"] is True
    if os.name == "posix":
        assert stat.S_IMODE(destination.stat().st_mode) == 0o600


def test_main_uses_helpers_and_utc_without_real_commands(tmp_path, monkeypatch):
    monkeypatch.setattr(capture, "git_info", lambda errors=None, repo_root=".": {"dirty": False})
    monkeypatch.setattr(capture, "env_info", lambda: {"NVIDIA_API_KEY": REDACTED})
    monkeypatch.setattr(capture, "colab_sessions", lambda errors=None: [{"id": REDACTED}])
    monkeypatch.setattr(capture, "openclaw_version", lambda errors=None: "fake-version")

    output = tmp_path / "context.json"
    assert capture.main(["--out", str(output), "--repo-root", str(tmp_path)]) == 0
    context = json.loads(output.read_text(encoding="utf-8"))
    parsed = datetime.fromisoformat(context["timestamp"].replace("Z", "+00:00"))
    assert parsed.tzinfo is not None
    assert parsed.utcoffset().total_seconds() == 0
    assert context["env"]["NVIDIA_API_KEY"] == REDACTED
    assert context["errors"] == []
    if os.name == "posix":
        assert stat.S_IMODE(output.stat().st_mode) == 0o600


def test_main_includes_command_errors_instead_of_clean_state(tmp_path, monkeypatch):
    monkeypatch.setattr(capture, "git_info", lambda errors=None, repo_root=".": {"dirty": None})
    monkeypatch.setattr(capture, "env_info", lambda: {})
    monkeypatch.setattr(capture, "colab_sessions", lambda errors=None: errors.append("colab: indisponível") or [])
    monkeypatch.setattr(capture, "openclaw_version", lambda errors=None: "not installed")

    output = tmp_path / "context.json"
    assert capture.main(["--out", str(output), "--repo-root", str(tmp_path)]) == 0
    context = json.loads(output.read_text(encoding="utf-8"))
    assert context["errors"] == ["colab: indisponível"]
    assert context["git"]["dirty"] is None
