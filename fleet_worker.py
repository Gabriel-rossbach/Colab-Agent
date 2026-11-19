#!/usr/bin/env python3
"""Adaptador JSON Lines entre o backend Java e o motor Python da fleet."""

import argparse
import asyncio
import json
import os
import re
import sys
import threading
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent
SKILL_SCRIPTS = REPO_ROOT / "skill" / "colab_agent_fleet" / "scripts"
sys.path.insert(0, str(SKILL_SCRIPTS))
load_dotenv(REPO_ROOT / ".env")

from fleet_public_safety import redact_text, sanitize_for_public

from init_fleet_plan import PlannerCancelled, gerar_plano
from run_fleet import (
    PROMOTION_GATES_DEFAULTS,
    FleetCancelled,
    aplicar_gates,
    render_summary,
    rodar_maquina,
)
from validate_fleet_plan import validar_plano_json

EVENT_FIELDS = {
    "run.state": {"state", "message"},
    "machine.state": {"machine", "state", "task", "message"},
    "task.state": {"machine", "task", "attempt", "state", "message"},
}


class JsonEmitter:
    """Serializa eventos sem misturar logs humanos no stdout do protocolo."""

    def __init__(self, run_id: str):
        self.run_id = run_id
        self._lock = threading.Lock()

    def emit(self, event_type: str, **fields) -> None:
        event = {"type": event_type, "run_id": self.run_id}
        event.update({key: value for key, value in fields.items() if value is not None})
        with self._lock:
            print(json.dumps(event, ensure_ascii=False), flush=True)

    def log(self, machine: str | None, message: object) -> None:
        self.emit("log", machine=machine, message=redact_text(str(message)))

    def logger(self, machine: str):
        return lambda message: self.log(machine, message)

    def external(self, event: dict) -> None:
        event_type = event.get("type")
        allowed = EVENT_FIELDS.get(event_type)
        if allowed is None:
            return
        fields = {key: event[key] for key in allowed if key in event}
        if "message" in fields:
            fields["message"] = redact_text(str(fields["message"]))
        self.emit(event_type, **fields)


def _prepare_run_dir(run_dir: Path) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(run_dir, 0o700)
    return run_dir


def _write_private(path: Path, content: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with open(temporary, "w", encoding="utf-8") as handle:
        handle.write(content)
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def _write_json_private(path: Path, value) -> None:
    _write_private(path, json.dumps(value, ensure_ascii=False, indent=2))


def _planner_config() -> tuple[str, str]:
    model = os.getenv("MODELO_PLANEJADOR", "gpt-oss:20b")
    flags = os.getenv("FLAGS_GPU", "--gpu t4")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,99}", model):
        raise ValueError("MODELO_PLANEJADOR contém caracteres não permitidos")
    if not re.fullmatch(r"--gpu (t4|l4|a100)", flags):
        raise ValueError("FLAGS_GPU permitidas: --gpu t4, --gpu l4 ou --gpu a100")
    return model, flags


class FleetWorker:
    def __init__(self, run_id: str, run_dir: Path, browser: bool):
        self.run_id = run_id
        self.run_dir = _prepare_run_dir(run_dir)
        self.browser = browser
        self.cancel_path = self.run_dir / "cancel.requested"
        self.emitter = JsonEmitter(run_id)

    def _check_cancelled(self) -> None:
        if self.cancel_path.exists():
            raise FleetCancelled("Cancelamento solicitado pelo backend")

    async def plan(self, request: str) -> int:
        self.emitter.emit("run.state", state="PLANNING")
        self.emitter.emit(
            "machine.state",
            machine="cpu6",
            state="RUNNING",
            message="Gerando e validando o plano",
        )
        try:
            self._check_cancelled()
            model, flags = _planner_config()
            plan = await asyncio.to_thread(
                gerar_plano,
                request,
                model,
                2,
                "cpu6",
                self.emitter.logger("cpu6"),
                flags,
                self.browser,
                self.cancel_path,
            )
            self._check_cancelled()
            if not plan or not plan.get("tasks"):
                raise RuntimeError("O planejador não retornou um plano válido")

            valid, errors = validar_plano_json(plan, request, self.browser)
            if not valid:
                raise RuntimeError("Plano inválido: " + "; ".join(errors))
            _write_json_private(self.run_dir / "plan.json", plan)
            self.emitter.emit("plan.ready", plan=sanitize_for_public(plan))
            self.emitter.emit("machine.state", machine="cpu6", state="COMPLETED")
            self.emitter.emit("run.state", state="WAITING_CONFIRMATION")
            return 0
        except (FleetCancelled, PlannerCancelled):
            self.emitter.emit("machine.state", machine="cpu6", state="CANCELLED")
            self.emitter.emit("run.state", state="CANCELLED")
            return 4
        except Exception as exc:
            self.emitter.emit("machine.state", machine="cpu6", state="FAILED")
            self.emitter.emit("run.state", state="FAILED", message=redact_text(str(exc)))
            return 1

    async def _run_machine(self, machine: str, tasks: list[dict], api_key: str):
        try:
            return await rodar_maquina(
                machine,
                tasks,
                api_key,
                self.emitter.logger(machine),
                use_browser=self.browser,
                event_callback=self.emitter.external,
                cancel_path=self.cancel_path,
            )
        except FleetCancelled:
            self.emitter.emit("machine.state", machine=machine, state="CANCELLED")
            raise
        except Exception as exc:
            message = redact_text(str(exc))
            self.emitter.emit(
                "machine.state",
                machine=machine,
                state="FAILED",
                message=message,
            )
            return [
                {
                    "maquina": machine,
                    "task": task["task"],
                    "prompt": task["prompt"],
                    "sucesso": False,
                    "erro": str(exc),
                    "tentativas": 0,
                }
                for task in tasks
            ]

    def _save_artifacts(self, plan: dict, results: list[dict], gates: dict) -> None:
        # O backend serve estes arquivos após autenticação: redação é obrigatória,
        # inclusive quando uma saída remota ecoar acidentalmente uma credencial.
        public_results = sanitize_for_public(results)
        _write_json_private(self.run_dir / "results.json", public_results)
        _write_json_private(self.run_dir / "gates.json", gates)
        summary = render_summary(
            public_results,
            gates,
            redact_text(plan.get("request", "")),
        )
        _write_private(self.run_dir / "summary.md", summary)

    async def execute(self) -> int:
        try:
            self._check_cancelled()
            with open(self.run_dir / "plan.json", "r", encoding="utf-8") as handle:
                plan = json.load(handle)
            valid, errors = validar_plano_json(plan, plan.get("request", ""), self.browser)
            if not valid:
                raise RuntimeError("Plano inválido: " + "; ".join(errors))
            api_key = os.getenv("NVIDIA_API_KEY", "")
            if not api_key:
                raise RuntimeError("NVIDIA_API_KEY não definida no worker")

            tasks = plan["tasks"]
            total_tasks = len(tasks)
            by_cpu = defaultdict(list)
            for task in tasks:
                by_cpu[task["cpu"]].append(task)

            self.emitter.emit("run.state", state="EXECUTING")
            groups = await asyncio.gather(
                *(
                    self._run_machine(f"cpu{cpu}", machine_tasks, api_key)
                    for cpu, machine_tasks in sorted(by_cpu.items())
                ),
                return_exceptions=True,
            )

            cancelled = any(isinstance(group, FleetCancelled) for group in groups)
            results = []
            for group in groups:
                if isinstance(group, FleetCancelled):
                    continue
                if isinstance(group, Exception):
                    raise group
                results.extend(group)
            results.sort(key=lambda item: (item.get("maquina", ""), item.get("task", 0)))

            successful = sum(1 for result in results if result.get("sucesso") is True)
            gates = aplicar_gates(results, PROMOTION_GATES_DEFAULTS)
            self._save_artifacts(plan, results, gates)
            result = {
                "totalTasks": total_tasks,
                "completedTasks": len(results),
                "successful": successful,
                "gatePass": gates["gate_pass"],
            }
            self.emitter.emit("run.result", result=result)
            if cancelled:
                self.emitter.emit("run.state", state="CANCELLED")
                return 4
            self.emitter.emit("run.state", state="COMPLETED")
            return 0
        except FleetCancelled:
            self.emitter.emit(
                "run.result",
                result={"totalTasks": 0, "completedTasks": 0, "successful": 0},
            )
            self.emitter.emit("run.state", state="CANCELLED")
            return 4
        except Exception as exc:
            self.emitter.emit("run.state", state="FAILED", message=redact_text(str(exc)))
            return 1


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Worker JSON Lines da Colab Agent Fleet")
    parser.add_argument("command", choices=("plan", "execute"))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--request")
    parser.add_argument("--browser", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", args.run_id):
        parser.error("run-id inválido")
    if args.command == "plan":
        if args.request is None or not 3 <= len(args.request.strip()) <= 10000:
            parser.error("request deve ter entre 3 e 10000 caracteres")
    return args


def main() -> None:
    args = _parse_args()
    worker = FleetWorker(args.run_id, args.run_dir, args.browser)
    try:
        if args.command == "plan":
            code = asyncio.run(worker.plan(args.request.strip()))
        else:
            code = asyncio.run(worker.execute())
    except Exception as exc:
        worker.emitter.emit("run.state", state="FAILED", message=redact_text(str(exc)))
        code = 1
    raise SystemExit(code)


if __name__ == "__main__":
    main()
