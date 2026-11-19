import asyncio

import pytest

from skill.colab_agent_fleet.scripts import init_fleet_plan


def test_planner_respeita_cancelamento_antes_de_chamar_colab(tmp_path, monkeypatch):
    cancel = tmp_path / "cancel.requested"
    cancel.write_text("cancel", encoding="utf-8")
    chamadas = 0

    async def factory(*args, **kwargs):
        nonlocal chamadas
        chamadas += 1
        raise AssertionError("Nenhum subprocesso deveria ser criado")

    monkeypatch.setattr(asyncio, "create_subprocess_shell", factory)
    with pytest.raises(init_fleet_plan.PlannerCancelled):
        init_fleet_plan.gerar_plano(
            "pesquise carros rápidos",
            "gpt-oss:20b",
            planner_machine="cpu6",
            flags_gpu="--gpu t4",
            cancel_path=cancel,
        )
    assert chamadas == 0


def test_planner_remoto_cancela_e_tenta_limpeza(tmp_path, monkeypatch):
    cancel = tmp_path / "cancel.requested"
    processos = []

    class FakeStdin:
        def write(self, content):
            pass

        def close(self):
            pass

    class FakeStdout:
        async def readline(self):
            cancel.write_text("cancel", encoding="utf-8")
            await asyncio.sleep(2)
            return b""

    class FakeProcess:
        def __init__(self):
            self.stdin = FakeStdin()
            self.stdout = FakeStdout()
            self.returncode = None
            self.terminated = False

        async def wait(self):
            self.returncode = 0 if self.terminated else self.returncode
            return self.returncode

        def terminate(self):
            self.terminated = True
            self.returncode = -15

        def kill(self):
            self.returncode = -9

    async def sem_provisionamento(*args, **kwargs):
        return None

    async def factory(*args, **kwargs):
        process = FakeProcess()
        processos.append(process)
        return process

    monkeypatch.setattr(init_fleet_plan, "garantir_maquina_remota", sem_provisionamento)
    monkeypatch.setattr(asyncio, "create_subprocess_shell", factory)

    with pytest.raises(init_fleet_plan.PlannerCancelled):
        asyncio.run(
            init_fleet_plan.chamar_ollama_remoto(
                "cpu6",
                init_fleet_plan.montar_mensagens("pesquise carros"),
                cancel_path=cancel,
            )
        )

    assert processos[0].terminated is True
    assert len(processos) == 2  # sessão principal + limpeza remota de melhor esforço


def test_flags_gpu_nao_aceitam_comando_arbitrario():
    with pytest.raises(ValueError):
        init_fleet_plan.gerar_plano(
            "pesquise carros",
            "gpt-oss:20b",
            flags_gpu="--gpu t4; comando-invalido",
        )


def test_instrucao_do_planner_respeita_toggle_browser():
    disabled = init_fleet_plan.montar_mensagens("pesquise carros", False)[1]["content"]
    enabled = init_fleet_plan.montar_mensagens("pesquise carros", True)[1]["content"]
    assert "Browser DESABILITADO" in disabled
    assert "Browser HABILITADO" in enabled
