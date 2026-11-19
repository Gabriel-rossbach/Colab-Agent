import asyncio
import base64

import pytest

from skill.colab_agent_fleet.scripts import run_fleet


class FakeStdin:
    def __init__(self):
        self.content = b""

    def write(self, content):
        self.content += content

    def close(self):
        pass


class FakeStdout:
    def __init__(self, lines):
        self.lines = list(lines)

    async def readline(self):
        if self.lines:
            return self.lines.pop(0)
        return b""


class FakeProcess:
    def __init__(self, lines, returncode=0):
        self.stdin = FakeStdin()
        self.stdout = FakeStdout(lines)
        self.returncode = None
        self.expected_returncode = returncode

    async def wait(self):
        if self.returncode is None:
            self.returncode = self.expected_returncode
        return self.returncode

    def terminate(self):
        self.returncode = -15

    def kill(self):
        self.returncode = -9


def task():
    return {"cpu": 1, "task": 1, "prompt": "Use web_search para testar. Traga em português."}


def test_eventos_e_saida_completa(monkeypatch):
    async def sem_provisionamento(*args, **kwargs):
        return None

    process = FakeProcess([b"inicio\n", b"x" * 2500 + b"\n", b"MISSAO_OK\n"])
    monkeypatch.setattr(run_fleet, "garantir_maquina", sem_provisionamento)

    async def factory(*args, **kwargs):
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_shell", factory)
    events = []
    results = asyncio.run(
        run_fleet.rodar_maquina(
            "cpu1",
            [task()],
            "chave-sintetica",
            lambda message: None,
            event_callback=events.append,
        )
    )

    assert results[0]["sucesso"] is True
    assert results[0]["saida_completa"].startswith("inicio\n")
    assert len(results[0]["saida_bruta"]) == 2000
    assert any(
        event["type"] == "task.state" and event["state"] == "COMPLETED"
        for event in events
    )


@pytest.mark.parametrize("use_browser,chamadas_esperadas", [(True, 1), (False, 2)])
def test_retry_nao_repete_browser(monkeypatch, use_browser, chamadas_esperadas):
    async def sem_provisionamento(*args, **kwargs):
        return None

    monkeypatch.setattr(run_fleet, "garantir_maquina", sem_provisionamento)
    chamadas = 0

    async def factory(*args, **kwargs):
        nonlocal chamadas
        chamadas += 1
        return FakeProcess([b"falhou\n"], returncode=1)

    monkeypatch.setattr(asyncio, "create_subprocess_shell", factory)
    results = asyncio.run(
        run_fleet.rodar_maquina(
            "cpu1",
            [task()],
            "chave-sintetica",
            lambda message: None,
            use_browser=use_browser,
        )
    )

    assert chamadas == chamadas_esperadas
    assert results[0]["sucesso"] is False


def test_cancelamento_antes_de_iniciar(tmp_path):
    cancel = tmp_path / "cancel.requested"
    cancel.write_text("cancel", encoding="utf-8")
    with pytest.raises(run_fleet.FleetCancelled):
        asyncio.run(
            run_fleet.rodar_maquina(
                "cpu1",
                [task()],
                "chave-sintetica",
                lambda message: None,
                cancel_path=cancel,
            )
        )


def test_chave_nao_e_interpolada_no_shell():
    chave = "chave-com-'aspa'-sintetica"
    script = run_fleet.gerar_comando_bash("prompt de teste", chave)
    assert chave not in script
    assert base64.b64encode(chave.encode()).decode() in script


def test_comunicacao_de_provisionamento_aceita_cancelamento(tmp_path):
    cancel = tmp_path / "cancel.requested"
    cancel.write_text("cancel", encoding="utf-8")

    class FakeCommunicationProcess:
        def __init__(self):
            self.returncode = None
            self.finished = asyncio.Event()

        async def communicate(self):
            await self.finished.wait()
            return b"", b""

        def terminate(self):
            self.returncode = -15
            self.finished.set()

        def kill(self):
            self.returncode = -9
            self.finished.set()

        async def wait(self):
            return self.returncode

    process = FakeCommunicationProcess()
    with pytest.raises(run_fleet.FleetCancelled):
        asyncio.run(
            run_fleet._comunicar_com_timeout(
                process,
                60,
                "teste sintético",
                cancel,
            )
        )
    assert process.returncode == -15
