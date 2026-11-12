# Referência da Dashboard TUI

## Arquitetura

A TUI (`dashboard.py`) usa **Textual** para uma UI de orquestração no terminal:

```
┌─────────────────────────────────────────────────────────────────┐
│ Header (relógio)                                                 │
├─────────────────────────────────────────────────────────────────┤
│ Input: "Descreva o pedido... Enter para plano, 'continuar' p/ launching"│
├──────────────┬──────────────┬──────────────┬────────────────────┤
│   log cpu1   │   log cpu2   │   log cpu3   │      log cpu6      │
│  (clique p/  │  (clique p/  │  (clique p/  │   (logs do planner)│
│  maximizar) │  maximizar) │  maximizar) │                    │
├──────────────┼──────────────┼──────────────┼────────────────────┤
│ Footer (atalhos de teclado)                                      │
└─────────────────────────────────────────────────────────────────┘
```

## Componentes-chave

### Widget MaximizableLog
```python
class MaximizableLog(RichLog):
    def on_click(self, event: Click) -> None:
        # Alterna maximizado: o log clicado ocupa 2 colunas, os outros ficam escondidos
```

### Máquina de estados
```python
missao_em_andamento: bool = False      # Fleet rodando?
aguardando_confirmacao: bool = False   # Esperando 'continuar'?
confirmacao: asyncio.Event             # Sinal para prosseguir
```

### Fluxo

1. **Input enviado** → `orquestrar(pedido)` inicia
2. **Planejador** (cpu6) → gera o plano → loga no painel do cpu6
3. **Plano exibido** → usuário vê o detalhamento das tarefas
4. **Confirmação** → input espera por "continuar"/"sim"/"s"
5. **Disparo** → `asyncio.gather` roda `rodar_maquina` por CPU
6. **Resultados** → cada máquina loga no seu painel; cpu6 mostra o resumo
7. **Fim** → estado reseta; pronto para o próximo pedido

## Atalhos de teclado

| Tecla | Ação |
|-------|------|
| Clique no log | Maximiza/restaura aquele painel de log |
| Enter (no input) | Envia o pedido ou a confirmação |
| Ctrl+C | Sai do app |

## Estendendo o dashboard

### Adicionar novo painel de máquina
```python
# Em compose():
for i in range(1, 8):  # era 7, agora 8
    yield MaximizableLog(id=f"log-cpu{i}")
```

### Adicionar widget customizado
```python
from textual.widgets import Static

class FleetStatus(Static):
    def update_status(self, machine: str, status: str):
        self.update(f"{machine}: {status}")
```

### Streaming assíncrono de log
```python
async def log_stream(self, machine: str, async_gen):
    log = self.query_one(f"#log-cpu{machine}", MaximizableLog)
    async for line in async_gen:
        log.write(line)
```

## Testando a TUI (headless)

```python
# tests/test_dashboard.py
from textual.testing import AppDriver

async def test_orquestrar():
    async with AppDriver(ColabOrchestrator()) as pilot:
        await pilot.press("pesquise 3 carros")
        await pilot.press("enter")
        # Espera o plano
        await pilot.wait_for_animation()
        assert "Plano" in pilot.app.query_one("#log-cpu6").render()
```
