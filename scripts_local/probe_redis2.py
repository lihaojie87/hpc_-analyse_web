"""Probe the isolated Redis endpoints and report raw socket state.

Deliberately speaks raw RESP over a plain socket so the result does not depend
on redis-py's protocol negotiation.
"""

from __future__ import annotations

import json
import socket

CANDIDATES = [56379, 6379]


def probe(port: int) -> dict:
    out: dict = {"port": port, "tcp_connect": False, "ping": None, "info_version": None, "error": None}
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(2.0)
    try:
        s.connect(("127.0.0.1", port))
        out["tcp_connect"] = True
        s.sendall(b"PING\r\n")
        out["ping"] = s.recv(256).decode("utf-8", "replace").strip()
        s.sendall(b"INFO server\r\n")
        buf = b""
        while b"redis_version" not in buf and len(buf) < 8192:
            chunk = s.recv(4096)
            if not chunk:
                break
            buf += chunk
        for line in buf.decode("utf-8", "replace").splitlines():
            if line.startswith("redis_version:"):
                out["info_version"] = line.strip()
    except OSError as exc:
        out["error"] = f"{type(exc).__name__}: {exc} (winerror={getattr(exc, 'winerror', None)})"
    finally:
        s.close()
    return out


results = [probe(p) for p in CANDIDATES]
payload = {
    "results": results,
    "reachable": [r["port"] for r in results if r["tcp_connect"]],
    "unreachable": [r["port"] for r in results if not r["tcp_connect"]],
}
with open(".local/redis_probe_round2.json", "w", encoding="utf-8") as fh:
    json.dump(payload, fh, indent=2, ensure_ascii=False)
print(json.dumps(payload, indent=2, ensure_ascii=False))
