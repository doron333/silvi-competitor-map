"""
End-to-end MSHA ingest for the Silvi competitor map.

Usage (from project root, after placing the zip files in data/raw/):

    python -m src.ingest.run_ingest

Expected files in data/raw/ (download from MSHA Open Government portal):
  - Mines.zip
  - MinesProdQuarterly.zip   (or the employment quarterly file)
  - ControllerOperatorHistory.zip  (optional)
"""

from __future__ import annotations

import sys
from pathlib import Path
from datetime import datetime
from typing import Optional

import duckdb

# Allow running as module
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.ingest.msha_parser import iter_msha_records, filter_active_aggregates, TARGET_STATES
from src.ingest.entity_resolver import OperatorResolver

DB_PATH = ROOT / "data" / "processed" / "competitor_map.duckdb"
RAW_DIR = ROOT / "data" / "raw"
SCHEMA_PATH = ROOT / "src" / "db" / "schema.sql"


def _to_float(v) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(str(v).replace(",", ""))
    except (ValueError, TypeError):
        return None


def _to_int(v) -> Optional[int]:
    if v is None:
        return None
    try:
        return int(float(str(v).replace(",", "")))
    except (ValueError, TypeError):
        return None


def _to_date(v) -> Optional[str]:
    if not v:
        return None
    # MSHA often uses MM/DD/YYYY
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y"):
        try:
            return datetime.strptime(str(v).strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return None


def load_mines(con: duckdb.DuckDBPyConnection, resolver: OperatorResolver) -> int:
    mines_path = RAW_DIR / "Mines.zip"
    if not mines_path.exists():
        # also accept plain text
        candidates = list(RAW_DIR.glob("*ines*"))
        if not candidates:
            raise FileNotFoundError(f"Place Mines.zip (or Mines.txt) in {RAW_DIR}")
        mines_path = candidates[0]

    print(f"Parsing mines from {mines_path.name} ...")
    records = list(filter_active_aggregates(iter_msha_records(mines_path)))
    print(f"  → {len(records)} active aggregate operations in {sorted(TARGET_STATES)}")

    rows = []
    for r in records:
        op_raw = r.get("CURRENT_OPERATOR_NAME") or r.get("OPERATOR_NAME")
        op_canon = resolver.add(op_raw)
        rows.append((
            r.get("MINE_ID"),
            r.get("CURRENT_MINE_NAME") or r.get("MINE_NAME"),
            op_raw,
            op_canon,
            r.get("CURRENT_CONTROLLER_NAME"),
            (r.get("STATE") or "").upper(),
            r.get("FIPS_CNTY_NM") or r.get("COUNTY"),
            _to_int(r.get("FIPS_CNTY_CD")),
            _to_float(r.get("LATITUDE")),
            _to_float(r.get("LONGITUDE")),
            _to_int(r.get("PRIMARY_CANVASS_CD")),
            r.get("PRIMARY_CANVASS"),
            r.get("PRIMARY_SIC") or r.get("PRIMARY_SIC_CD_1"),
            r.get("CURRENT_MINE_STATUS"),
            _to_date(r.get("CURRENT_STATUS_DT")),
            r.get("DIRECTIONS_TO_MINE"),
            r.get("NEAREST_TOWN"),
            r.get("COMPANY_TYPE"),
            _to_int(r.get("NO_EMPLOYEES")),
        ))

    con.execute("DELETE FROM mines")
    con.executemany(
        """
        INSERT INTO mines (
            mine_id, mine_name, operator_raw, operator_canonical, controller_raw,
            state, county, fips_cnty_cd, latitude, longitude,
            primary_canvass_cd, primary_canvass, primary_sic,
            current_status, status_date, directions, nearest_town,
            company_type, no_employees
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    return len(rows)


def load_employment(con: duckdb.DuckDBPyConnection) -> int:
    emp_path = RAW_DIR / "MinesProdQuarterly.zip"
    if not emp_path.exists():
        candidates = list(RAW_DIR.glob("*Prod*Quarterly*")) + list(RAW_DIR.glob("*employment*"))
        if not candidates:
            print("  (no quarterly employment file found – skipping)")
            return 0
        emp_path = candidates[0]

    print(f"Parsing employment from {emp_path.name} ...")
    # We only keep rows that match mines we already loaded
    mine_ids = {r[0] for r in con.execute("SELECT mine_id FROM mines").fetchall()}

    rows = []
    for r in iter_msha_records(emp_path):
        mid = r.get("MINE_ID")
        if mid not in mine_ids:
            continue
        year = _to_int(r.get("CALENDAR_YR") or r.get("CALENDAR_YEAR"))
        qtr = _to_int(r.get("CALENDAR_QTR") or r.get("QTR"))
        if year is None or qtr is None:
            continue
        rows.append((
            mid,
            year,
            qtr,
            r.get("SUBUNIT_CD") or r.get("SUBUNIT") or "03",
            _to_float(r.get("AVG_EMPLOYEE_CNT") or r.get("AVG_NBR_EMPLOYEES")),
            _to_float(r.get("EMPLOYEE_HOURS") or r.get("HOURS_WORKED")),
            _to_float(r.get("COAL_PRODUCTION") or r.get("PRODUCTION")),
        ))

    con.execute("DELETE FROM employment_quarterly")
    if rows:
        con.executemany(
            """
            INSERT INTO employment_quarterly (
                mine_id, calendar_year, calendar_qtr, subunit_cd,
                avg_employee_cnt, employee_hours, coal_production
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
    print(f"  → {len(rows)} quarterly employment records")
    return len(rows)


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("Silvi Competitor Map – MSHA Ingest")
    print("=" * 60)

    con = duckdb.connect(str(DB_PATH))
    schema_sql = SCHEMA_PATH.read_text()
    # Simple comment stripper that does not choke on semicolons inside comments
    cleaned = []
    for line in schema_sql.splitlines():
        if "--" in line:
            line = line[: line.index("--")]
        cleaned.append(line)
    con.execute("\n".join(cleaned))

    resolver = OperatorResolver()

    n_mines = load_mines(con, resolver)
    n_emp = load_employment(con)

    stats = resolver.stats()
    print()
    print("Entity resolution:")
    print(f"  {stats['raw_variants']} raw operator strings → {stats['canonical_operators']} real companies")

    # Quick signal check
    movers = con.execute("""
        SELECT mine_name, operator, state, yoy_pct_change, latest_hours
        FROM v_capacity_movers
        WHERE yoy_pct_change IS NOT NULL
        ORDER BY ABS(yoy_pct_change) DESC
        LIMIT 8
    """).fetchall()

    print()
    print("Top capacity movers (real signal, recency-filtered):")
    for m in movers:
        print(f"  {m[0][:40]:<40} {m[1][:25]:<25} {m[2]}  {m[3]:+.1f}%  ({m[4]:,.0f} hrs)")

    geocoded = con.execute("SELECT COUNT(*) FROM mines WHERE latitude IS NOT NULL").fetchone()[0]
    print()
    print(f"Done. {n_mines} active operations ({geocoded} geocoded), {n_emp} employment rows.")
    print(f"Database: {DB_PATH}")
    con.close()


if __name__ == "__main__":
    main()
