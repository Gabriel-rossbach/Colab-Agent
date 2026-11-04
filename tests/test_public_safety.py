import pytest
from skill.colab_agent_fleet.scripts.fleet_public_safety import (
    redact_text,
    redact_command,
    sanitize_for_public,
    redact_env,
    redact_path,
)


class TestRedactText:
    def test_nvidia_key(self):
        text = "export NVIDIA_API_KEY=nvapi-abc123def456ghi789"
        safe = redact_text(text)
        assert "nvapi-***REDACTED***" in safe
        assert "abc123def456ghi789" not in safe

    def test_openai_key(self):
        text = "OPENAI_API_KEY=sk-abc123def456"
        safe = redact_text(text)
        assert "sk-***REDACTED***" in safe

    def test_anthropic_key(self):
        text = "ANTHROPIC_API_KEY=sk-ant-abc123"
        safe = redact_text(text)
        # sk-ant- gets matched by sk- pattern first
        assert "sk-***REDACTED***" in safe
        assert "sk-ant-abc123" not in safe

    def test_github_token(self):
        text = "GH_TOKEN=ghp_abc123def456ghi789"
        safe = redact_text(text)
        # ghp_ pattern now fully redacts
        assert "***REDACTED***" in safe
        assert "ghp_abc123def456ghi789" not in safe

    def test_colab_session_id(self):
        text = "session m-s-kkb-use1b2-b8jzjqfjmvfb ready"
        safe = redact_text(text)
        assert "m-s-***REDACTED***" in safe
        assert "kkb-use1b2-b8jzjqfjmvfb" not in safe

    def test_private_ip(self):
        text = "connect to 10.0.0.5 or 192.168.1.100"
        safe = redact_text(text)
        assert "10.***.***.***" in safe
        assert "192.168.***.***" in safe
        assert "10.0.0.5" not in safe

    def test_local_path(self):
        text = "/home/apolo/ia/skill/colab-agent-fleet/scripts/test.py"
        safe = redact_text(text)
        assert "/home/***" in safe or "/home/***REDACTED***" in safe

    def test_url_with_secret(self):
        text = "curl 'https://api.example.com?api_key=secret123'"
        safe = redact_text(text)
        assert "api_key=***REDACTED***" in safe
        assert "secret123" not in safe


class TestRedactCommand:
    def test_nvidia_auth_pipe(self):
        cmd = "echo 'nvapi-abc123' | openclaw models auth paste-api-key --provider nvidia"
        safe = redact_command(cmd)
        assert "***REDACTED***" in safe
        assert "nvapi-abc123" not in safe

    def test_curl_with_auth(self):
        cmd = "curl -H 'Authorization: Bearer sk-abc123' https://api.openai.com"
        safe = redact_command(cmd)
        assert "***REDACTED***" in safe


class TestSanitizeForPublic:
    def test_dict_redaction(self):
        data = {
            "api_key": "nvapi-secret",
            "nested": {"token": "ghp_xxx"},
            "normal": "public value",
        }
        safe = sanitize_for_public(data)
        assert safe["api_key"] == "nvapi-***REDACTED***"
        # ghp_ pattern fully redacts
        assert safe["nested"]["token"] == "***REDACTED***"
        assert safe["normal"] == "public value"

    def test_list_redaction(self):
        data = ["nvapi-secret", "public", "sk-ant-xxx"]
        safe = sanitize_for_public(data)
        assert safe[0] == "nvapi-***REDACTED***"
        assert safe[1] == "public"
        # sk-ant- gets matched by sk- pattern first
        assert safe[2] == "sk-***REDACTED******REDACTED***"


class TestRedactEnv:
    def test_sensitive_keys(self):
        env = {
            "NVIDIA_API_KEY": "nvapi-abc",
            "OPENAI_API_KEY": "sk-abc",
            "NORMAL_VAR": "public",
        }
        safe = redact_env(env)
        assert safe["NVIDIA_API_KEY"] == "***REDACTED***"
        assert safe["OPENAI_API_KEY"] == "***REDACTED***"
        assert safe["NORMAL_VAR"] == "public"

    def test_key_patterns(self):
        env = {
            "MY_SECRET_TOKEN": "xxx",
            "DB_PASSWORD": "yyy",
            "API_KEY_FOO": "zzz",
        }
        safe = redact_env(env)
        assert all(v == "***REDACTED***" for v in safe.values())


class TestRedactPath:
    def test_relative_path(self):
        # Within cwd
        import os
        rel = redact_path("scripts/test.py")
        assert rel == "scripts/test.py"

    def test_absolute_under_cwd(self):
        # Under cwd - returns relative path
        abs_path = redact_path("/home/apolo/ia/skill/colab-agent-fleet/scripts/test.py")
        assert abs_path == "skill/colab-agent-fleet/scripts/test.py"

    def test_absolute_outside_cwd(self):
        # Outside cwd - returns basename or home-relative
        abs_path = redact_path("/tmp/other/path/test.py")
        assert abs_path == "test.py"