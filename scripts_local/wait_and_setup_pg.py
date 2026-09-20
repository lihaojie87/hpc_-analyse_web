"""Wait for the local test PostgreSQL to finish recovery, then provision test databases.

Test-only. Polls ``pg_isready`` with a bounded timeout, creates ``hpc_test`` /
``hpc_drill`` if missing, runs Alembic to head against ``hpc_test``, and records
everything in ``.local/pg_ready_result.json``. Never touches production.
"""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / ".local"
BIN = LOCAL / "pg16" / "pgsql" / "bin"
BACKEND = ROOT / "backend"
PORT = 55432
SUPERUSER = "postgres"
URL_ASYNC = f"postgresql+asyncpg://{SUPERUSER}@127.0.0.1:{PORT}/hpc_test"
URL_SYNC = f"postgresql+psycopg://{SUPERUSER}@127.0.0.1:{PORT}/hpc_test"
RESULT: dict[str, object] = {}
DEADLINE_SECONDS = 900


def record(name: str, completed: subprocess.CompletedProcess[str]) -> subprocess.CompletedProcess[str]:
    RESULT[name] = {
        "rc": completed.returncode,
        "stdout_tail": (completed.stdout or "")[-1500:],
        "stderr_tail": (completed.stderr or "")[-1500:],
    }
    return completed


def run(name: str, args: list[str], timeout: int = 300, cwd: Path | None = None, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    import os

    merged = dict(os.environ)
    if env:
        merged.update(env)
    return record(name, subprocess.run(args, capture_output=True, text=True, timeout=timeout, cwd=cwd, env=merged))


def wait_ready() -> bool:
    started = time.time()
    while time.time() - started < DEADLINE_SECONDS:
        probe = subprocess.run(
            [str(BIN / "pg_isready.exe"), "-h", "127.0.0.1", "-p", str(PORT), "-U", SUPERUSER],
            capture_output=True,
            text=True,
        )
        if probe.returncode == 0:
            RESULT["wait_seconds"] = round(time.time() - started, 1)
            return True
        time.sleep(3)
    RESULT["wait_seconds"] = round(time.time() - started, 1)
    return False


def main() -> None:
    RESULT["ready"] = wait_ready()
    if not RESULT["ready"]:
        (LOCAL / "pg_ready_result.json").write_text(json.dumps(RESULT, indent=2, ensure_ascii=False), encoding="utf-8")
        return

    run("version", [str(BIN / "psql.exe"), "-h", "127.0.0.1", "-p", str(PORT), "-U", SUPERUSER, "-d", "postgres", "-tAc", "select version()"])

    for db in ("hpc_test", "hpc_drill"):
        existing = run(f"exists_{db}", [str(BIN / "psql.exe"), "-h", "127.0.0.1", "-p", str(PORT), "-U", SUPERUSER, "-d", "postgres", "-tAc", f"select 1 from pg_database where datname='{db}'"])
        if (existing.stdout or "").strip() != "1":
            run(f"createdb_{db}", [str(BIN / "createdb.exe"), "-h", "127.0.0.1", "-p", str(PORT), "-U", SUPERUSER, db])

    python = str(BACKEND / ".venv" / "Scripts" / "python.exe")
    run(
        "alembic_upgrade",
        [python, "-m", "alembic", "upgrade", "head"],
        timeout=600,
        cwd=BACKEND,
        env={"HPC_ENV": "test", "HPC_DATABASE_URL": URL_SYNC, "HPC_JWT_SECRET": "x" * 40},
    )
    run(
        "alembic_current",
        [python, "-m", "alembic", "current"],
        timeout=300,
        cwd=BACKEND,
        env={"HPC_ENV": "test", "HPC_DATABASE_URL": URL_SYNC, "HPC_JWT_SECRET": "x" * 40},
    )
    run(
        "tables",
        [str(BIN / "psql.exe"), "-h", "127.0.0.1", "-p", str(PORT), "-U", SUPERUSER, "-d", "hpc_test", "-tAc", "select tablename from pg_tables where schemaname='public' order by tablename"],
    )
    RESULT["url_async"] = URL_ASYNC
    RESULT["url_sync"] = URL_SYNC
    (LOCAL / "pg_ready_result.json").write_text(json.dumps(RESULT, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
