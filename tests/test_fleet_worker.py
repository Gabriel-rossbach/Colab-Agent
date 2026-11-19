import asyncio
import json

import fleet_worker


VALID_PLAN = {
    "request": "pesquise carros rápidos",
    "tasks": [
        {
            "cpu": 1,
            "task": 1,
            "prompt": "Use web_search para pesquisar carros rápidos. Traga em português.",
        }
    ],
}


def events(capsys):
    return [json.loads(line) for line in capsys.readouterr().out.splitlines()]


def test_plan_emite_protocolo_e_salva_plano(monkeypatch, tmp_path, capsys):
    observed = {}

    def fake_plan(*args):
        observed["args"] = args
        return VALID_PLAN

    monkeypatch.setattr(fleet_worker, "gerar_plano", fake_plan)
    monkeypatch.setenv("FLAGS_GPU", "--gpu t4")
    worker = fleet_worker.FleetWorker("teste123", tmp_path / "run", False)

    code = asyncio.run(worker.plan(VALID_PLAN["request"]))
    emitted = events(capsys)

    assert code == 0
    assert observed["args"][6] is False
    assert observed["args"][7] == worker.cancel_path
    assert json.loads((worker.run_dir / "plan.json").read_text()) == VALID_PLAN
    assert any(event["type"] == "plan.ready" for event in emitted)
    assert emitted[-1]["state"] == "WAITING_CONFIRMATION"
    assert (worker.run_dir / "plan.json").stat().st_mode & 0o777 == 0o600


def test_execute_emite_estados_e_artefatos(monkeypatch, tmp_path, capsys):
    worker = fleet_worker.FleetWorker("teste123", tmp_path / "run", True)
    fleet_worker._write_json_private(worker.run_dir / "plan.json", VALID_PLAN)
    monkeypatch.setenv("NVIDIA_API_KEY", "valor-sintetico")
    observed = {}

    async def fake_run(machine, tasks, key, callback, **kwargs):
        observed.update(kwargs)
        callback("execução sintética")
        kwargs["event_callback"]({
            "type": "machine.state",
            "machine": machine,
            "state": "RUNNING",
        })
        return [{
            "maquina": machine,
            "task": tasks[0]["task"],
            "prompt": tasks[0]["prompt"],
            "sucesso": True,
            "saida_completa": "resultado sintético",
            "tentativas": 1,
        }]

    monkeypatch.setattr(fleet_worker, "rodar_maquina", fake_run)
    code = asyncio.run(worker.execute())
    emitted = events(capsys)

    assert code == 0
    assert observed["use_browser"] is True
    assert observed["cancel_path"] == worker.cancel_path
    assert emitted[-1]["state"] == "COMPLETED"
    result = json.loads((worker.run_dir / "results.json").read_text())
    assert result[0]["saida_completa"] == "resultado sintético"
    assert (worker.run_dir / "summary.md").exists()


def test_artefatos_nao_expoem_chave_em_saida_completa(monkeypatch, tmp_path, capsys):
    worker = fleet_worker.FleetWorker("teste123", tmp_path / "run", False)
    fleet_worker._write_json_private(worker.run_dir / "plan.json", VALID_PLAN)
    monkeypatch.setenv("NVIDIA_API_KEY", "valor-sintetico")

    async def fake_run(*args, **kwargs):
        return [{
            "maquina": "cpu1",
            "task": 1,
            "prompt": "prompt sintético",
            "sucesso": True,
            "saida_completa": "erro remoto: NVIDIA_API_KEY=nvapi-segredo-sintetico",
            "tentativas": 1,
        }]

    monkeypatch.setattr(fleet_worker, "rodar_maquina", fake_run)
    assert asyncio.run(worker.execute()) == 0
    stored = (worker.run_dir / "results.json").read_text(encoding="utf-8")
    assert "nvapi-segredo-sintetico" not in stored
    assert "REDACTED" in stored
    capsys.readouterr()


def test_execute_cancelado_emite_estado_terminal(monkeypatch, tmp_path, capsys):
    worker = fleet_worker.FleetWorker("teste123", tmp_path / "run", False)
    fleet_worker._write_json_private(worker.run_dir / "plan.json", VALID_PLAN)
    monkeypatch.setenv("NVIDIA_API_KEY", "valor-sintetico")

    async def fake_run(*args, **kwargs):
        kwargs["cancel_path"].write_text("cancel", encoding="utf-8")
        raise fleet_worker.FleetCancelled("cancelamento sintético")

    monkeypatch.setattr(fleet_worker, "rodar_maquina", fake_run)
    code = asyncio.run(worker.execute())
    emitted = events(capsys)

    assert code == 4
    assert emitted[-1]["state"] == "CANCELLED"
    assert (worker.run_dir / "results.json").exists()
