"""Wait for the shared isolated PostgreSQL instance and enumerate its databases.

Uses the bundled psql so we do not depend on anything being on PATH.
"""

from __future__ import annotations

import json
import os
import subprocess
import time

BIN = os.path.abspath(".local/pg16/pgsql/bin")
PSQL = os.path.join(BIN, "psql.exe")
HOST, PORT, USER = "127.0.0.1", "55432", "postgres"

env = dict(os.environ)
env["PATH"] = BIN + os.pathsep + env.get("PATH", "")
env["PGPASSWORD"] = "postgres"

deadline = time.time() + 90
ready = False
last = ""
while time.time() < deadline:
    proc = subprocess.run(
        [PSQL, "-h", HOST, "-p", PORT, "-U", USER, "-d", "postgres",
         "-tAc", "select version()"],
        capture_output=True, text=True, env=env, timeout=30,
    )
    last = (proc.stdout or proc.stderr or "").strip()
    if proc.returncode == 0 and last:
        ready = True
        break
    time.sleep(3)

payload: dict = {"ready": ready, "version": last if ready else None, "last_error": None if ready else last}

if ready:
    dbs = subprocess.run(
        [PSQL, "-h", HOST, "-p", PORT, "-U", USER, "-d", "postgres",
         "-tAc", "select datname from pg_database where datistemplate = false order by datname"],
        capture_output=True, text=True, env=env, timeout=30,
    )
    payload["databases"] = [line for line in dbs.stdout.splitlines() if line.strip()]
    payload["dbs_exit"] = dbs.returncode

    # Report the table count of the two databases the team is actively using.
    counts = {}
    for db in ("hpc_test", "hpc_t05_2", "hpc_qa_mig"):
        q = subprocess.run(
            [PSQL, "-h", HOST, "-p", PORT, "-U", USER, "-d", db,
             "-tAc", "select count(*) from pg_tables where schemaname='public'"],
            capture_output=True, text=True, env=env, timeout=30,
        )
        counts[db] = {"exit": q.returncode, "public_tables": (q.stdout or q.stderr).strip()}
    payload["public_tables"] = counts

with open(".local/pg_restart_check.json", "w", encoding="utf-8") as fh:
    json.dump(payload, fh, indent=2, ensure_ascii=False)
print(json.dumps(payload, indent=2, ensure_ascii=False))
