"""
Railway / production entrypoint.

1. Downloads latest MSHA Open Government files if missing
2. Runs the ingest if the DuckDB does not exist (or FORCE_INGEST=1)
3. Starts uvicorn on $PORT (Railway injects this)
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

RAW_DIR = ROOT / "data" / "raw"
DB_PATH = ROOT / "data" / "processed" / "competitor_map.duckdb"

# Official MSHA Open Government endpoints (updated every Friday)
MSHA_FILES = {
    "Mines.zip": "https://arlweb.msha.gov/OpenGovernmentData/DataSets/Mines.zip",
    "MinesProdQuarterly.zip": "https://arlweb.msha.gov/OpenGovernmentData/DataSets/MinesProdQuarterly.zip",
}


def download_if_needed() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    for name, url in MSHA_FILES.items():
        dest = RAW_DIR / name
        if dest.exists() and dest.stat().st_size > 1_000_000:
            print(f"[start] {name} already present ({dest.stat().st_size / 1e6:.1f} MB)")
            continue
        print(f"[start] Downloading {name} …")
        try:
            with httpx.stream("GET", url, follow_redirects=True, timeout=120.0) as r:
                r.raise_for_status()
                with open(dest, "wb") as f:
                    for chunk in r.iter_bytes():
                        f.write(chunk)
            print(f"[start]   → {dest.stat().st_size / 1e6:.1f} MB")
        except Exception as e:
            print(f"[start] WARNING: failed to download {name}: {e}")
            if dest.exists():
                dest.unlink(missing_ok=True)


def ensure_db() -> None:
    force = os.environ.get("FORCE_INGEST", "").lower() in ("1", "true", "yes")
    if DB_PATH.exists() and not force:
        print(f"[start] Database exists ({DB_PATH})")
        return
    print("[start] Running MSHA ingest …")
    from src.ingest.run_ingest import main as run_ingest
    run_ingest()


def main() -> None:
    print("=" * 60)
    print("Silvi Competitor Map – Railway start")
    print("=" * 60)

    download_if_needed()
    ensure_db()

    port = int(os.environ.get("PORT", "8000"))
    print(f"[start] Starting uvicorn on 0.0.0.0:{port}")
    import uvicorn
    uvicorn.run(
        "src.api.main:app",
        host="0.0.0.0",
        port=port,
        workers=1,          # DuckDB is not multi-process friendly without care
        log_level="info",
    )


if __name__ == "__main__":
    main()
