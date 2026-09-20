"""Independent raw-socket probe of the isolated test Redis (RESP2, no redis-py).

Confirms the server is reachable and reports its version without relying on the
application's client stack. Test-only.
"""
from __future__ import annotations

import json
import socket
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOST = "127.0.0.1"
PORT = 56379
RESULT: dict[str, object] = {}


def send_command(sock: socket.socket, *args: str) -> str:
    payload = f"*{len(args)}\r\n" + "".join(f"${len(a)}\r\n{a}\r\n" for a in args)
    sock.sendall(payload.encode())
    return sock.recv(65536).decode(errors="replace")


def main() -> None:
    netstat = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", f"netstat -ano | Select-String ':{PORT}'"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    RESULT["netstat"] = (netstat.stdout or "").strip() or "(no listener)"

    try:
        with socket.create_connection((HOST, PORT), timeout=8) as sock:
            RESULT["ping"] = send_command(sock, "PING")
            info = send_command(sock, "INFO", "server")
            for line in info.splitlines():
                if line.startswith(("redis_version:", "redis_mode:", "os:")):
                    RESULT.setdefault("info", [])
                    assert isinstance(RESULT["info"], list)
                    RESULT["info"].append(line)
            RESULT["hello_on_resp2"] = send_command(sock, "HELLO", "3")[:200]
    except Exception as exc:  # noqa: BLE001
        RESULT["error"] = repr(exc)

    (ROOT / ".local" / "redis_probe_lead.json").write_text(json.dumps(RESULT, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
