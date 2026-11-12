# Referência de operações do Colab

## Padrões da CLI Colab

### Gerenciamento de sessões
```bash
# Listar sessões ativas
colab sessions

# Criar nova sessão de CPU
colab new -s cpu1

# Criar sessão de GPU (T4, L4 etc.)
colab new -s cpu6 --gpu t4

# Parar sessão
colab stop -s cpu1

# SSH na sessão (roda comando via stdin)
colab ssh -s cpu1 << 'EOF'
comando1
comando2
exit
EOF

# SSH com comando como argumento (limitado — use pipe via stdin para scripts complexos)
colab ssh -s cpu1 -- comando arg1 arg2
```

### Problemas comuns

| Problema | Causa | Correção |
|----------|-------|----------|
| `HTTP 429: another colab ssh is connected` | SSH concorrente na mesma sessão | Serialize o acesso; aguarde o anterior terminar |
| `session not found` | Sessão parada ou nome errado | `colab sessions` para verificar; `colab new -s nome` para recriar |
| `GPU not available` | Cota esgotada ou limite de região | Tente outro tipo de GPU (`--gpu l4`, `--gpu a100`) ou aguarde |
| Startup lento | Boot frio da VM | Primeira run ~2–3 min; as seguintes ~30s |

### Ciclo de vida da sessão na fleet

```
1. Orquestrador checa `colab sessions` → verifica se cpu1-cpu5 existem
2. Se faltar → `colab new -s cpuN` (espera 15s de boot)
3. Script de deploy roda via `colab ssh -s cpuN` (pipe via stdin)
4. Script instala OpenClaw, plugin, configura NVIDIA, inicia o gateway
5. Agente roda → retorna resultados
6. Orquestrador agrega → humano vê o resumo
7. Opcional: `colab stop -s cpuN` para economizar compute
```

## Formas GPU vs CPU

| Forma | Acelerador | Caso de uso | Custo (unidades de compute/h) |
|-------|-----------|-------------|-------------------------------|
| CPU | Nenhuma | Busca web, cargas leves | ~1 |
| T4 | 1× T4 16GB | Planejador (Ollama), inferência leve | ~4 |
| L4 | 1× L4 24GB | Inferência local pesada | ~8 |
| A100 | 1× A100 40/80GB | Treino, modelos grandes | ~30+ |

**Padrão da fleet**: cpu1–cpu5 = CPU, cpu6 = T4 (só planejador)

## Quirks de SSH

### Pipe via stdin (recomendado para scripts)
```python
proc = await asyncio.create_subprocess_shell(
    f"colab ssh -s {maquina}",
    stdin=asyncio.subprocess.PIPE,
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.STDOUT,
)
proc.stdin.write(script.encode())
proc.stdin.close()
```

### Comando como argumento (limitado)
```bash
# Só funciona para comandos simples, sem pipes/redirecionamentos
colab ssh -s cpu1 -- openclaw agent exec "prompt"
```

### Tratamento de saída (exit)
Sempre termine o script com `exit` para fechar o SSH de forma limpa:
```bash
echo 'comandos...'
exit
```

## Variáveis de ambiente no Colab

As sessões Colab herdam algumas variáveis de ambiente, mas nem todas. Boa prática: **passar via script no stdin**:

```bash
# No script enviado via stdin:
export NVIDIA_API_KEY="nvapi-xxx"
export MODELO_PLANEJADOR="gpt-oss:20b"
```

Ou use `openclaw config set` para config persistente:
```bash
openclaw config set models.providers.nvidia.apiKey "$NVIDIA_API_KEY"
```

## Disco e persistência

- `/content` = efêmero (reseta ao reiniciar a sessão)
- `/root` = persiste entre reinícios (mas não entre `colab stop/start`)
- Mount do Google Drive: `colab drivemount` → `/content/drive`
- Para a fleet: use `/root` para instalações de plugins, `/tmp` para logs transitórios

## Rede

- Cada sessão Colab = **IP público único** (egress do Google Cloud)
- 5 sessões = 5 IPs diferentes = distribuição natural de rate-limit
- Sem VPC peering entre sessões
- Somente saída; sem portas de entrada (use `colab ssh` para acesso)
