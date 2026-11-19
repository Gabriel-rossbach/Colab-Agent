from pathlib import Path

import pytest

from skill.colab_agent_fleet.scripts.fleet_public_safety import (
    REDACTED,
    main,
    redact_command,
    redact_env,
    redact_path,
    redact_text,
    sanitize_for_public,
    scan_path,
)


class TestRedactText:
    def test_known_keys_and_no_duplicate_marker(self):
        text = "ANTHROPIC_API_KEY=sk-ant-abc123 e OPENAI_API_KEY=sk-abc123def456"
        safe = redact_text(text)
        assert "sk-ant-abc123" not in safe
        assert "sk-abc123def456" not in safe
        assert "sk-ant-" + REDACTED in safe
        assert safe.count(REDACTED) == 2
        assert REDACTED + REDACTED not in safe

    def test_already_redacted_text_is_not_a_bypass(self):
        text = f"api_key={REDACTED}"
        assert redact_text(text) == text
        safe = redact_text(f"{REDACTED} --token valor-desconhecido-sintetico")
        assert "valor-desconhecido-sintetico" not in safe
        assert safe.count(REDACTED) == 2

    def test_sensitive_assignment_with_unknown_format(self):
        safe = redact_text("PASSWORD=valor-sem-formato-sintetico")
        assert "valor-sem-formato-sintetico" not in safe
        assert REDACTED in safe

    def test_colab_session_id(self):
        safe = redact_text("session m-s-kkb-use1b2-b8jzjqfjmvfb ready")
        assert "m-s-" + REDACTED in safe
        assert "kkb-use1b2-b8jzjqfjmvfb" not in safe

    def test_ips_and_local_paths(self):
        safe = redact_text("10.0.0.5 192.168.1.100 /home/alice/private/file.txt")
        assert "10.0.0.5" not in safe
        assert "192.168.1.100" not in safe
        assert "alice" not in safe
        assert "/home/" + REDACTED in safe

    def test_url_userinfo_and_query_secrets(self):
        password = "pass" + "word"
        text = f"https://user:{password}@example.test/path?api_key=valor-url-sintetico&next=/ok"
        safe = redact_text(text)
        assert password not in safe
        assert "valor-url-sintetico" not in safe
        assert "api_key=" + REDACTED in safe
        assert "next=/ok" in safe

    def test_private_urls_and_notebook_ids_are_removed(self):
        internal = "https://service." + "internal/private"
        notebook = "https://colab.research.google.com/drive/" + "notebook-id-privado"
        safe = redact_text(f"{internal} {notebook}")
        assert "service.internal" not in safe
        assert "/private" not in safe
        assert "notebook-id-privado" not in safe
        assert safe.count(REDACTED) == 2

    def test_raw_json_sensitive_field_is_redacted(self):
        value = "valor-json-" + "sintetico"
        safe = redact_text('{"api_key": "' + value + '"}')
        assert value not in safe
        assert REDACTED in safe

    def test_public_ipv4_is_preserved(self):
        assert redact_text("8.8.8.8") == "8.8.8.8"


class TestRedactCommand:
    def test_token_flag_separate_value(self):
        safe = redact_command("openclaw --token valor-token-sintetico")
        assert "valor-token-sintetico" not in safe
        assert REDACTED in safe

    def test_api_key_flag_equals_value(self):
        safe = redact_command("openclaw --api-key=valor-api-key-sintetico")
        assert "valor-api-key-sintetico" not in safe

    def test_authorization_bearer_and_export(self):
        command = (
            "export NVIDIA_API_KEY=formato-livre-sintetico; "
            "curl -H 'Authorization: Bearer token-com-formato-livre-sintetico' https://api.example.test"
        )
        safe = redact_command(command)
        assert "formato-livre-sintetico" not in safe
        assert "token-com-formato-livre-sintetico" not in safe
        assert "Bearer " + REDACTED in safe


class TestSanitizeForPublic:
    def test_sensitive_fields_redact_unknown_values(self):
        data = {
            "api_key": "valor-desconhecido-sintetico",
            "nested": {"client_secret": "outro-sintetico", "session_id": "id-sintetica"},
            "normal": "public value",
        }
        safe = sanitize_for_public(data)
        assert safe["api_key"] == REDACTED
        assert safe["nested"]["client_secret"] == REDACTED
        assert safe["nested"]["session_id"] == REDACTED
        assert safe["normal"] == "public value"

    def test_type_allowlist_does_not_use_repr(self):
        class PrivateObject:
            def __repr__(self):
                return "valor-privado-no-repr"

        safe = sanitize_for_public({"items": (1, "ok"), "object": PrivateObject()})
        assert safe["items"] == [1, "ok"]
        assert "PrivateObject" in safe["object"]
        assert "valor-privado-no-repr" not in str(safe)


class TestRedactEnv:
    def test_sensitive_keys_redact_even_unknown_formats(self):
        env = {
            "NVIDIA_API_KEY": "valor-sintetico-sem-prefixo",
            "MY_SECRET_TOKEN": "xxx",
            "DB_PASSWORD": "yyy",
            "NORMAL_VAR": "public",
        }
        safe = redact_env(env)
        assert safe["NVIDIA_API_KEY"] == REDACTED
        assert safe["MY_SECRET_TOKEN"] == REDACTED
        assert safe["DB_PASSWORD"] == REDACTED
        assert safe["NORMAL_VAR"] == "public"

    def test_non_sensitive_value_still_uses_text_rules(self):
        password = "sec" + "ret"
        safe = redact_env({"REMOTE": f"https://user:{password}@example.test/repo"})
        assert password not in safe["REMOTE"]


class TestRedactPath:
    def test_relative_path(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert redact_path("scripts/test.py") == "scripts/test.py"

    def test_absolute_under_cwd(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        path = tmp_path / "skill" / "test.py"
        assert redact_path(path) == "skill/test.py"

    def test_absolute_outside_cwd(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        outside = Path("/tmp") / "other" / "path" / "test.py"
        assert redact_path(outside) == "test.py"


class TestScan:
    @staticmethod
    def _strong_value() -> str:
        # Construir em runtime evita que este arquivo de teste vire um achado.
        return "valor-" + "realista-123456"

    def test_scan_real_file_reports_location_without_value(self, tmp_path, capsys):
        secret = self._strong_value()
        leak = tmp_path / "leak.txt"
        leak.write_text(f"api_key = {secret}\n", encoding="utf-8")

        findings = scan_path(tmp_path)
        assert [(item.path, item.line, item.kind) for item in findings] == [
            ("leak.txt", 1, "sensitive-assignment")
        ]
        assert main(["--scan", str(tmp_path)]) == 1
        output = capsys.readouterr().out
        assert "leak.txt:1" in output
        assert secret not in output

    def test_scan_excludes_env_binary_and_synthetic_tests(self, tmp_path):
        secret = self._strong_value()
        (tmp_path / ".env").write_text(f"API_KEY={secret}\n", encoding="utf-8")
        (tmp_path / ".env.local").write_text(f"API_KEY={secret}\n", encoding="utf-8")
        (tmp_path / "binary.png").write_bytes(b"\x00" + secret.encode())
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_synthetic.py").write_text(f"API_KEY = '{secret}'\n", encoding="utf-8")
        (tmp_path / ".env.example").write_text("API_KEY=changeme\n", encoding="utf-8")
        assert scan_path(tmp_path) == []

    def test_explicit_env_is_never_scanned(self, tmp_path, capsys):
        secret = self._strong_value()
        env = tmp_path / ".env"
        env.write_text(f"API_KEY={secret}\n", encoding="utf-8")

        assert main(["--scan", str(env)]) == 2
        captured = capsys.readouterr()
        assert secret not in captured.out
        assert secret not in captured.err

    def test_scan_detects_private_artifacts_without_values(self, tmp_path, capsys):
        local_path = "/home/" + "usuario-real/private/file.txt"
        internal_url = "https://service." + "internal/private"
        notebook_url = "https://colab.research.google.com/drive/" + "id-notebook-123"
        private_ip = "10." + "20.30.40"
        session_id = "m-s-" + "id-sessao-real-123"
        flag_value = "token-" + "realista-123"
        artifact = tmp_path / "artifact.txt"
        artifact.write_text(
            "\n".join(
                [
                    f"path={local_path}",
                    internal_url,
                    notebook_url,
                    f"ip={private_ip}",
                    f"session={session_id}",
                    f"cmd --token {flag_value}",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        findings = scan_path(tmp_path)
        assert {item.kind for item in findings} == {
            "private-path",
            "private-url",
            "private-ip",
            "session-id",
            "cli-secret",
        }
        assert main(["--scan", str(tmp_path)]) == 1
        output = capsys.readouterr().out
        for hidden in (local_path, "service.internal", "id-notebook-123", private_ip, session_id, flag_value):
            assert hidden not in output

    def test_scan_detects_private_key_text(self, tmp_path):
        marker = "-----BEGIN " + "PRIVATE KEY-----"
        key_file = tmp_path / "id_rsa"
        key_file.write_text(marker + "\nconteudo-sintetico\n", encoding="utf-8")
        findings = scan_path(tmp_path)
        assert [(item.path, item.kind) for item in findings] == [("id_rsa", "private-key")]

    def test_scan_excludes_generated_dirs(self, tmp_path):
        secret = self._strong_value()
        for directory in (
            ".git",
            "build",
            "dist",
            "target",
            "node_modules",
            "__pycache__",
            "package.egg-info",
        ):
            target = tmp_path / directory
            target.mkdir()
            (target / "leak.txt").write_text(f"API_KEY={secret}\n", encoding="utf-8")
        assert scan_path(tmp_path) == []

    def test_placeholders_and_loopback_do_not_make_scan_findings(self, tmp_path):
        (tmp_path / "example.txt").write_text(
            "token=changeme\nhttp://localhost:11434/api/tags\n", encoding="utf-8"
        )
        assert scan_path(tmp_path) == []

    def test_missing_path_is_error(self, tmp_path, capsys):
        missing = tmp_path / "missing"
        assert main(["--scan", str(missing)]) == 2
        assert str(missing) not in capsys.readouterr().err

    def test_default_self_test_is_short_and_safe(self, capsys):
        assert main([]) == 0
        output = capsys.readouterr().out
        assert "self-test: OK" in output
        assert "nvapi-" not in output
