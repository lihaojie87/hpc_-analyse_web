"""Diagnose the local test PostgreSQL state: processes, ports, data dirs, logs.

Test-only diagnostics. Reads process metadata and log tails; changes nothing.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / ".local"
RESULT: dict[str, object] = {}

PS_LIST = (
    "$p = Get-CimInstance Win32_Process -Filter \"Name='postgres.exe'\" | "
    "Select-Object ProcessId,ParentProcessId,ExecutablePath,CommandLine; "
    "$p | ConvertTo-Json -Compress"
)


def powershell(command: str, name: str) -> None:
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        text=True,
        timeout=90,
    )
    RESULT[name] = {
        "rc": completed.returncode,
        "stdout": (completed.stdout or "")[-4000:],
        "stderr": (completed.stderr or "")[-1500:],
    }


def main() -> None:
    powershell(PS_LIST, "postgres_processes")
    powershell("netstat -ano | Select-String ':55432'", "port_55432")
    powershell("netstat -ano | Select-String ':56379'", "port_56379")
    powershell("Get-ChildItem -Force 'C:/Users/lihaojie/hpc-pgtest' -ErrorAction SilentlyContinue | Select-Object Name | ConvertTo-Json -Compress", "hpc_pgtest_dir")

    local_dirs = {}
    for candidate in (".local/pgdata", ".local/pg16"):
        path = ROOT / candidate
        local_dirs[candidate] = {"exists": path.exists()}
    postmaster = LOCAL / "pgdata" / "postmaster.pid"
    if postmaster.is_file():
        local_dirs["postmaster_pid"] = postmaster.read_text(encoding="utf-8", errors="replace")[:400]
    RESULT["local_dirs"] = local_dirs

    for log_name in ("pg.log", "pg16.log"):
        log_path = LOCAL / log_name
        if log_path.is_file():
            RESULT[f"log_{log_name}"] = log_path.read_text(encoding="utf-8", errors="replace")[-3000:]

    (LOCAL / "pg_diag_result.json").write_text(json.dumps(RESULT, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
