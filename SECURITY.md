# Política de Segurança

## Reportando uma vulnerabilidades

**Não abra issues públicas para vulnerabilidades de segurança.**

Email: security@seu-dominio.com (ou GitHub Security Advisories)

Inclua:
- Descrição da vulnerabilidade
- Passos para reproduzir
- Impacto potencial
- Correção sugerida (se houver)

Responderemos em até 48 horas e coordenaremos a divulgação.

## Versões suportadas

| Versão | Suportada |
|--------|-----------|
| 0.1.x  | ✅ Sim    |

## Práticas de segurança

### Gerenciamento de segredos
- **Nunca commite** `.env`, chaves de API, tokens ou IDs de sessão
- Use `.env.example` como modelo
- Todos os scripts usam `fleet_public_safety.py` para redação das saídas
- O CI escaneia segredos em cada PR

### Sessões Colab
- Cada sessão = IP público único (Google Cloud)
- Nenhuma credencial persistente é guardada no Colab
- Sessões são encerradas após o uso (`stop_all.py`)
- Nenhuma chave SSH é guardada; usa OAuth da CLI `colab`

### OpenClaw
- O gateway roda com `--auth none --bind loopback` (somente local)
- A chave de API da NVIDIA é injetada em tempo de execução via stdin
- O plugin é instalado de caminho local (não do registro)
- Nenhuma telemetria é enviada a serviços externos

### Tratamento de dados
- Resultados de pesquisa ficam locais (JSONL + markdown)
- Nenhum upload automático para serviços externos
- Os promotion gates filtram antes de qualquer "promoção"
- Redação (redaction) aplicada em todas as saídas públicas

## Modelo de ameaças

| Ativo | Ameaça | Mitigação |
|-------|--------|-----------|
| Chave de API da NVIDIA | Vazamento via logs/git | Redação, .gitignore, somente env |
| ID da sessão Colab | Sequestro (hijack) | Curta duração, encerrada após o uso |
| Dados de pesquisa | Exfiltração | Somente local, sem upload automático |
| Código do plugin | Cadeia de suprimentos (supply chain) | Build local, sem dependência de registro |
| Gateway | Acesso não autorizado | Bind em loopback, sem auth (só dev) |

## Divulgação responsável

Seguimos a divulgação coordenada de vulnerabilidades. Se você encontrar um problema de segurança, trabalharemos com você para corrigi-lo antes da divulgação pública.
