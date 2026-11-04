#!/usr/bin/env python3
"""
CLI runner for Colab Agent Fleet - Automation/Debug mode.
Runs without TUI, uses mock prompt from agent config, shows all logs in terminal.
"""
import asyncio
import os
import sys
import yaml
from pathlib import Path
from collections import defaultdict

# Carrega .env
from dotenv import load_dotenv
load_dotenv()

# Adiciona skill ao path
SKILL_ROOT = Path(__file__).parent / "skill" / "colab_agent_fleet"
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from init_fleet_plan import gerar_plano
from run_fleet import rodar_maquina
from validate_fleet_plan import etiquetas_esperadas


def load_agent_config():
    """Carrega config do agente (openai.yaml)"""
    config_path = SKILL_ROOT / "agents" / "openai.yaml"
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)


def print_log(prefix: str, msg: str):
    """Print log with prefix to terminal"""
    print(f"[{prefix}] {msg}", flush=True)


async def run_automation_mode(config: dict):
    """Executa em modo automação (sem TUI, com prompt mockado)"""
    auto = config.get("automation", {})
    enabled = auto.get("enabled", False)
    mock_prompt = auto.get("mock_prompt", "pesquise 5 plugins do OpenClaw e traga em português")
    timeout_minutes = auto.get("timeout_minutes", 25)
    timeout_seconds = timeout_minutes * 60
    
    if not enabled:
        print("❌ Automation não habilitado no openai.yaml (automation.enabled: true)")
        return
    
    print("=" * 70)
    print("🤖 MODO AUTOMAÇÃO ATIVADO")
    print("=" * 70)
    print(f"📝 Prompt mockado: {mock_prompt}")
    print()
    
    # Gera plano no cpu6 (planner)
    print("🧠 Gerando plano no cpu6 (planner)...")
    modelo = os.getenv("MODELO_PLANEJADOR", "gpt-oss:20b")
    flags_gpu = os.getenv("FLAGS_GPU", "--gpu t4")
    
    def log_cpu6(msg: str):
        print_log("cpu6", msg)
    
    plano_obj = await asyncio.to_thread(
        gerar_plano, mock_prompt, modelo, 4, "cpu6", log_cpu6, flags_gpu
    )
    
    if not plano_obj:
        print("❌ Falha ao gerar plano válido.")
        return
    
    tasks = plano_obj.get("tasks", [])
    if not tasks:
        print("❌ Plano vazio.")
        return
    
    print("\n📋 Plano gerado:")
    for t in tasks:
        print(f"   [cpu{t['cpu']}] [tarefa{t['task']}] {t['prompt'][:100]}...")
    
    maquinas_usadas = sorted(set(t['cpu'] for t in tasks))
    print(f"\n📤 Executando em {len(maquinas_usadas)} máquina(s): {maquinas_usadas}")
    print("-" * 70)
    
    # Agrupa tasks por máquina
    itens_por_cpu = defaultdict(list)
    for t in tasks:
        itens_por_cpu[t['cpu']].append(t)
    
    chave_nvidia = os.getenv("NVIDIA_API_KEY", "")
    if not chave_nvidia:
        print("❌ NVIDIA_API_KEY não definida no ambiente.")
        return
    
    # Executa em paralelo com logs no terminal
    resultados = await asyncio.gather(
        *(rodar_maquina(f"cpu{cpu}", itens, chave_nvidia, 
                        lambda m, c=cpu: print_log(f"cpu{c}", m)) 
          for cpu, itens in sorted(itens_por_cpu.items())),
        return_exceptions=True,
    )
    
    # Resumo final
    confirmadas = 0
    total = len(tasks)
    print("-" * 70)
    for (cpu, itens), resultado in zip(sorted(itens_por_cpu.items()), resultados):
        if isinstance(resultado, Exception):
            print(f"❌ cpu{cpu} falhou: {resultado}")
        else:
            sucessos = sum(1 for r in resultado if r.get("sucesso"))
            confirmadas += sucessos
            print(f"✅ cpu{cpu}: {sucessos}/{len(itens)} tarefas OK")
    
    print("-" * 70)
    print(f"🏁 Fim: {confirmadas}/{total} tarefas confirmadas.")


async def run_normal_mode():
    """Executa modo normal (TUI) - importa e roda o dashboard"""
    # Importa e roda o Textual app
    sys.path.insert(0, str(Path(__file__).parent))
    from dashboard import ColabOrchestrator
    app = ColabOrchestrator()
    await app.run_async()


async def main():
    config = load_agent_config()
    auto = config.get("automation", {})
    
    if auto.get("enabled", False):
        timeout_minutes = auto.get("timeout_minutes", 25)
        timeout_seconds = timeout_minutes * 60
        print(f"⏱️  Timeout de automação: {timeout_minutes} minutos")
        try:
            await asyncio.wait_for(run_automation_mode(config), timeout=timeout_seconds)
        except asyncio.TimeoutError:
            print(f"\n⏰ Timeout de {timeout_minutes} min atingido. Encerrando automação.")
    else:
        print("📱 Modo normal (TUI) - automation.enabled: false")
        print("   Para usar automação, edite skill/colab_agent_fleet/agents/openai.yaml")
        print("   e defina automation.enabled: true")
        await run_normal_mode()


if __name__ == "__main__":
    asyncio.run(main())