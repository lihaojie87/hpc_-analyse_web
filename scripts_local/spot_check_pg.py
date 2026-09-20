"""Read-only spot check of the isolated test PostgreSQL schema state."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / ".local" / "pg16" / "pgsql" / "bin"
PSQL = str(BIN / "psql.exe")
RESULT: dict[str, object] = {}

QUERIES = {
    "alembic_version": "select version_num from alembic_version",
    "table_count": "select count(*) from pg_tables where schemaname='public'",
    "tables": "select tablename from pg_tables where schemaname='public' order by 1",
    "source_snapshots_constraints": "select conname from pg_constraint where conrelid='source_snapshots'::regclass order by 1",
    "source_id_column": "select column_name, data_type, character_maximum_length from information_schema.columns where table_name='source_snapshots' and column_name in ('source_id','tombstone') order by 1",
}


def query(db: str, sql: str) -> dict[str, object]:
    completed = subprocess.run(
        [PSQL, "-h", "127.0.0.1", "-p", "55432", "-U", "postgres", "-d", db, "-tAc", sql],
        capture_output=True,
        text=True,
        timeout=120,
    )
    return {"rc": completed.returncode, "rows": [line for line in (completed.stdout or "").splitlines() if line.strip()], "err": (completed.stderr or "")[-400:]}


def main() -> None:
    for db in ("hpc_test", "hpc_drill", "hpc_qa_mig", "hpc_t05_2"):
        existing = subprocess.run(
            [PSQL, "-h", "127.0.0.1", "-p", "55432", "-U", "postgres", "-d", "postgres", "-tAc", f"select 1 from pg_database where datname='{db}'"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        RESULT.setdefault("databases", {})
        assert isinstance(RESULT["databases"], dict)
        if (existing.stdout or "").strip() != "1":
            RESULT["databases"][db] = "missing"
            continue
        RESULT["databases"][db] = {name: query(db, sql) for name, sql in QUERIES.items()}

    (ROOT / ".local" / "pg_spot_check.json").write_text(json.dumps(RESULT, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
