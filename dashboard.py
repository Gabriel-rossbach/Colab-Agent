import asyncio

from textual.app import App, ComposeResult
from textual.containers import Grid
from textual.widgets import Header, Footer, RichLog, Input
from textual import work
from textual.events import Click

from colab_runner import executar_agente, planejar
from plano import linhas_do_plano


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
            plano = await planejar(pedido, log_cpu6.write)
            if plano is None:
                log_cpu6.write("❌ Nenhuma máquina foi ligada.")
                return

            log_cpu6.write("\n📋 Plano (confira antes de ligar):")
            for cpu, n, prompt in linhas_do_plano(plano):
                log_cpu6.write(f"   [cpu{cpu}] [tarefa{n}] {prompt[:110]}...")
            log_cpu6.write(
                f"\n⏸ Vou ligar {len(plano)} máquina(s). Digite 'continuar' para iniciar, "
                "ou outra coisa para cancelar."
            )

            self.confirmacao = asyncio.Event()
            self.aguardando_confirmacao = True
            await self.confirmacao.wait()
            if not self.continuar:
                log_cpu6.write("🛑 Cancelado. Nenhuma máquina foi ligada além do cpu6.")
                return

            itens_por_cpu = sorted(plano.items())
            log_cpu6.write("\n📤 Enviando as tarefas...")
            resultados = await asyncio.gather(
                *(self.rodar_maquina(cpu, itens) for cpu, itens in itens_por_cpu),
                return_exceptions=True,
            )

            confirmadas = 0
            total = 0
            for (cpu, itens), resultado in zip(itens_por_cpu, resultados):
                total += len(itens)
                if isinstance(resultado, Exception):
                    log_cpu6.write(f"❌ cpu{cpu} falhou: {resultado}")
                else:
                    confirmadas += resultado
            log_cpu6.write(f"\n🏁 Fim: {confirmadas}/{total} tarefas confirmadas.")
        except Exception as e:
            log_cpu6.write(f"❌ Erro: {e}")
        finally:
            self.aguardando_confirmacao = False
            self.missao_em_andamento = False

    async def rodar_maquina(self, cpu: int, itens: list) -> int:
        """Roda as tarefas de uma máquina uma depois da outra. Devolve quantas foram confirmadas."""
        log_widget = self.query_one(f"#log-cpu{cpu}", MaximizableLog)
        confirmadas = 0
        for n, prompt in itens:
            log_widget.write(f"\n▶ tarefa {n}")
            if await executar_agente(f"cpu{cpu}", prompt, log_widget.write):
                confirmadas += 1
        return confirmadas


if __name__ == "__main__":
    ColabOrchestrator().run()