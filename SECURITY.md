# Security Policy

## Reporting a Vulnerability

**Do not file public issues for security vulnerabilities.**

Email: security@seu-dominio.com (or GitHub Security Advisories)

Include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

We'll acknowledge within 48 hours and coordinate disclosure.

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | ✅ Yes    |

## Security Practices

### Secrets Management
- **Never commit** `.env`, API keys, tokens, or session IDs
- Use `.env.example` for template
- All scripts use `fleet_public_safety.py` for output redaction
- CI scans for secrets on every PR

### Colab Sessions
- Each session = unique public IP (Google Cloud)
- No persistent credentials stored in Colab
- Sessions stopped after use (`stop_all.py`)
- No SSH keys stored; uses `colab` CLI OAuth

### OpenClaw
- Gateway runs with `--auth none --bind loopback` (local only)
- NVIDIA API key injected at runtime via stdin
- Plugin installed from local path (not registry)
- No telemetry sent to external services

### Data Handling
- Research results stored locally (JSONL + markdown)
- No automatic upload to external services
- Promotion gates filter before any "promotion"
- Redaction applied to all public outputs

## Threat Model

| Asset | Threat | Mitigation |
|-------|--------|------------|
| NVIDIA API key | Leak via logs/git | Redaction, .gitignore, env-only |
| Colab session ID | Hijack | Short-lived, stopped after use |
| Research data | Exfiltration | Local-only, no auto-upload |
| Plugin code | Supply chain | Local build, no registry dep |
| Gateway | Unauthorized access | Loopback bind, no auth (dev only) |

## Responsible Disclosure

We follow coordinated vulnerability disclosure. If you find a security issue, we'll work with you to fix it before public disclosure.