# Referência de segurança pública

## Regras para distribuição pública (ClawHub / GitHub)

### Nunca inclua no bundle público da skill

| Categoria | Exemplos | Redação |
|-----------|----------|---------|
| **Chaves de API** | `NVIDIA_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` | `***REDACTED***` |
| **Tokens** | GitHub PAT, token GitLab, chaves AWS | `***REDACTED***` |
| **URLs privadas** | URLs internas do Colab, links privados de notebooks, domínios da empresa | `https://***.internal/**` |
| **IDs de sessão** | IDs de sessão Colab (`m-s-kkb-use1b2-...`) | `m-s-***REDACTED***` |
| **Caminhos locais** | `/home/apolo/...`, `/root/...`, `/tmp/...` | `/home/***/...` |
| **Endereços IP** | Privados (10.x, 192.168.x, 172.16-31.x) | `10.***.***.***` |
| **Dados de clientes** | Nomes, emails, codenames de projeto | `[REDACTED]` |
| **Alegações sem suporte** | "SOTA", "vence benchmark", "pronto para produção" sem evidência | Remover ou qualificar |

### Helpers de redação (redaction)

Use `fleet_public_safety.py`:
```python
from fleet_public_safety import redact_text, redact_command, sanitize_for_public

# Redige logs antes de saída pública
public_log = redact_text(raw_log)
public_cmd = redact_command(bash_script)
public_json = sanitize_for_public(result_dict)
```

### Variáveis de ambiente

```bash
# .env.example (COMMITE ISTO)
NVIDIA_API_KEY=nvapi-SUA_CHAVE_AQUI
MODELO_PLANEJADOR=gpt-oss:20b
MAQUINAS=cpu1,cpu2,cpu3,cpu4,cpu5

# .env (NUNCA COMMITE — fica no .gitignore)
# Cole aqui o valor real apenas no ambiente privado, nunca em exemplos versionados.
```

### .gitignore (mínimo)
```gitignore
.env
*.log
/tmp/
*.sqlite
__pycache__/
*.pyc
colab-sessions.json
```

### Validação local

Este repositório não inclui workflow de CI configurado. Antes de publicar, rode o scanner localmente:

```bash
python3 skill/colab_agent_fleet/scripts/fleet_public_safety.py --scan .
```

Se um pipeline de CI for adicionado no futuro, ele deve executar esse comando e falhar quando o scanner encontrar segredos reais.

### Narrativa pública

Ao descrever a skill publicamente:
- ✅ "Orquestra pesquisa web distribuída em runtimes do Colab"
- ✅ "Usa LLM local para planejamento e NVIDIA NIMs para execução"
- ✅ "Confirmação humana no loop antes de disparar a fleet"
- ❌ "Faz scraping automático de dados de concorrentes" → agressivo demais
- ❌ "Contorna rate limits" → implica abuso
- ❌ "Garante resultados SOTA" → alegação sem suporte

### Reportando problemas de segurança

> reporte problemas de segurança de forma privada usando o contato em SECURITY.md em vez de abrir issue pública com detalhes sensíveis.

### Cabeçalhos de licença

Todos os arquivos públicos devem ter cabeçalho de licença:
```python
# SPDX-License-Identifier: Apache-2.0
# Copyright 2024 [Seu Nome/Org]
```
