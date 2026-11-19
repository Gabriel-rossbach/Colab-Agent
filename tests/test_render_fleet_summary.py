import json
from pathlib import Path

import pytest

from skill.colab_agent_fleet.scripts import render_fleet_summary as summary
from skill.colab_agent_fleet.scripts.fleet_public_safety import REDACTED


def valid_gates():
    return {
        "gate_pass": False,
        "total_tasks": 1,
        "successful": 0,
        "details": {"actual_ratio": 0.0},
    }


def valid_result(**overrides):
    result = {
        "maquina": "cpu1",
        "task": 1,
        "prompt": "Use web_search para pesquisar.",
        "sucesso": False,
    }
    result.update(overrides)
    return result


def test_render_redacts_request_and_prompt_and_escapes_injection():
    request = "api_key=valor-request-sintetico [link](https://evil.test)"
    result = valid_result(
        prompt="api_key=valor-prompt-sintetico ![img](https://evil.test/x) <script>alert(1)</script>"
    )
    markdown = summary.render([result], valid_gates(), request)

    assert "valor-request-sintetico" not in markdown
    assert "valor-prompt-sintetico" not in markdown
    assert "[link](" not in markdown
    assert "![img](" not in markdown
    assert "<script>" not in markdown
    assert "&lt;script&gt;" in markdown
    assert "https://evil.test" not in markdown  # ':' é escapado para evitar autolink
    assert "not a guarantee" in markdown
    assert "All secrets" not in markdown


def test_render_does_not_include_raw_outputs_and_counts_only_bool_true():
    result = valid_result(sucesso=True, saida_bruta="raw-output-sintetico")
    result["output"] = "outro-output-sintetico"
    markdown = summary.render([result], valid_gates(), "request")
    assert "raw-output-sintetico" not in markdown
    assert "outro-output-sintetico" not in markdown
    assert "✅ **tarefa1**" in markdown
    assert "cpu1" in markdown


def test_escape_markdown_prevents_markdown_html_and_autolink():
    escaped = summary.escape_markdown("[x](https://evil.test) <b>negrito</b> ![i](x)")
    assert "[x](" not in escaped
    assert "![i](" not in escaped
    assert "<b>" not in escaped
    assert "https://evil.test" not in escaped
    assert "\\[" in escaped and "\\!" in escaped


@pytest.mark.parametrize(
    "results,gates,request_text",
    [
        ("not-a-list", valid_gates(), ""),
        ([valid_result(sucesso="true")], valid_gates(), ""),
        ([valid_result()], "not-a-dict", ""),
        ([valid_result()], {**valid_gates(), "gate_pass": "false"}, ""),
        ([valid_result(prompt=123)], valid_gates(), ""),
    ],
)
def test_render_rejects_invalid_structure_and_types(results, gates, request_text):
    with pytest.raises((TypeError, ValueError)):
        summary.render(results, gates, request_text)


def test_carregar_jsonl_validates_objects_and_json(tmp_path):
    results = tmp_path / "results.jsonl"
    results.write_text("[]\n", encoding="utf-8")
    with pytest.raises(ValueError, match="objeto"):
        summary.carregar_jsonl(results)

    results.write_text("not-json\n", encoding="utf-8")
    with pytest.raises(ValueError, match="linha 1"):
        summary.carregar_jsonl(results)


def test_cli_writes_only_sanitized_summary(tmp_path):
    results = tmp_path / "results.jsonl"
    gates = tmp_path / "gates.json"
    output = tmp_path / "public" / "summary.md"
    results.write_text(json.dumps(valid_result(prompt="api_key=valor-cli-sintetico")) + "\n", encoding="utf-8")
    gates.write_text(json.dumps(valid_gates()), encoding="utf-8")

    assert summary.main(
        [
            "--results",
            str(results),
            "--gates",
            str(gates),
            "--request",
            "api_key=valor-request-cli-sintetico",
            "--out",
            str(output),
        ]
    ) == 0
    content = output.read_text(encoding="utf-8")
    assert "valor-cli-sintetico" not in content
    assert "valor-request-cli-sintetico" not in content
    assert "REDACTED" in content


def test_script_has_valid_python_shebang():
    first_line = Path(summary.__file__).read_text(encoding="utf-8").splitlines()[0]
    assert first_line == "#!/usr/bin/env python3"
