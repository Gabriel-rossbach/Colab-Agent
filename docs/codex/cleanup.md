# Limpeza e manutenção

## Limpeza automática

### Parar todas as sessões
```bash
python3 stop_all.py
# Detecta sessões ativas via regex em `colab sessions`
# Para todas em paralelo
```

### O que é limpo
- Sessões Colab (cpu1–cpu6)
- Nenhum artefato local (JSONL, relatórios persistem em `/tmp` ou `--out`)

## Limpeza manual

### CLI do Colab
```bash
# Listar
colab sessions

# Parar específica
colab stop -s cpu1

# Remover sessão (permanente)
colab rm -s cpu1
```

### Artefatos locais
```bash
# Remover runs temporárias
rm -rf /tmp/fleet-*.json /tmp/run_*

# Remover cache de build do plugin
rm -rf /root/openclaw-plugins/web-search/node_modules
rm -rf /root/openclaw-plugins/web-search/dist

# Limpar estado do OpenClaw (opção nuclear)
openclaw reset
```

## Atualização de dependências

### Python
```bash
# Atualizar deps da skill
pip install -U textual colab-cli duckduckgo-search python-dotenv

# Ver desatualizadas
pip list --outdated
```

### Node (plugin)
```bash
cd /root/openclaw-plugins/web-search
npm update
npm audit fix
```

### OpenClaw
```bash
# Atualizar a CLI
curl -fsSL https://openclaw.ai/install.sh | bash

# Ver versão
openclaw --version
```

## Rotação de logs

```bash
# Logs do gateway (por máquina, no Colab)
# /tmp/gateway.log - sobrescrito a cada run

# Logs do orquestrador local
# Apenas na TUI / stdout; sem arquivos persistentes
```

## Espaço em disco

```bash
# Ver disco no Colab (na sessão)
df -h /content

# Ver local
df -h ~
```

## Manutenção agendada (cron)

```bash
# Semanal: parar sessões órfãs, atualizar deps
0 3 * * 0 /home/apolo/ia/stop_all.py && pip install -U textual colab-cli
```

## Solução de problemas de limpeza

| Problema | Correção |
|----------|----------|
| `colab stop` trava | `colab stop -s nome --force` (se suportado) ou aguarde |
| Sessão presa em "READY" mas sem SSH | `colab rm -s nome` e depois `colab new -s nome` |
| Disco local cheio | `docker system prune -a` se usar Docker; `pip cache purge` |
| Reinstalação do plugin falha | `rm -rf /root/.openclaw/extensions/web-search` e reinstale |
