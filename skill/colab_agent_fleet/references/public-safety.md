# Public Safety Reference

## Rules for Public Distribution (ClawHub / GitHub)

### Never Include in Public Skill Bundle

| Category | Examples | Redaction |
|----------|----------|-----------|
| **API Keys** | `NVIDIA_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` | `***REDACTED***` |
| **Tokens** | GitHub PAT, GitLab token, AWS keys | `***REDACTED***` |
| **Private URLs** | Internal Colab URLs, private notebook links, company domains | `https://***.internal/**` |
| **Session IDs** | Colab session IDs (`m-s-kkb-use1b2-...`) | `m-s-***REDACTED***` |
| **Local Paths** | `/home/apolo/...`, `/root/...`, `/tmp/...` | `/home/***/...` |
| **IP Addresses** | Private (10.x, 192.168.x, 172.16-31.x) | `10.***.***.***` |
| **Customer Data** | Names, emails, project codenames | `[REDACTED]` |
| **Unsupported Claims** | "SOTA", "beats benchmark", "production-ready" without evidence | Remove or qualify |

### Redaction Helpers

Use `fleet_public_safety.py`:
```python
from fleet_public_safety import redact_text, redact_command, sanitize_for_public

# Auto-redact logs before public output
public_log = redact_text(raw_log)
public_cmd = redact_command(bash_script)
public_json = sanitize_for_public(result_dict)
```

### Environment Variables

```bash
# .env.example (COMMIT THIS)
NVIDIA_API_KEY=nvapi-YOUR_KEY_HERE
MODELO_PLANEJADOR=gpt-oss:20b
MAQUINAS=cpu1,cpu2,cpu3,cpu4,cpu5

# .env (NEVER COMMIT - in .gitignore)
NVIDIA_API_KEY=nvapi-actual-secret-key
```

### Gitignore (Minimum)
```gitignore
.env
*.log
/tmp/
*.sqlite
__pycache__/
*.pyc
colab-sessions.json
```

### CI Validation

```yaml
# .github/workflows/public-safety.yml
- name: Check for secrets
  run: |
    python3 -m skill.colab-agent-fleet.scripts.fleet_public_safety \
      --scan . --fail-on-secrets
```

### Public Narrative

When describing the skill publicly:
- ✅ "Orchestrates distributed web research across Colab runtimes"
- ✅ "Uses local LLM for planning, NVIDIA NIMs for execution"
- ✅ "Human-in-the-loop confirmation before launching fleet"
- ❌ "Automatically scrapes competitor data" → too aggressive
- ❌ "Bypasses rate limits" → implies abuse
- ❌ "Guarantees SOTA results" → unsupported claim

### Reporting Security Issues

> Report security issues privately using the contact path in SECURITY.md instead of filing a public issue with sensitive details.

### License Headers

All public files should have license header:
```python
# SPDX-License-Identifier: Apache-2.0
# Copyright 2024 [Your Name/Org]
```