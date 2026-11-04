# Dashboard TUI Reference

## Architecture

The TUI (`dashboard.py`) uses **Textual** for a terminal-based orchestration UI:

```
┌─────────────────────────────────────────────────────────────────┐
│ Header (clock)                                                   │
├─────────────────────────────────────────────────────────────────┤
│ Input: "Describe request... Enter to plan, 'continuar' to launch"│
├──────────────┬──────────────┬──────────────┬────────────────────┤
│   cpu1 log   │   cpu2 log   │   cpu3 log   │      cpu6 log      │
│  (click to   │  (click to   │  (click to   │   (planner logs)   │
│  maximize)   │  maximize)   │  maximize)   │                    │
├──────────────┼──────────────┼──────────────┼────────────────────┤
│ Footer (keybinds)                                             │
└─────────────────────────────────────────────────────────────────┘
```

## Key Components

### MaximizableLog Widget
```python
class MaximizableLog(RichLog):
    def on_click(self, event: Click) -> None:
        # Toggle maximized: clicked log spans 2 columns, others hidden
```

### State Machine
```python
missao_em_andamento: bool = False      # Fleet running?
aguardando_confirmacao: bool = False   # Waiting for 'continuar'?
confirmacao: asyncio.Event             # Signal to proceed
```

### Flow

1. **Input submitted** → `orquestrar(pedido)` starts
2. **Planner** (cpu6) → generates plan → logs to cpu6 panel
3. **Plan displayed** → user sees task breakdown
4. **Confirmation** → input waits for "continuar"/"sim"/"s"
5. **Launch** → `asyncio.gather` runs `rodar_maquina` per CPU
6. **Results** → each machine logs to its panel; cpu6 shows summary
7. **Done** → state reset; ready for next request

## Keybinds

| Key | Action |
|-----|--------|
| Click log | Maximize/restore that log panel |
| Enter (input) | Submit request or confirmation |
| Ctrl+C | Quit app |

## Extending the Dashboard

### Add New Machine Panel
```python
# In compose():
for i in range(1, 8):  # was 7, now 8
    yield MaximizableLog(id=f"log-cpu{i}")
```

### Add Custom Widget
```python
from textual.widgets import Static

class FleetStatus(Static):
    def update_status(self, machine: str, status: str):
        self.update(f"{machine}: {status}")
```

### Async Log Streaming
```python
async def log_stream(self, machine: str, async_gen):
    log = self.query_one(f"#log-cpu{machine}", MaximizableLog)
    async for line in async_gen:
        log.write(line)
```

## Testing TUI (Headless)

```python
# tests/test_dashboard.py
from textual.testing import AppDriver

async def test_orquestrar():
    async with AppDriver(ColabOrchestrator()) as pilot:
        await pilot.press("pesquise 3 carros")
        await pilot.press("enter")
        # Wait for plan
        await pilot.wait_for_animation()
        assert "Plano" in pilot.app.query_one("#log-cpu6").render()
```