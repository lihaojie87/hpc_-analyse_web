"""Isolated T05.3 backup manifest and recovery checks."""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from scripts import backup_restore
from scripts.backup_restore import (
    backup_postgres,
    check_provenance,
    is_safe_test_url,
    preflight,
    resolve_pg_tool,
    restore_postgres,
    subprocess_env,
    validate_dump,
    verify_manifest,
    write_manifest,
)


class _FakeCompletedProcess:
    """Minimal stand-in for subprocess.CompletedProcess in injected tests."""

    def __init__(self, returncode: int = 0, stderr: str = "", stdout: str = "") -> None:
        self.returncode = returncode
        self.stderr = stderr
        self.stdout = stdout

SAFE_URL = "postgresql://tester:secret@localhost:5432/hpc_test"


def test_preflight_blocks_missing_postgres_without_sqlite_substitution(monkeypatch):
    monkeypatch.delenv("HPC_POSTGRES_TEST_URL", raising=False)
    result = preflight("backup")
    assert result.status == "BLOCKED"
    assert "HPC_POSTGRES_TEST_URL" in result.reason


def test_preflight_rejects_sqlite_and_production_urls():
    assert is_safe_test_url("postgresql://tester:secret@localhost:5432/hpc_test")
    assert not is_safe_test_url("sqlite+aiosqlite:///./hpc.db")
    assert not is_safe_test_url("postgresql://tester:secret@production-db:5432/hpc")
    # F1: production-looking URL must be refused through preflight, not only is_safe_test_url.
    assert preflight("backup", "postgresql://u:p@production-db:5432/hpc").status == "BLOCKED"
    assert preflight("backup", "sqlite+aiosqlite:///./hpc.db").status == "BLOCKED"


def test_is_safe_test_url_accepts_non_hostname_prod_tokens():
    # F4: forbidden tokens in dbname must not reject a legitimate loopback/test host.
    assert is_safe_test_url("postgresql://tester:secret@localhost:5432/hpc_prod")
    assert is_safe_test_url("postgresql://tester:secret@hpc-test-db:5432/hpc")


def test_is_safe_test_url_tightened_hostname_contract():
    # F4 residual: non-loopback IP literal rejected.
    assert not is_safe_test_url("postgresql://tester:secret@10.0.0.5:5432/hpc_test")
    # F4 residual: marker-less custom alias rejected.
    assert not is_safe_test_url("postgresql://tester:secret@db.internal:5432/hpc_test")
    # F4 residual: production token in userinfo (username or password) rejected,
    # even when the hostname itself looks safe.
    assert not is_safe_test_url("postgresql://prod_user:secret@localhost:5432/hpc_test")
    assert not is_safe_test_url("postgresql://user:prodpass@localhost:5432/hpc_test")
    # Positive controls: loopback and test-marked hosts accepted.
    assert is_safe_test_url("postgresql://tester:secret@127.0.0.1:5432/hpc_test")
    assert is_safe_test_url("postgresql://tester:secret@hpc-ci-db:5432/hpc_test")
    assert is_safe_test_url("postgresql://tester:secret@hpc-dev-db:5432/hpc")


def test_preflight_blocks_when_pg_dump_missing(monkeypatch):
    # F2/F8: "pg_dump missing" must be constructed deterministically. resolve_pg_tool
    # checks HPC_PG_BIN *before* PATH, so an inherited HPC_PG_BIN would still resolve
    # the real binary and invalidate this premise. Neutralise both lookups.
    monkeypatch.delenv("HPC_PG_BIN", raising=False)
    monkeypatch.setattr(shutil, "which", lambda name: None)
    result = preflight("backup", SAFE_URL)
    assert result.status == "BLOCKED"
    assert "pg_dump" in result.reason

    backup = backup_postgres(SAFE_URL, Path("unused"), "0004_outbox_events")
    assert backup.status == "BLOCKED"
    assert "pg_dump" in backup.reason


def test_restore_blocks_when_pg_restore_missing(monkeypatch, tmp_path: Path):
    # F2/F8: pg_dump present, pg_restore missing -> restore must be BLOCKED.
    dump = tmp_path / "postgres.full.dump"
    manifest_path = tmp_path / "postgres.full.manifest.json"
    dump.write_bytes(b"PGCUSTOM isolated test dump\n")
    write_manifest(dump, manifest_path, "postgres", "0004_outbox_events")

    # HPC_PG_BIN takes precedence over PATH in resolve_pg_tool, so clear it to make
    # this a real "pg_restore missing" scenario regardless of the caller's env.
    monkeypatch.delenv("HPC_PG_BIN", raising=False)
    monkeypatch.setattr(
        shutil,
        "which",
        lambda name: "/usr/bin/pg_dump" if name == "pg_dump" else None,
    )
    result = restore_postgres(manifest_path, SAFE_URL)
    assert result.status == "BLOCKED"
    assert "pg_restore" in result.reason


def test_manifest_roundtrip_and_tamper_detection(tmp_path: Path):
    dump = tmp_path / "postgres.full.dump"
    manifest_path = tmp_path / "postgres.full.manifest.json"
    dump.write_bytes(b"PGCUSTOM isolated test dump\n")
    manifest = write_manifest(dump, manifest_path, "postgres", "0004_outbox_events")
    assert manifest.redis_included is False
    assert verify_manifest(manifest_path).status == "PASS"

    dump.write_bytes(b"corrupted dump\n")
    result = verify_manifest(manifest_path)
    assert result.status == "FAIL"
    assert "SHA256" in result.reason


def test_verify_manifest_rejects_non_postgres_source(tmp_path: Path):
    # F3: a non-postgres source must fail verification even if hash/size match.
    dump = tmp_path / "dump"
    manifest_path = tmp_path / "manifest.json"
    dump.write_bytes(b"dump")
    write_manifest(dump, manifest_path, "postgres", "0004_outbox_events")
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))

    raw["source"] = "sqlite"
    manifest_path.write_text(json.dumps(raw), encoding="utf-8")
    result = verify_manifest(manifest_path)
    assert result.status == "FAIL"
    assert "source" in result.reason

    raw["source"] = "postgres"
    raw["redis_included"] = True
    manifest_path.write_text(json.dumps(raw), encoding="utf-8")
    result = verify_manifest(manifest_path)
    assert result.status == "FAIL"
    assert "Redis" in result.reason


def test_restore_postgres_blocks_non_postgres_source(tmp_path: Path):
    # F3: restore must return BLOCKED for a non-postgres manifest source.
    dump = tmp_path / "dump"
    manifest_path = tmp_path / "manifest.json"
    dump.write_bytes(b"dump")
    write_manifest(dump, manifest_path, "postgres", "0004_outbox_events")
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    raw["source"] = "sqlite"
    manifest_path.write_text(json.dumps(raw), encoding="utf-8")

    result = restore_postgres(manifest_path, SAFE_URL)
    assert result.status == "BLOCKED"
    assert "source" in result.reason


def test_check_provenance_enforces_postgres_only():
    assert check_provenance({"source": "postgres", "redis_included": False}).status == "PASS"
    assert check_provenance({"source": "sqlite", "redis_included": False}).status == "FAIL"
    assert check_provenance({"source": "postgres", "redis_included": True}).status == "FAIL"


def test_backup_dry_run_never_creates_sqlite_or_dump(tmp_path: Path, monkeypatch):
    # F8: pin the environment so the dry-run path is deterministic (a READY
    # preflight that stops before pg_dump), independent of HPC_PG_BIN / PATH.
    monkeypatch.delenv("HPC_PG_BIN", raising=False)
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/pg_dump")
    result = backup_postgres(
        "postgresql://tester:secret@localhost:5432/hpc_test",
        tmp_path,
        "0004_outbox_events",
        dry_run=True,
    )
    assert result.status == "DRY_RUN"
    assert not (tmp_path / "postgres.full.dump").exists()
    assert not (tmp_path / "postgres.full.manifest.json").exists()


def test_backup_dry_run_reason_states_not_executed(tmp_path: Path, monkeypatch):
    # F5: with prerequisites ready, dry-run reason must say it was not executed.
    # F8: clear HPC_PG_BIN so the monkeypatched PATH is the sole resolver.
    monkeypatch.delenv("HPC_PG_BIN", raising=False)
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/pg_dump")
    result = backup_postgres(SAFE_URL, tmp_path, "0004_outbox_events", dry_run=True)
    assert result.status == "DRY_RUN"
    assert "not executed" in result.reason


def test_manifest_records_postgres_source_only(tmp_path: Path):
    dump = tmp_path / "dump"
    manifest_path = tmp_path / "manifest.json"
    dump.write_bytes(b"dump")
    write_manifest(dump, manifest_path, "postgres", "0004_outbox_events")
    content = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert content["source"] == "postgres"
    assert content["redis_included"] is False
    assert content["alembic_head"] == "0004_outbox_events"


def test_backup_uses_order_independent_dbname_form(monkeypatch, tmp_path: Path):
    # F6: the URL must travel as a --dbname value, never a bare positional.
    captured: list[list[str]] = []
    url = "postgresql://tester:secret@localhost:5432/hpc_test"

    def fake_run(command, *, capture=True, env=None):
        captured.append(list(command))
        if command[0].endswith("pg_dump") or "pg_dump" in command[0]:
            Path(command[command.index("--file") + 1]).write_bytes(b"PGCUSTOM archive payload\n")
        return _FakeCompletedProcess(0)

    monkeypatch.setattr(backup_restore, "resolve_pg_tool", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(backup_restore, "run_command", fake_run)

    result = backup_postgres(url, tmp_path, "0004_outbox_events")
    assert result.status == "PASS"
    dump_cmd = captured[0]
    assert f"--dbname={url}" in dump_cmd
    assert url not in dump_cmd[1:], "URL must not be a bare positional argument"
    # post-dump validation ran pg_restore --list
    assert any("pg_restore" in item[0] and "--list" in item for item in captured)
    assert (tmp_path / "postgres.full.manifest.json").is_file()


def test_backup_emits_no_manifest_when_dump_missing(monkeypatch, tmp_path: Path):
    # Post-dump validation: pg_dump "succeeds" but writes nothing -> no manifest.
    def fake_run(command, *, capture=True, env=None):
        return _FakeCompletedProcess(0)

    monkeypatch.setattr(backup_restore, "resolve_pg_tool", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(backup_restore, "run_command", fake_run)

    result = backup_postgres(SAFE_URL, tmp_path, "0004_outbox_events")
    assert result.status == "FAIL"
    assert not (tmp_path / "postgres.full.manifest.json").exists()


def test_backup_emits_no_manifest_when_dump_empty(monkeypatch, tmp_path: Path):
    # Post-dump validation: a zero-byte dump must be rejected before the manifest.
    def fake_run(command, *, capture=True, env=None):
        if "pg_dump" in command[0]:
            Path(command[command.index("--file") + 1]).write_bytes(b"")
        return _FakeCompletedProcess(0)

    monkeypatch.setattr(backup_restore, "resolve_pg_tool", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(backup_restore, "run_command", fake_run)

    result = backup_postgres(SAFE_URL, tmp_path, "0004_outbox_events")
    assert result.status == "FAIL"
    assert "empty" in result.reason
    assert not (tmp_path / "postgres.full.manifest.json").exists()


def test_backup_emits_no_manifest_when_pg_restore_list_rejects(monkeypatch, tmp_path: Path):
    # Post-dump validation: a corrupt archive (pg_restore --list exit != 0) is refused.
    def fake_run(command, *, capture=True, env=None):
        if "pg_dump" in command[0]:
            Path(command[command.index("--file") + 1]).write_bytes(b"not a real custom archive\n")
            return _FakeCompletedProcess(0)
        return _FakeCompletedProcess(1, stderr="pg_restore: error: input file does not appear to be a valid archive")

    monkeypatch.setattr(backup_restore, "resolve_pg_tool", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(backup_restore, "run_command", fake_run)

    result = backup_postgres(SAFE_URL, tmp_path, "0004_outbox_events")
    assert result.status == "FAIL"
    assert "pg_restore --list" in result.reason
    assert not (tmp_path / "postgres.full.manifest.json").exists()


def test_validate_dump_flags_missing_file(tmp_path: Path):
    result = validate_dump(tmp_path / "absent.dump")
    assert result.status == "FAIL"
    assert "not created" in result.reason


def test_restore_uses_order_independent_dbname_form(monkeypatch, tmp_path: Path):
    # F6: pg_restore takes the target as --dbname, not a trailing positional pair.
    dump = tmp_path / "postgres.full.dump"
    manifest_path = tmp_path / "postgres.full.manifest.json"
    dump.write_bytes(b"PGCUSTOM archive payload\n")
    write_manifest(dump, manifest_path, "postgres", "0004_outbox_events")
    captured: list[list[str]] = []

    def fake_run(command, *, capture=True, env=None):
        captured.append(list(command))
        return _FakeCompletedProcess(0)

    monkeypatch.setattr(backup_restore, "resolve_pg_tool", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(backup_restore, "run_command", fake_run)

    result = restore_postgres(manifest_path, SAFE_URL)
    assert result.status == "PASS"
    restore_cmd = captured[0]
    assert f"--dbname={SAFE_URL}" in restore_cmd
    assert "--dbname" not in restore_cmd, "the space-separated --dbname form must be gone"


def test_resolve_pg_tool_prefers_hpc_pg_bin_over_path(monkeypatch, tmp_path: Path):
    # F7: with a cleaned PATH, HPC_PG_BIN must still resolve the tool.
    bin_dir = tmp_path / "pgbin"
    bin_dir.mkdir()
    exe_name = "pg_dump.exe" if os.name == "nt" else "pg_dump"
    (bin_dir / exe_name).write_bytes(b"")
    monkeypatch.setenv("HPC_PG_BIN", str(bin_dir))
    monkeypatch.setattr(shutil, "which", lambda name: None)

    resolved = resolve_pg_tool("pg_dump")
    assert resolved is not None
    assert Path(resolved).parent == bin_dir
    assert preflight("backup", SAFE_URL).status == "READY"


def test_resolve_pg_tool_falls_back_to_path(monkeypatch, tmp_path: Path):
    # F7: without HPC_PG_BIN, resolution still falls back to PATH.
    monkeypatch.delenv("HPC_PG_BIN", raising=False)
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
    assert resolve_pg_tool("pg_restore") == "/usr/bin/pg_restore"


def test_subprocess_env_prepends_hpc_pg_bin(monkeypatch, tmp_path: Path):
    # F7: the child PATH is prepended so sibling DLLs are discoverable.
    monkeypatch.setenv("HPC_PG_BIN", str(tmp_path))
    env = subprocess_env()
    assert env["PATH"].startswith(str(tmp_path))


def test_subprocess_env_without_hpc_pg_bin_is_plain(monkeypatch):
    monkeypatch.delenv("HPC_PG_BIN", raising=False)
    env = subprocess_env()
    assert env.get("PATH") == os.environ.get("PATH", env.get("PATH"))
