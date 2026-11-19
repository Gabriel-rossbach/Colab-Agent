# Decisões de arquitetura

## 1. Separação em duas lanes (planejamento vs execução)

**Decisão**: separar o planejador em GPU (LLM local) da fleet de execução em CPU (NVIDIA NIMs).

**Justificativa**:
- Planejamento é sensível à latência, mas de baixo volume → Ollama local (grátis, privado, sem chaves de API)
- Execução é sensível a volume, precisa de saída estruturada + ferramentas → NVIDIA NIMs (rápidos, confiáveis, com web_search)
- Custo: GPU só por segundos; CPUs por minutos

**Alternativas consideradas**:
- Lane única com planejador via API (OpenAI/Anthropic) → rejeitada: chaves de API, custo, latência
- Tudo local (Ollama em tudo) → rejeitada: Nemotron é melhor para uso estruturado de ferramentas

## 2. Colab como infraestrutura

**Decisão**: usar o nível gratuito do Google Colab (CPU) + GPU opcional para o planejador.

**Justificativa**:
- 5+ IPs públicos limpos (distribuição natural de rate-limit)
- Compute grátis para cargas de pesquisa
- Efêmero = sem gerenciamento de estado persistente
- Acesso SSH via CLI `colab`

**Trade-offs**:
- Startup da sessão ~2–3 min a frio
- 12h máx de runtime (nível gratuito)
- Problemas de lock no SQLite em starts paralelos de gateway → mitigado pelo pipeline escalonado

## 3. Plugin OpenClaw para web_search

**Decisão**: plugin TypeScript customizado (`web-search`) usando `duckduckgo-search`, e não `@openclaw/duckduckgo-plugin`.

**Justificativa**:
- O plugin oficial pode não existir / pode haver desencontro de versão
- Controle total sobre o schema da ferramenta, execução e tratamento de erros
- Sem dependência de registro; instala de caminho local

**Interface do plugin**:
```typescript
tool({
  name: "web_search",
  parameters: { query: string, max_results?: number },
  execute: async ({ query, max_results = 5 }) => DDGS().text(query, { max_results })
})
```

## 4. Gateway por máquina, somente em loopback

**Decisão**: com browser habilitado, cada máquina de CPU roda seu próprio gateway em loopback; sem browser, o agente usa `openclaw agent exec` diretamente.

**Justificativa**:
- Ferramentas de plugin exigem gateway
- Gateway compartilhado seria ponto único de falha
- Bind em loopback não expõe o gateway fora da sessão Colab

## 5. Plano da fleet em JSON (não YAML/TOML)

**Decisão**: plano da fleet = JSON com schema estrito (`plan-spec.md`).

**Justificativa**:
- Legível por máquina para validação (`validate_fleet_plan.py`)
- Fácil de gerar a partir de LLM (modo JSON)
- Schema versionável
- Amigável para CI

## 6. Pipeline escalonado (60s entre máquinas)

**Decisão**: o executor CLI lança as máquinas com 60s de intervalo; o worker web inicia os grupos das máquinas após a confirmação.

**Justificativa**: o intervalo reduz contenção de inicialização observada no modo CLI e não é tempo real.

## 7. Confirmação com humano no loop

**Decisão**: o dashboard exige um "continuar" explícito antes de disparar a fleet.

**Justificativa**:
- Compute do Colab custa dinheiro (unidades de computação)
- Evita disparos acidentais a partir de planos ruins
- Permite revisar o plano (prévia dos promotion gates)

## 8. Agent exec embutido (lean)

**Decisão**: usar `openclaw agent exec --local-model-lean` pela velocidade.

**Justificativa**:
- Sem ida e volta ao gateway para o raciocínio central
- Gateway só é necessário para ferramentas de plugin (web_search)
- 2–3x mais rápido que o modo gateway completo

## 9. Base64 para injeção de prompt

**Decisão**: passar os prompts via `base64 -d` para evitar o inferno de escaping de shell.

**Justificativa**:
- Prompts contêm aspas, $(), crases e quebras de linha
- Base64 = zero problemas de escaping
- Simples: `echo 'b64' | base64 -d > /tmp/missao.txt`

## 10. Resumo em markdown com redação (redaction)

**Decisão**: saída final = resumo em markdown + resultados JSON sanitizados + JSON dos gates.

**Justificativa**:
- Relatório legível por humanos
- Legível por máquina para processamento downstream
- Redação em camadas reduz o risco de exposição acidental
- `fleet_public_safety.py` padroniza a redação, mas a revisão humana continua obrigatória antes de qualquer publicação
