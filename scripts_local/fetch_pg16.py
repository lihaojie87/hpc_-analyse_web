"""Download and extract the portable PostgreSQL 16 Windows binaries for local testing.

Test-only infrastructure: extracts into ``hpc-perf-platform/.local/pg16`` and never
touches production databases or services.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

URL = "https://get.enterprisedb.com/postgresql/postgresql-16.6-1-windows-x64-binaries.zip"
ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / ".local"
ARCHIVE = LOCAL / "pg16-binaries.zip"
EXTRACT_ROOT = LOCAL / "pg16"
LOG = LOCAL / "fetch_pg16.log"


def log(message: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {message}"
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def download() -> None:
    if ARCHIVE.is_file() and ARCHIVE.stat().st_size > 300_000_000:
        log(f"archive already present size={ARCHIVE.stat().st_size}")
        return
    LOCAL.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(URL, headers={"User-Agent": "hpc-local-test-provisioner"})
    with urllib.request.urlopen(request, timeout=120) as response, ARCHIVE.open("wb") as target:
        total = int(response.headers.get("Content-Length") or 0)
        written = 0
        while chunk := response.read(1024 * 1024):
            target.write(chunk)
            written += len(chunk)
            if written % (20 * 1024 * 1024) < 1024 * 1024:
                log(f"downloaded {written}/{total} bytes")
    log(f"download complete size={ARCHIVE.stat().st_size}")


def extract() -> None:
    if (EXTRACT_ROOT / "pgsql" / "bin" / "initdb.exe").is_file():
        log("already extracted")
        return
    EXTRACT_ROOT.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(ARCHIVE) as archive:
        archive.extractall(EXTRACT_ROOT)
    log("extraction complete")


def verify() -> None:
    bin_dir = EXTRACT_ROOT / "pgsql" / "bin"
    result = {
        "archive": str(ARCHIVE),
        "archive_size": ARCHIVE.stat().st_size if ARCHIVE.is_file() else None,
        "bin_dir": str(bin_dir),
        "tools": {
            name: (bin_dir / name).is_file()
            for name in ("initdb.exe", "pg_ctl.exe", "pg_dump.exe", "pg_restore.exe", "psql.exe", "postgres.exe")
        },
    }
    (LOCAL / "fetch_pg16_result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    log(f"verify {result['tools']}")


if __name__ == "__main__":
    try:
        download()
        extract()
        verify()
        log("OK")
    except Exception as exc:  # noqa: BLE001
        log(f"FAILED {exc!r}")
        sys.exit(1)
