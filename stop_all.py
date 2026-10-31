import asyncio
import re

async def parar_maquina(maquina: str):
    """Envia o comando de desligamento para uma máquina específica."""
    print(f"[*] Enviando sinal de parada para a '{maquina}'...")
    processo = await asyncio.create_subprocess_shell(
        f"colab stop -s {maquina}",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT
    )
    stdout, _ = await processo.communicate()
    
    # Pega a última linha da saída do comando para mostrar o status limpo
    linhas = stdout.decode('utf-8').strip().split('\n')
    mensagem_final = linhas[-1] if linhas else "Desligada."
    print(f"[+] {maquina}: {mensagem_final}")

async def main():
    print("🔍 Lendo sessões ativas dinamicamente do servidor...")
    
    # 1. Puxa a lista de sessões atuais
    proc_check = await asyncio.create_subprocess_shell(
        "colab sessions",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT
    )
    stdout, _ = await proc_check.communicate()
    saida = stdout.decode('utf-8')
    
    print("-" * 40)
    print(saida.strip()) # Mostra o log original do Colab para referência
    print("-" * 40)
    
    # 2. Usa Regex para encontrar tudo que está entre colchetes (ex: [cpu1], [teste])
    encontrados = re.findall(r'\[(.*?)\]', saida)
    
    # 3. Filtra a tag '[colab]' do sistema e remove possíveis duplicatas
    maquinas_ativas = list(set([m for m in encontrados if m.lower() != 'colab']))
    
    if not maquinas_ativas:
        print("\n✅ Nenhuma sessão ativa encontrada. (Tudo limpo!)")
        return
        
    print(f"\n🛑 Sessões ativas detectadas: {', '.join(maquinas_ativas)}")
    print("🚀 Iniciando protocolo de encerramento em paralelo...\n")
    
    # 4. Dispara o desligamento de todas as máquinas detectadas ao mesmo tempo
    tarefas = [parar_maquina(maq) for maq in maquinas_ativas]
    await asyncio.gather(*tarefas)
    
    print("\n✨ Limpeza concluída! Todas as instâncias órfãs foram encerradas.")

if __name__ == "__main__":
    asyncio.run(main())