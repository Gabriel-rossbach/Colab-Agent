import asyncio
import os
import sys
from collections import defaultdict
from pathlib import Path

# Carrega .env antes de tudo
from dotenv import load_dotenv
load_dotenv()

from textual.app import App, ComposeResult
from textual.containers import Grid
from textual.widgets import Header, Footer, RichLog, Input
from textual import work
from textual.events import Click

# Adiciona skill ao path para imports locais
SKILL_ROOT = Path(__file__).parent / "skill" / "colab_agent_fleet"
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from init_fleet_plan import gerar_plano
from run_fleet import rodar_maquina
from validate_fleet_plan import etiquetas_esperadas


class MaximizableLog(RichLog):
    def on_click(self, event: Click) -> None:
        is_maximized = self.has_class("maximized")
        all_logs = self.app.query(MaximizableLog)
        if is_maximized:
            for log in all_logs:
                log.remove_class("maximized")
                log.remove_class("hidden")
        else:
            for log in all_logs:
                if log == self:
                    log.add_class("maximized")
                    log.remove_class("hidden")
                else:
                    log.add_class("hidden")
                    log.remove_class("maximized")


class ColabOrchestrator(App):
    CSS = """
    Input {
        margin: 0 1;
    }
    Grid {
        grid-size: 2;
        grid-rows: 1fr;
        grid-gutter: 1 2;
        height: 1fr;
    }
    MaximizableLog {
        border: solid #00ff00;
        height: 100%;
        background: #1e1e1e;
    }
    MaximizableLog.maximized {
        column-span: 2;
    }
    MaximizableLog.hidden {
        display: none;
    }
    """

    missao_em_andamento: bool = False
    aguardando_confirmacao: bool = False
    continuar: bool = False
    confirmacao: asyncio.Event | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Input(
            placeholder="Descreva o pedido e aperte Enter. Depois confirme com 'continuar'.",
            id="entrada",
        )
        with Grid():
            for i in range(1, 7):
                yield MaximizableLog(id=f"log-cpu{i}", highlight=True, wrap=True)
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#entrada", Input).focus()
        self.query_one("#log-cpu6", MaximizableLog).write(
            "Pronto. Descreva o pedido. O cpu6 monta o plano e você confirma antes de ligar as máquinas."
        )

    def on_input_submitted(self, event: Input.Submitted) -> None:
        log_cpu6 = self.query_one("#log-cpu6", MaximizableLog)
        texto = event.value.strip()

        # Resposta à confirmação do plano
        if self.aguardando_confirmacao:
            event.input.value = ""
            self.continuar = texto.lower() in ("continuar", "sim", "s")
            self.aguardando_confirmacao = False
            self.confirmacao.set()
            return

        if self.missao_em_andamento:
            log_cpu6.write("⏳ Ainda há uma missão rodando. Espere terminar antes de enviar outra.")
            return
        if not texto:
            log_cpu6.write("❌ Digite um pedido.")
            return

        event.input.value = ""
        self.missao_em_andamento = True
        self.orquestrar(texto)

    @work(exclusive=False)
    async def orquestrar(self, pedido: str) -> None:
        log_cpu6 = self.query_one("#log-cpu6", MaximizableLog)
        try:
            # Usa gerar_plano do skill com planner remoto no cpu6
            modelo = os.getenv("MODELO_PLANEJADOR", "gpt-oss:20b")
            flags_gpu = os.getenv("FLAGS_GPU", "--gpu t4")
            plano_obj = await asyncio.to_thread(
                gerar_plano, pedido, modelo, 2, "cpu6", log_cpu6.write, flags_gpu
            )

            if not plano_obj:
                log_cpu6.write("❌ Falha ao gerar plano válido.")
                return

            tasks = plano_obj.get("tasks", [])
            if not tasks:
                log_cpu6.write("❌ Plano vazio.")
                return

            log_cpu6.write("\n📋 Plano (confira antes de ligar):")
            for t in tasks:
                log_cpu6.write(f"   [cpu{t['cpu']}] [tarefa{t['task']}] {t['prompt'][:110]}...")

            maquinas_usadas = sorted(set(t['cpu'] for t in tasks))
            log_cpu6.write(
                f"\n⏸ Vou ligar {len(maquinas_usadas)} máquina(s). Digite 'continuar' para iniciar, "
                "ou outra coisa para cancelar."
            )

            self.confirmacao = asyncio.Event()
            self.aguardando_confirmacao = True
            await self.confirmacao.wait()
            if not self.continuar:
                log_cpu6.write("🛑 Cancelado. Nenhuma máquina de execução foi ligada.")
                return

            # Agrupa tasks por máquina
            itens_por_cpu = defaultdict(list)
            for t in tasks:
                itens_por_cpu[t['cpu']].append(t)

            log_cpu6.write("\n📤 Enviando as tarefas...")
            chave_nvidia = os.getenv("NVIDIA_API_KEY", "")
            if not chave_nvidia:
                log_cpu6.write("❌ NVIDIA_API_KEY não definida no ambiente.")
                return

            resultados = await asyncio.gather(
                *(rodar_maquina(f"cpu{cpu}", itens, chave_nvidia, self.query_one(f"#log-cpu{cpu}", MaximizableLog).write) for cpu, itens in sorted(itens_por_cpu.items())),
                return_exceptions=True,
            )

            confirmadas = 0
            total = len(tasks)
            for (cpu, itens), resultado in zip(sorted(itens_por_cpu.items()), resultados):
                if isinstance(resultado, Exception):
                    log_cpu6.write(f"❌ cpu{cpu} falhou: {resultado}")
                else:
                    confirmadas += sum(1 for r in resultado if r.get("sucesso"))
            log_cpu6.write(f"\n🏁 Fim: {confirmadas}/{total} tarefas confirmadas.")
        except Exception as e:
            log_cpu6.write(f"❌ Erro: {e}")
        finally:
            self.aguardando_confirmacao = False
            self.missao_em_andamento = False


if __name__ == "__main__":
    ColabOrchestrator().run()