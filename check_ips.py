#!/usr/bin/env python3
"""
Verifica se as sessões Colab têm IPs públicos diferentes.
Uso: python3 check_ips.py
Requer: colab CLI autenticado e sessões ativas.
"""

import subprocess
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

SESSIONS = ["cpu1", "cpu2", "cpu3"]  # adicione cpu4, cpu5 se existirem
IP_CMD = "curl -s https://api.ipify.org"  # retorna só o IP


def get_ip(session: str) -> tuple[str, str | None, str | None]:
    """Retorna (session, ip, error)."""
    try:
        # colab ssh -s <session> abre shell; mandamos comando via stdin
        result = subprocess.run(
            ["colab", "ssh", "-s", session],
            input=IP_CMD + "\nexit\n",
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return session, None, result.stderr.strip() or "ssh falhou"
        # stdout vem com prompt, echo do comando, IP, etc. Pega última linha não vazia que parece IP
        lines = [l.strip() for l in result.stdout.splitlines() if l.strip()]
        ip = None
        for l in reversed(lines):
            # IP simples: 4 octetos
            if all(p.isdigit() and 0 <= int(p) <= 255 for p in l.split(".")) and len(l.split(".")) == 4:
                ip = l
                break
        if not ip:
            return session, None, f"IP não encontrado na saída: {lines[-3:]}"
        return session, ip, None
    except subprocess.TimeoutExpired:
        return session, None, "timeout (30s)"
    except Exception as e:
        return session, None, f"erro: {e}"


def main():
    print(f"🔍 Verificando IPs em {len(SESSIONS)} sessões...\n")
    results = {}

    with ThreadPoolExecutor(max_workers=len(SESSIONS)) as executor:
        futures = {executor.submit(get_ip, s): s for s in SESSIONS}
        for fut in as_completed(futures):
            session, ip, err = fut.result()
            results[session] = {"ip": ip, "error": err}
            status = f"✅ {ip}" if ip else f"❌ {err}"
            print(f"  {session}: {status}")

    # Resumo
    ips = [v["ip"] for v in results.values() if v["ip"]]
    unique = set(ips)

    print("\n" + "=" * 40)
    print(f"📊 Resumo: {len(unique)} IP(s) único(s) de {len(SESSIONS)} sessões")
    for ip in sorted(unique):
        owners = [s for s, v in results.items() if v["ip"] == ip]
        print(f"  {ip} → {', '.join(owners)}")

    if len(unique) == len(SESSIONS):
        print("\n🎉 Perfeito: todas as sessões têm IPs DIFERENTES.")
        sys.exit(0)
    elif len(unique) == 1:
        print("\n⚠️  Todas as sessões compartilham o MESMO IP.")
        sys.exit(1)
    else:
        print("\n⚠️  IPs parcialmente duplicados.")
        sys.exit(2)


if __name__ == "__main__":
    main()