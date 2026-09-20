"""Initialise and start the isolated test-only PostgreSQL 16 instance.

Test-only infrastructure bound to loopback. Never points at production.
Writes structured results to ``.local/pg_provision_result.json``.
"""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / ".local"
BIN = LOCAL / "pg16" / "pgsql" / "bin"
DATA = LOCAL / "pgdata"
LOG = LOCAL / "pg.log"
PORT = 55432
SUPERUSER = "postgres"
RESULTS: dict[str, object] = {}


def run(name: str, args: list[str], timeout: int = 300) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    RESULTS[name] = {
        "args": args,
        "rc": completed.returncode,
        "stdout_tail": (completed.stdout or "")[-600:],
        "stderr_tail": (completed.stderr or "")[-600:],
    }
    return completed


def main() -> None:
    RESULTS["bin_exists"] = {tool: (BIN / tool).is_file() for tool in ("initdb.exe", "pg_ctl.exe", "pg_dump.exe", "pg_restore.exe", "psql.exe", "createdb.exe")}

    if not (DATA / "PG_VERSION").is_file():
        run("initdb", [str(BIN / "initdb.exe"), "-D", str(DATA), "-U", SUPERUSER, "-A", "trust", "-E", "UTF8", "--locale=C"])

    status = run("pg_ctl_status", [str(BIN / "pg_ctl.exe"), "-D", str(DATA), "status"])
    if status.returncode != 0:
        run("pg_ctl_start", [str(BIN / "pg_ctl.exe"), "-D", str(DATA), "-l", str(LOG), "-o", f"-p {PORT} -c listen_addresses=127.0.0.1", "start"])
        for _ in range(40):
            probe = run("pg_isready", [str(BIN / "pg_isready.exe"), "-h", "127.0.0.1", "-p", str(PORT)])
            if probe.returncode == 0:
                break
            time.sleep(0.5)

    run("select_version", [str(BIN / "psql.exe"), "-h", "127.0.0.1", "-p", str(PORT), "-U", SUPERUSER, "-d", "postgres", "-tAc", "select version()"])

    for db in ("hpc_test", "hpc_drill"):
        existing = run(f"exists_{db}", [str(BIN / "psql.exe"), "-h", "127.0.0.1", "-p", str(PORT), "-U", SUPERUSER, "-d", "postgres", "-tAc", f"select 1 from pg_database where datname='{db}'"])
        if (existing.stdout or "").strip() != "1":
            run(f"createdb_{db}", [str(BIN / "createdb.exe"), "-h", "127.0.0.1", "-p", str(PORT), "-U", SUPERUSER, db])
        run(f"list_{db}", [str(BIN / "psql.exe"), "-h", "127.0.0.1", "-p", str(PORT), "-U", SUPERUSER, "-d", db, "-tAc", "select current_database()"])

    RESULTS["url"] = f"postgresql+asyncpg://{SUPERUSER}@127.0.0.1:{PORT}/hpc_test"
    LOCAL.mkdir(parents=True, exist_ok=True)
    (LOCAL / "pg_provision_result.json").write_text(json.dumps(RESULTS, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
