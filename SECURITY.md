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
- Os pontos de saída pública usam `fleet_public_safety.py` para redação; revise os artefatos mesmo assim
- O scanner local está disponível em `fleet_public_safety.py --scan .`; não há workflow de CI configurado neste repositório

### Sessões Colab
- Cada sessão usa o runtime remoto e a autenticação da CLI `colab`; o acesso depende da conta operadora
- Sessões podem ser encerradas manualmente com `stop_all.py` quando apropriado
- Arquivos remotos de configuração, logs e processos devem ser tratados como sensíveis; runtime efêmero não é garantia de apagamento

### OpenClaw
- Com browser habilitado, o gateway usa bind loopback e autenticação local
- A chave NVIDIA é passada ao processo remoto por variável de ambiente em tempo de execução
- Plugins podem ser baixados do registro e de repositórios externos; revise a cadeia de suprimentos antes do deploy

### Painel Web
- O backend exige Bearer token em todos os endpoints `/api`, exceto health
- O token de acesso e a chave NVIDIA são segredos distintos; a chave NVIDIA não é enviada ao Flutter
- O proxy publica somente o frontend e `/api`; artefatos ficam fora do diretório web

### Tratamento de dados
- Resultados ficam em diretório privado por execução e são servidos somente pela API autenticada
- Prompts e pesquisas são enviados aos provedores externos necessários para a execução; não há promessa de ausência de telemetria desses serviços
- O gate implementado calcula somente taxa de sucesso; não há promoção automática de dados
- Redação (redaction) reduz risco, mas não substitui controle de acesso nem revisão humana

## Modelo de ameaças

| Ativo | Ameaça | Mitigação |
|-------|--------|-----------|
| Chave de API da NVIDIA | Vazamento via logs/git | Redação em camadas, .gitignore, env somente no backend |
| ID da sessão Colab | Sequestro (hijack) | Redação dos IDs e autenticação da CLI; revise sessões após falhas |
| Dados de pesquisa | Exfiltração | Diretório privado, API autenticada e revisão antes de publicação |
| Código do plugin | Cadeia de suprimentos (supply chain) | Dependências declaradas e build controlado; instalação externa deve ser auditada |
| Gateway remoto | Acesso não autorizado | Bind em loopback e autenticação local |
| API Web | Uso não autorizado | Bearer token, comparação constant-time e backend sem porta pública no Compose |

## Divulgação responsável

Seguimos a divulgação coordenada de vulnerabilidades. Se você encontrar um problema de segurança, trabalharemos com você para corrigi-lo antes da divulgação pública.
