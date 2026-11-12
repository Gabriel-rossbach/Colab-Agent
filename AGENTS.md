# AGENTS.md

Este repositório empacota a skill **colab-agent-fleet** do OpenClaw. Use este arquivo como índice para agentes Codex.

## Regras de operação

- Reformule o objetivo do usuário e nomeie a etapa de verificação antes de editar arquivos.
- Mantenha os diffs cirúrgicos. Não refatore código vizinho a menos que a tarefa exija.
- Preserve a separação entre código da skill (`skill/colab-agent-fleet/`), docs (`docs/codex/`) e orquestração na raiz (`dashboard.py`, `stop_all.py`).
- Trate a revisão de superfície pública como parte do loop padrão. Novos docs, exemplos, manifestos e templates devem passar pelas verificações de vazamento (leak), transfência indevida (bleed) e disciplina de evidências.
- Não publique caminhos locais absolutos, nomes de perfil de navegador, URLs privadas de notebooks, segredos, identificadores de clientes ou linguagem de alegação sem suporte.
- Coloque conhecimento durável do repo em `docs/codex/`. Mantenha este arquivo curto.

## Mapa do repo

- **Skill**: `skill/colab-agent-fleet/` — skill OpenClaw (scripts, references, agents)
- **Orquestrador**: `dashboard.py` (TUI), `stop_all.py` (limpeza), `plano.py` (planejador legado)
- **Docs**: `docs/codex/` — orientação para agentes Codex (overview, architecture, workflow, evals, cleanup)
- **Testes**: `tests/` — testes unitários + integração
- **Config**: `pyproject.toml`, `.env.example`, `.gitignore`

## Verificação padrão

1. Rode `python3 -m py_compile skill/colab-agent-fleet/scripts/*.py`
2. Rode `python3 -m pytest tests/ -q`
3. Rode `python3 skill/colab_agent_fleet/scripts/fleet_public_safety.py --scan .`
4. Se `codex_harness` estiver disponível: `python3 -m codex_harness audit . --strict --min-score 90`
5. Revise os arquivos públicos alterados atrás de segredos, caminhos privados, URLs privadas, dados de clientes e deriva de evidências.

## Conhecimentos-chave para agentes

Ao trabalhar neste repo, os agentes devem conhecer:
- Estrutura de skill OpenClaw (`SKILL.md`, SDK de plugins, configs de agente)
- Padrões da CLI Colab (`colab-operations.md`)
- Especificação do plano da fleet (`plan-spec.md`) — algoritmo de distribuição, regras de validação
- Promotion gates (`promotion-gates.md`) — critérios de qualidade, customização
- Segurança pública (`public-safety.md`) — redação (redaction), prevenção de vazamento
