# Painel web e implantação na Oracle

## Arquitetura publicada

- **Oracle**: hospeda somente o painel Flutter Web e o orquestrador Spring Boot.
- **Colab**: cpu6 executa o planner Ollama; cpu1–cpu5 executam as tarefas.
- **Worker**: o Java inicia `fleet_worker.py` com `ProcessBuilder`; stdout usa JSON Lines.
- **HTTP**: Flutter chama REST same-origin e consulta eventos a cada segundo. Não há SSE nem WebSocket.
- **Artefatos**: cada run grava `plan.json`, `results.json`, `gates.json` e `summary.md` em volume privado. O repositório nunca é diretório web.

O navegador recebe o token Bearer digitado pelo operador, mas não recebe `NVIDIA_API_KEY`. A chave NVIDIA existe apenas no ambiente do backend e é encaminhada pelo worker aos runtimes de execução.

## Fluxo funcional

1. O operador descreve a missão e escolhe se o browser pode ser usado.
2. O backend inicia `fleet_worker.py plan` e mostra cpu6 em atividade.
3. O plano validado fica em `WAITING_CONFIRMATION`; nenhuma tarefa de cpu1–cpu5 começa nesse estado.
4. Somente a confirmação inicia `fleet_worker.py execute`.
5. Os eventos estruturados atualizam máquinas, tarefas e logs. Ao terminar, o painel carrega os artefatos.
6. O cancelamento cria `cancel.requested`; o Python tenta encerrar SSH/agentes/gateways antes do fallback de término do subprocesso Java.

A limpeza remota é de melhor esforço. Após um cancelamento ou falha de infraestrutura, o operador deve verificar as sessões Colab antes de reutilizá-las. Ações de browser podem ter efeitos externos irreversíveis; por isso o executor não repete essas tarefas automaticamente por padrão.

## Arquivos de implantação

| Arquivo | Uso |
|---|---|
| `deploy/backend.Dockerfile` | Build Java 21 e runtime com Python/CLI Colab |
| `deploy/frontend.Dockerfile` | Build Flutter Web e imagem final Caddy |
| `deploy/compose.yaml` | Rede interna, volumes privados e publicação do proxy |
| `deploy/Caddyfile` | Proxy same-origin, headers de segurança e SPA fallback |
| `deploy/nginx.conf` | Alternativa equivalente para quem já usa Nginx |

## Preparação na VM Oracle

Pré-requisitos: Docker com Compose v2, acesso de saída à internet e uma cópia deste repositório. Para HTTPS público, aponte um DNS próprio para a VM e libere as portas 80 e 443 no firewall/Security List. Não publique a porta 8080 do backend: apenas o serviço `panel` possui mapeamento de porta no Compose.

Na raiz do repositório:

```bash
cp .env.example .env
chmod 600 .env
```

Preencha no `.env`:

- `NVIDIA_API_KEY`: segredo real, somente no servidor;
- `FLEET_API_TOKEN`: token longo e aleatório, diferente da chave NVIDIA;
- `PANEL_ADDRESS`: mantenha `:80` para avaliação local ou use o domínio público para TLS automático;
- `PANEL_HTTP_PORT=80` e `PANEL_HTTPS_PORT=443` para publicação pública.

Um token pode ser gerado localmente, sem gravá-lo no repositório, com:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

## Build, autenticação da CLI e inicialização

Nenhum desses comandos cria sessões Colab nem inicia uma pesquisa:

```bash
docker compose -f deploy/compose.yaml --env-file .env build
docker compose -f deploy/compose.yaml --env-file .env run --rm --entrypoint colab backend login
docker compose -f deploy/compose.yaml --env-file .env up -d
```

Conclua o fluxo de autenticação exibido pela própria CLI. As credenciais ficam no volume Docker `colab-home`; não use caminhos de home pessoais nem copie esses arquivos para o repositório.

Verificação local do proxy, sem criar execução:

```bash
curl --fail http://127.0.0.1:8080/api/health
```

Em publicação pública nas portas padrão, use o domínio configurado. O acesso às runs exige o Bearer token pela interface; `/api/health` é o único endpoint operacional sem autenticação.

## Nginx como alternativa

O Compose usa Caddy por padrão para facilitar TLS. `deploy/nginx.conf` pode ser montado em um container Nginx que sirva `frontend/build/web` em `/usr/share/nginx/html` e esteja na mesma rede do serviço `backend`. A configuração escuta na porta interna 8080, faz proxy de `/api/` e nunca serve a raiz do repositório. O TLS deve ser terminado no Nginx ou em outro proxy externo nessa alternativa.

## Operação e limites desta versão

- Apenas **uma run ativa** é aceita por processo backend.
- O catálogo de runs e seus eventos ficam em memória. Os artefatos sobrevivem no volume, mas a lista da API não é reconstruída após restart.
- **Não reinicie o backend durante uma run.** Faça cancelamento e confirme o estado terminal antes da manutenção.
- O polling guarda no máximo 500 eventos por resposta; o cliente continua do último `seq` sem transformar logs em estado.
- Logs e resultados passam por redaction, mas redaction não substitui o controle de acesso nem torna dados privados adequados para publicação.
- Rode a verificação padrão antes de publicar alterações; os testes unitários não validam Colab, Ollama ou NVIDIA reais.

Comandos de inspeção (não devem ser usados como relatório público sem revisar o conteúdo):

```bash
docker compose -f deploy/compose.yaml ps
docker compose -f deploy/compose.yaml logs --tail=100 backend
docker compose -f deploy/compose.yaml logs --tail=100 panel
```

Para uma manutenção sem run ativa:

```bash
docker compose -f deploy/compose.yaml down
```

Esse comando preserva os volumes. Não use `down -v` em operação normal, pois ele apaga artefatos, credenciais da CLI e dados do proxy.
