# Handoff para o Hermes — painel Web da Colab Agent Fleet

- **Data:** 2026-11-19
- **Branch de trabalho:** `feat-web-automation`
- **Natureza deste commit:** handoff/WIP; não é uma versão pronta para deploy.
- **Git:** o usuário autorizou commit local nesta branch e proibiu push. Não enviar para `main` nem para nenhum remoto sem uma instrução nova e explícita.

## 1. Objetivo original

Transformar a TUI existente em um painel Web hospedado na Oracle, mantendo o motor Python e usando:

- Flutter Web para a interface;
- Java 21 + Spring Boot para a API e supervisão de processos;
- `fleet_worker.py` como adaptador JSON Lines entre Java e o motor Python;
- cpu6 para o planner e cpu1–cpu5 para execução;
- planner → revisão do plano → confirmação humana explícita → execução;
- seis painéis de máquina, logs ao vivo, browser opcional, cancelamento e artefatos.

Não é para reescrever o motor em Java nem adicionar FastAPI. MarkItDown não faz parte do produto e não deve ser inserido nos prompts de browser.

## 2. Restrições obrigatórias

1. Não executar fleet real, Colab, Ollama, NVIDIA ou deploy durante o desenvolvimento local.
2. Não ler, imprimir ou commitar `.env`, credenciais, caminhos pessoais, URLs privadas ou IDs de sessão.
3. O navegador nunca deve receber `NVIDIA_API_KEY`; somente o Bearer token digitado pelo operador, mantido em memória.
4. Nunca servir a raiz do repositório como conteúdo Web.
5. Preservar a alteração preexistente em `CONTRIBUTING.md`; ela não pertence a este trabalho e foi deliberadamente deixada fora do commit de handoff.
6. Manter uma única run ativa por processo backend.
7. Cancelamento usa `cancel.requested` e limpeza remota de melhor esforço; não chamar `stop_all.py` nem encerrar todas as sessões.
8. Browser não deve repetir ações reais automaticamente por padrão: uma tentativa para tarefas com browser e duas para tarefas sem browser.
9. Redaction reduz risco, mas não substitui controle de acesso ou revisão humana.
10. Antes de qualquer commit futuro, revisar o diff público e não incluir trabalho alheio ou alterações não relacionadas.

## 3. O que já foi implementado

### Motor Python e worker

- `fleet_worker.py` implementa os comandos:
  - `plan --run-id ID --request REQUEST --run-dir RUNDIR [--browser]`;
  - `execute --run-id ID --run-dir RUNDIR [--browser]`.
- Emite `run.state`, `machine.state`, `task.state`, `log`, `plan.ready` e `run.result` em JSONL stdout.
- Grava `plan.json`, `results.json`, `gates.json` e `summary.md` em diretório privado da run.
- Redige eventos, logs e artefatos públicos antes de disponibilizá-los ao backend.
- `run_fleet.py` ganhou eventos estruturados, saída completa das tarefas, cancelamento cooperativo, limpeza remota, timeouts e tratamento de encerramento de processos.
- `init_fleet_plan.py` valida máquina/GPU, respeita cancelamento e recebe o toggle de browser.
- `validate_fleet_plan.py` rejeita planos malformados, prompts nulos, booleanos usados como inteiros e tarefas de browser quando o browser está desligado.
- `dashboard.py` agora também passa seu toggle de browser ao planner.

### Backend Spring Boot

- REST em `backend/`, com `ProcessBuilder`, sem sidecar FastAPI.
- Autenticação Bearer em todos os `/api/*`, exceto `/api/health`.
- Uma run ativa, transições validadas, polling incremental e catálogo em memória.
- O backend atribui `seq` monotônico e `timestamp` ISO-8601 UTC quando ausente.
- Cancelamento cooperativo com espera de 30 s e fallback de término forçado; testes usam durações curtas injetáveis.
- Redaction adicional de eventos, stderr, request/error de resposta e artefatos.
- Limites de eventos/artefatos e rejeição de symlinks na leitura de artefatos.
- Maven wrapper incluído; testes usam workers falsos e não chamam a fleet real.

### Frontend Flutter — base incompleta

Já existem:

- `frontend/lib/src/api_client.dart`: REST same-origin e Bearer token somente em memória;
- `frontend/lib/src/models.dart`: DTOs, eventos e reducer das seis máquinas;
- `frontend/lib/src/fleet_controller.dart`: autenticação, seleção, polling de 1 s, páginas de 500 eventos, confirmação, cancelamento e carga de artefatos;
- `frontend/lib/main.dart`, `pubspec.yaml`, `analysis_options.yaml` e shell Web.

**Bloqueador:** `main.dart` importa `src/fleet_app.dart`, mas esse arquivo não existe. Não há testes em `frontend/test/`. Portanto a árvore atual não compila o frontend e ainda não entrega a UI solicitada.

### Deploy e documentação

- `deploy/backend.Dockerfile`, `frontend.Dockerfile`, `compose.yaml`, `Caddyfile` e `nginx.conf`.
- Compose publica somente o proxy; o backend aparece apenas em `expose: 8080` na rede interna.
- Repositório montado somente leitura no backend; artefatos em volume privado.
- `.dockerignore` exclui `.env`, builds e caches.
- Limite de request do proxy ajustado para 64 KB, suficiente para o contrato de 10.000 caracteres com escape JSON.
- Comando de login corrigido para substituir o entrypoint Java:
  `docker compose -f deploy/compose.yaml --env-file .env run --rm --entrypoint colab backend login`.
- `docs/codex/web-deployment.md`, README e SECURITY descrevem arquitetura, limites e operação sem prometer segurança absoluta.

### Segurança e artefatos Python

- `fleet_public_safety.py` possui redaction cumulativa, sanitização por allowlist e CLI de scan.
- `.env*` locais são excluídos; scan explícito de `.env` é recusado com código 2.
- Builds, caches, testes sintéticos e binários são excluídos conforme regras implementadas.
- `capture_fleet_context.py` sanitiza contexto e grava JSON privado.
- `render_fleet_summary.py` redige e escapa Markdown sem incluir saídas brutas.
- Integração real exige `FLEET_RUN_INTEGRATION=1`; a presença de `NVIDIA_API_KEY` sozinha não ativa chamadas externas.
- `pyproject.toml` corrige console scripts e empacotamento sob `skill/`.

## 4. Contrato REST e de eventos

Endpoints implementados:

```text
GET  /api/health
POST /api/runs
GET  /api/runs
GET  /api/runs/{id}
POST /api/runs/{id}/confirm
POST /api/runs/{id}/cancel
GET  /api/runs/{id}/events?after=SEQ
GET  /api/runs/{id}/artifacts
```

Estados:

```text
PLANNING
WAITING_CONFIRMATION
EXECUTING
CANCELLING
COMPLETED
FAILED
CANCELLED
```

Resultado no backend:

```json
{
  "totalTasks": 0,
  "completedTasks": 0,
  "successful": 0,
  "gatePass": null
}
```

Artefatos REST contêm somente `summary` e `results`; a raiz do repositório e os arquivos privados não são servidos estaticamente.

## 5. Evidências locais deste handoff

Executado sem integração real:

```text
FLEET_RUN_INTEGRATION=0 python3 -m pytest tests/ -o addopts='' -q
84 passed, 3 skipped

python3 -m py_compile fleet_worker.py dashboard.py run_fleet_cli.py stop_all.py skill/colab_agent_fleet/scripts/*.py
PASS

cd backend && ./mvnw -q test
PASS; suíte já verificada com 32 testes, 0 falhas, 0 erros

cd backend && ./mvnw -q -DskipTests package
PASS; JAR gerado

python3 -m pip wheel . --no-deps --no-build-isolation
PASS; scripts essenciais conferidos no wheel
```

Também passaram:

- `bash -n` para os scripts remotos gerados com e sem browser;
- validação estática do Compose: nenhum `ports` no backend;
- `git diff --check` antes da criação deste documento.

O scan agregado do estado imediatamente anterior a este documento encontrou **6 ocorrências**, sem imprimir valores:

```text
private-ip: 3
private-path: 2
sensitive-assignment: 1
```

Arquivos envolvidos:

- `skill/colab_agent_fleet/scripts/fleet_public_safety.py`;
- `skill/colab_agent_fleet/references/public-safety.md`;
- `docs/codex/cleanup.md`.

Esses achados precisam ser classificados e corrigidos; o scan final ainda não está limpo.

### Limitações do ambiente

- Flutter e Dart não estão instalados: nenhuma análise, teste ou build Flutter foi executado.
- Docker não está instalado: imagens, Caddy, Nginx e Compose não foram executados.
- Testes Java usaram JDK 27 compilando com `release 21`; não houve execução em uma JVM 21.
- Não houve teste real Colab/Ollama/NVIDIA/Oracle e isso deve permanecer assim até autorização explícita.
- Não existe teste ponta a ponta real Python → Java → Dart.

## 6. Trabalho obrigatório para o Hermes

### P0 — tornar o handoff compilável e seguro

1. Implementar `frontend/lib/src/fleet_app.dart` sem remover a base válida existente.
   - Tela de token sem persistência;
   - criação da missão e toggle de browser;
   - plano legível e confirmação humana explícita;
   - seis painéis (`cpu1`–`cpu6`), estado, tarefa, tentativa e logs;
   - cancelamento com confirmação;
   - resultados e saída completa dos artefatos;
   - tratamento de loading, 401, conflito, erro de polling e retry.
2. Adicionar testes Dart para modelos, reducer, polling incremental, confirmação, cancelamento e artefatos.
3. Rodar `flutter analyze`, `flutter test` e `flutter build web --release` quando o SDK estiver disponível; não declarar sucesso sem essas evidências.
4. Corrigir os seis achados do scanner sem enfraquecer detecção:
   - eliminar autoachados das CIDRs literais e do self-test;
   - redigir caminhos pessoais nos dois documentos;
   - revisar se hosts internos de um só nome continuam adequadamente protegidos;
   - manter `.env` fora do scan e recusado quando explícito.
5. Repetir toda a suíte Python, o scan e a revisão de superfície pública.

### P1 — reconciliar o contrato ponta a ponta

1. **Schema do plano:** Python valida 1–10 tarefas, cpu1–cpu5, tarefas 1–2, distribuição, prompt, duplicidade e browser; Java apenas verifica campos básicos e aceita até 256. Formalizar um schema compartilhado e alinhar validação/testes.
2. **Cancelamento:** o worker pode emitir `run.result` durante `CANCELLING`; Java ignora a atualização no DTO, enquanto Dart aplica o evento. Definir uma única semântica para resultados parciais, `gatePass` ausente e carregamento de artefatos.
3. **Gate:** Web termina `COMPLETED` mesmo com `gatePass=false`, enquanto CLI retorna erro. Decidir e documentar se gate reprovado significa run concluída com promoção reprovada ou run falha; testar REST e UI.
4. **Modelo Dart:** preservar e apresentar `completedTasks` e `gatePass`; atualmente `RunResult` descarta esses campos.
5. **Stagger:** CLI espera 60 s entre máquinas; worker Web usa `asyncio.gather` simultâneo. Aplicar stagger cooperativo/cancelável no Web ou justificar e testar outra proteção contra contenção/429.
6. **Confirmação imutável:** UI aprova o plano sanitizado, mas `execute` lê o plano original. Introduzir versão/hash do plano e impedir que outro conteúdo seja executado após a confirmação.
7. **Eventos:** backend conserva 10.000 eventos e Flutter não detecta lacunas. Expor detecção de gap e recuperação/re-sincronização.
8. **Artefatos:** limitar `saida_completa`/tamanho agregado ou implementar streaming/paginação; hoje `results.json` acima de 5 MB faz o endpoint falhar.
9. **Cancelamento parcial:** testar limpeza remota, processos descendentes, saída parcial e consistência do estado terminal. O fallback local não garante encerrar toda a árvore SSH/remota.

### P2 — validação de implantação, ainda sem executar infraestrutura real

1. Validar Dockerfiles e `docker compose config` quando Docker estiver disponível.
2. Conferir build Flutter dentro da imagem e proxy same-origin.
3. Confirmar que somente o proxy possui porta pública e que `/api/*`, exceto health, exige Bearer.
4. Confirmar que o frontend não contém `NVIDIA_API_KEY`, URLs privadas ou credenciais.
5. Não fazer deploy Oracle nem login/sessões Colab sem autorização nova do usuário.

## 7. Sequência de verificação sugerida

Na raiz do repositório:

```bash
python3 -m py_compile fleet_worker.py dashboard.py run_fleet_cli.py stop_all.py skill/colab_agent_fleet/scripts/*.py
FLEET_RUN_INTEGRATION=0 python3 -m pytest tests/ -o addopts='' -q
python3 skill/colab_agent_fleet/scripts/fleet_public_safety.py --scan .
python3 -m pip wheel . --no-deps --no-build-isolation --wheel-dir /tmp/opencode/fleet-wheel

cd backend
./mvnw -q test
./mvnw -q -DskipTests package
cd ..

cd frontend
flutter analyze
flutter test
flutter build web --release
cd ..

git diff --check
git status --short --branch
```

Se `codex_harness` estiver disponível, também executar:

```bash
python3 -m codex_harness audit . --strict --min-score 90
```

Integração real só pode ser executada com opt-in explícito e autorização do usuário. Não basta existir `NVIDIA_API_KEY` no ambiente.

## 8. Critério de conclusão

O trabalho só deixa de ser WIP quando:

- o frontend compila e tem testes;
- planner/confirmação/execução/cancelamento usam o mesmo contrato em Python, Java e Dart;
- os seis painéis e artefatos funcionam contra mocks ponta a ponta;
- gate e resultados parciais têm semântica documentada e testada;
- scanner e revisão pública estão limpos;
- testes Python/Java/Flutter e builds locais passam;
- limitações de Docker e infraestrutura real continuam explicitamente registradas;
- nenhum push, deploy ou fleet real foi feito sem autorização.
