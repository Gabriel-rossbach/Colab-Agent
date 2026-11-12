# Como o sistema funciona (explicação simples)

> Escrito para quem nunca viu o projeto. Sem jargão.

## A ideia em uma frase

Você faz **uma pergunta** no seu computador → o sistema **divide essa pergunta em várias tarefas pequenas** → manda cada tarefa para **uma máquina diferente no Google Colab** → cada máquina pesquisa na internet com um agente de IA → os resultados voltam todos juntos para você.

É tipo mandar 5 pessoas pesquisarem coisas diferentes ao mesmo tempo, em vez de você pesquisar tudo sozinho.

---

## O desenho geral

```
┌──────────────────────────────────────────────────────────────┐
│  SEU COMPUTADOR (onde você roda o comando)                   │
│                                                              │
│   python3 run_fleet_cli.py                                   │
│   └── run_fleet_cli.py  (o "cérebro" que coordena tudo)      │
│                                                              │
└────────────┬─────────────────────────────┬───────────────────┘
             │                             │
             ▼                             ▼
   ┌─────────────────┐          ┌─────────────────────────────┐
   │  cpu6 (GPU)     │          │  cpu1, cpu2, cpu3... (CPU)  │
   │  PLANEJADOR     │          │  EXECUTORES                 │
   │                 │          │                             │
   │  Roda Ollama    │  plano   │  Cada um roda:              │
   │  com modelo     │─────────▶│  - OpenClaw (agente de IA)  │
   │  gpt-oss:20b    │  JSON    │  - plugin DuckDuckGo        │
   │  (IA local,     │          │  - modelo NVIDIA na nuvem   │
   │   grátis)       │          │  - ferramenta web_search    │
   │                 │          │                             │
   │  Decide: "essa  │          │  Faz a pesquisa de verdade  │
   │  pergunta vira  │          │  na internet e responde     │
   │  5 tarefas, uma │          │                             │
   │  por máquina"   │          │                             │
   └─────────────────┘          └─────────────────────────────┘
                                          │
                                          ▼
                              ┌─────────────────────┐
                              │  Resultados voltam  │
                              │  pro seu terminal   │
                              │  (JSONL + resumo)   │
                              └─────────────────────┘
```

---

## Quem é quem

| Nome | O que é | O que faz |
|------|---------|-----------|
| `run_fleet_cli.py` | Script Python no seu PC | Coordena tudo. Lê o pedido, chama o planejador, manda as tarefas, junta os resultados |
| `cpu6` | Máquina Colab com GPU (Tesla T4) | **Planejador**. Roda uma IA local (Ollama + gpt-oss:20b) que transforma seu pedido em um plano de tarefas |
| `cpu1`–`cpu5` | Máquinas Colab só com CPU | **Executores**. Cada uma roda um agente OpenClaw que pesquisa na web |
| `init_fleet_plan.py` | Script que roda no cpu6 | Gera e valida o plano de tarefas |
| `run_fleet.py` | Script que roda em cada cpu1–cpu5 | Instala OpenClaw, configura tudo, roda o agente com `web_search` |
| `validate_fleet_plan.py` | Validador | Confere se o plano está certo antes de gastar máquina |
| `dashboard.py` | Tela interativa (TUI) | Modo normal: mostra o plano e pede sua confirmação antes de gastar as máquinas |
| `.env` | Arquivo de configuração | Guarda as chaves de API (NVIDIA) e quais máquinas usar. **Nunca é commitado** |

---

## O fluxo passo a passo

### 1. Você escribe o pedido

Exemplo: `"pesquise 5 plugins do OpenClaw e traga em português"`

No modo automação esse pedido está fixo em `agents/openai.yaml` (`mock_prompt`). No modo normal você digita na TUI.

### 2. O planejador (cpu6) cria o plano

O cpu6 baixa e roda o modelo `gpt-oss:20b` localmente (via Ollama, grátis). Esse modelo recebe um **prompt de sistema com regras rígidas** (em `init_fleet_plan.py`) e devolve só linhas assim:

```
[cpu1] [tarefa1] Use web_search para pesquisar os 5 plugins do OpenClaw. Traga em português.
[cpu2] [tarefa1] Use web_search para pesquisar ...
```

Regras que o planejador segue:
- Cada categoria do pedido vira **uma tarefa só** ("5 carros" = 1 tarefa, não 5)
- Máximo **2 tarefas por máquina** (tarefa1, tarefa2)
- Pedido simples (2–4 tarefas) usa 2 máquinas; 5+ tarefas usa o mínimo de máquinas com 2 tarefas cada
- **Nunca inventa nomes** — se o pedido não deu nomes, o prompt manda o agente achar os nomes com web_search
- Formato fixo: `[cpuN] [tarefaK] prompt`, uma por linha, sem markdown

Se o plano sair errado (tarefas duplicadas, nomes inventados, máquina errada), o sistema **tenta de novo até 4 vezes**, mandando o erro de volta pro modelo como correção.

### 3. O plano é validado

`validate_fleet_plan.py` confere:
- Formato correto de cada linha
- Distribuição certa entre máquinas (máx 2 por máquina, ordem cpu1, cpu2...)
- Prompts não repetidos (similaridade alta = erro)
- Nomes entre aspas que o pedido não trouxe = erro (nome inventado)
- Palavras extras fora do tema (segurança, etc.) = erro

Só depois de passar na validação as máquinas são ligadas.

### 4. Cada executor (cpu1–cpuN) roda a tarefa

Em cada máquina CPU, o script `run_fleet.py` faz:

1. **Instala o OpenClaw** (`curl -fsSL https://openclaw.ai/install.sh | bash`)
2. **Instala o plugin oficial de busca**: `openclaw plugins install @openclaw/duckduckgo-plugin`
3. **Escreve o arquivo de config** `~/.openclaw/openclaw.json` com:
   - Modelo NVIDIA (`nvidia/nemotron-3.5-lightning-30b-a3b`) usando a chave do env `NVIDIA_API_KEY`
   - Provider de busca: `duckduckgo`
   - **Só as ferramentas de web liberadas**: `"tools": { "allow": ["group:web"] }` — o agente NÃO consegue usar nenhuma outra ferramenta, só `web_search`
4. **Roda o agente**: `openclaw agent exec "<prompt>" --model nvidia/... --code-mode direct --timeout 600`

O prompt enviado pro agente tem instruções claras:
```
REGRAS OBRIGATÓRIAS:
1. Sua ÚNICA ferramenta é web_search.
2. Chame assim: {"query": "texto da pesquisa", "count": 5}
3. Chame pelo menos 2 vezes com ângulos diferentes.
4. Baseie sua resposta SÓ nos resultados do web_search.
```

Isso foi o que fez funcionar de verdade — antes o modelo chamava a ferramenta com o nome errado do parâmetro e caía no conhecimento interno.

### 4b. Ferramenta browser (opcional)

Quando `browser.enabled: true` em `agents/openai.yaml`, o executor também instala:

- **Google Chrome** (pacote `.deb` oficial)
- **Plugin browser** (`@openclaw/browser-plugin`, já vem junto com o OpenClaw)
- **Gateway do OpenClaw** na porta 3456 (o browser tool só funciona via gateway, não no modo `agent exec`)

A config escrita em `~/.openclaw/openclaw.json` precisa ter:

```json
{
  "gateway": { "port": 3456, "bind": "loopback", "auth": { "mode": "token", "token": "..." } },
  "tools": { "allow": ["group:web", "browser"] },
  "agents": { "entries": { "main": { "tools": { "allow": ["group:web", "browser"] } } } },
  "plugins": { "allow": ["duckduckgo", "browser"], "entries": { "browser": { "enabled": true } } },
  "browser": { "enabled": true, "profiles": { "openclaw": { "driver": "openclaw", "engine": "chromium", "noSandbox": true } } }
}
```

**Pontos importantes que aprendemos:**
- O ID da ferramenta browser é exatamente `"browser"` (não `openclaw:browser:browser`)
- O gateway precisa de ~40s para subir com o plugin browser totalmente carregado — o script espera `connectivity check: ok` antes de disparar o agente
- O processo do gateway se chama `openclaw-gateway` (hífen), então o `pkill` precisa casar `openclaw[- ]gateway`
- O agente roda com `openclaw agent --message` (via gateway), não `agent exec` (embutido)

### 5. Os resultados voltam

Cada máquina imprime `MISSAO_OK` se deu certo. O `run_fleet_cli.py` junta tudo e mostra:

```
✅ cpu1: 1/1 tarefas OK
🏁 Fim: 1/1 tarefas confirmadas.
```

E salva arquivos em disco: `resultados.jsonl` (dados brutos), `gates.json` (passou nos critérios de qualidade?) e `summary.md` (resumo em markdown).

---

## Os dois modos de rodar

| Modo | Como liga | Para quê |
|------|-----------|----------|
| **Automação** (terminal) | `automation.enabled: true` em `agents/openai.yaml` | Debug e teste rápido. Sem tela, sem confirmar, prompt fixo (`mock_prompt`), limite de tempo (`timeout_minutes: 120`) |
| **Normal** (TUI) | `automation.enabled: false` | Uso real. Abre `dashboard.py`, mostra o plano, você confirma digitando `continuar` |

Comando nos dois casos: `python3 run_fleet_cli.py`

---

## Por que separar planejador (GPU) de executor (CPU)?

- **Planejar é rápido e barato**: o modelo local no cpu6 responde em segundos e não gasta API paga. A GPU só serve pra rodar o modelo local mais rápido.
- **Executar precisa de ferramenta**: o agente executor precisa chamar `web_search` de verdade, e o modelo da NVIDIA (Nemotron) faz isso bem via API.
- **Cada máquina de execução tem IP próprio**: 5 máquinas Colab = 5 IPs diferentes, então as buscas não batem em limite de rate do mesmo IP.

---

## Arquivos importantes

```
.env                          → chaves (NVIDIA_API_KEY, MAQUINAS, MODELO_PLANEJADOR)
run_fleet_cli.py              → entrada principal (escolhe automação ou TUI)
dashboard.py                  → TUI do modo normal
stop_all.py                   → mata todas as sessões Colab órfãs
skill/colab_agent_fleet/
  SKILL.md                    → descrição do skill
  agents/openai.yaml          → config do agente + modo automação
  scripts/
    init_fleet_plan.py        → planejador (roda no cpu6, gera o plano)
    validate_fleet_plan.py    → valida o plano antes de gastar máquina
    run_fleet.py              → executor (roda em cada cpu1–cpu5)
    render_fleet_summary.py   → gera o resumo markdown
    fleet_public_safety.py    → remove secrets dos arquivos públicos
    capture_fleet_context.py  → registra estado do ambiente
```

---

## Comandos úteis

```bash
# Rodar o sistema (automação se enabled: true, senão TUI)
python3 run_fleet_cli.py

# Ver logs da última rodada
tail -f $(ls -t /tmp/opencode/fleet_v*.log | head -1)

# Matar todas as máquinas Colab
python3 stop_all.py

# Ver quais máquinas estão ligadas
colab sessions

# Testes
python3 -m pytest tests/ -q

# Checar segurança (sem secrets vazando)
python3 skill/colab_agent_fleet/scripts/fleet_public_safety.py --scan .
```

---

## Resumo visual do que aconteceu na última rodada (v8)

```
Você: "pesquise 5 plugins do OpenClaw"
   │
   ▼
cpu6 (GPU): gpt-oss:20b gera plano válido na 1ª tentativa
   │  → [cpu1] [tarefa1] Use web_search para pesquisar os 5 plugins do OpenClaw...
   ▼
validação: ✅ formato OK, ✅ distribuição OK, ✅ sem nomes inventados
   │
   ▼
cpu1 (CPU): instala OpenClaw + plugin DuckDuckGo + config NVIDIA
   │  → openclaw agent exec "..." --model nvidia/nemotron-... 
   │  → agente chama web_search({"query": "...", "count": 5}) ✅
   │  → traz 5 plugins com fontes da web
   ▼
Terminal: ✅ cpu1: 1/1 tarefas OK — 🏁 Fim: 1/1 tarefas confirmadas.
```
