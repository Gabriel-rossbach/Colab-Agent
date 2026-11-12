# Contribuindo

## Configuração de desenvolvimento

```bash
# Clonar
git clone https://github.com/seu-usuario/colab-agent-fleet.git
cd colab-agent-fleet

# Instalar dependências
pip install -e ".[dev]"
# ou: pip install textual colab-cli duckduckgo-search python-dotenv pytest

# Instalar plugin (para testes locais)
cd skill/colab-agent-fleet/scripts
# O plugin é buildado no Colab; build local é opcional

# Rodar testes
python3 -m pytest tests/ -q
```

## Estilo de código

- Python 3.11+
- Type hints em todas as funções públicas
- Formatação com `black` (line length 100)
- Lint com `ruff`
- Docstrings em todos os módulos/classes/funções públicos

```bash
# Formatar
black skill/ tests/
ruff check --fix skill/ tests/
```

## Mensagens de commit

Siga o Conventional Commits:
```
feat: adiciona novo gate de promoção para frescor do conteúdo
fix: trata lock do SQLite no pipeline escalonado
docs: atualiza plan-spec.md com distribuição de 10 tarefas
refactor: extrai health-check do gateway para helper
test: adiciona testes unitários da lógica de dedup
chore: atualiza dependências
```

## Processo de Pull Request

1. Fork e crie a branch: `git checkout -b feat/minha-feature`
2. Faça as alterações com testes
3. Rode a verificação: `python3 -m py_compile skill/... && python3 -m pytest -q`
4. Rode o scan de segurança: `python3 skill/colab-agent-fleet/scripts/fleet_public_safety.py --scan .`
5. Push e abra o PR com a descrição das alterações
6. O CI deve passar (sintaxe, testes, segurança)

## Adicionando novas funcionalidades

### Novo Promotion Gate
1. Edite `run_fleet.py`: adicione em `PROMOTION_GATES_DEFAULTS` + `aplicar_gates()`
2. Documente em `references/promotion-gates.md`
3. Adicione teste em `tests/test_gates.py`

### Novo doc de referência
1. Crie `references/novo-topico.md`
2. Adicione na seção References do `SKILL.md`
3. Linke a partir dos scripts relevantes

### Novo script
1. Crie `scripts/novo_script.py` com argparse + main()
2. Adicione na seção Bundled Scripts do `SKILL.md`
3. Adicione teste unitário em `tests/`
4. Atualize entry_points do `pyproject.toml` se for CLI

## Testes

```bash
# Todos os testes
pytest tests/ -q

# Com cobertura
pytest tests/ --cov=skill/colab-agent-fleet/scripts --cov-report=term-missing

# Pulando integração
pytest tests/ -m "not integration" -q
```

## Documentação

- Atualize `docs/codex/` para orientação dos agentes Codex
- Atualize `references/` para docs voltado ao usuário
- Mantenha o `SKILL.md` em sincronia com as capacidades dos scripts

## Release

1. Atualize a versão no `SKILL.md` e no `pyproject.toml`
2. Tag: `git tag v0.1.1`
3. Push: `git push origin v0.1.1`
4. O GitHub Actions builda e publica no ClawHub (se configurado)
