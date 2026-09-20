"""Probe which loopback ports can actually be bound.

Read-only with respect to the OS state: each socket is opened, bound, then
immediately closed. Nothing is left listening.
"""

from __future__ import annotations

import json
import socket

CANDIDATES = [55432, 55433, 5432, 15432, 25432, 45432, 55434, 55435, 60000]

results = []
for port in CANDIDATES:
    entry = {"port": port, "bind_ok": False, "error": None}
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # Match PostgreSQL's behaviour: it does not set SO_REUSEADDR on Windows
    # by default, so we deliberately do not set it either.
    s.settimeout(2.0)
    try:
        s.bind(("127.0.0.1", port))
        entry["bind_ok"] = True
    except OSError as exc:
        entry["error"] = f"{type(exc).__name__}: {exc} (winerror={getattr(exc, 'winerror', None)})"
    finally:
        s.close()
    results.append(entry)

# Also report which candidate ports are currently occupied by a listener.
listening = {}
for port in CANDIDATES:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.settimeout(0.5)
    try:
        probe.connect(("127.0.0.1", port))
        listening[port] = True
    except OSError:
        listening[port] = False
    finally:
        probe.close()

payload = {
    "bind_results": results,
    "connecting": listening,
    "bindable": [r["port"] for r in results if r["bind_ok"]],
    "not_bindable": [r["port"] for r in results if not r["bind_ok"]],
}
with open(".local/bind_probe_result.json", "w", encoding="utf-8") as fh:
    json.dump(payload, fh, indent=2, ensure_ascii=False)
print(json.dumps(payload, indent=2, ensure_ascii=False))
