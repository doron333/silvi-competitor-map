"""
Robust MSHA Open Government data parsers.

MSHA files are pipe-delimited (|) with a header row.
Some fields (notably DIRECTIONS_TO_MINE) contain embedded newlines
and are quote-wrapped. Using DuckDB's ignore_errors=true silently
drops tens of thousands of rows (MD + DE + half of PA in testing).

This module uses Python's csv module in a streaming fashion so that
quoted multi-line fields are handled correctly.
"""

from __future__ import annotations

import csv
import io
import zipfile
from pathlib import Path
from typing import Iterator, Dict, Any, List, Optional

# Primary canvass codes of interest for aggregates
SAND_GRAVEL_CANVASS = 5
STONE_CANVASS = 6
TARGET_CANVASSES = {SAND_GRAVEL_CANVASS, STONE_CANVASS}

TARGET_STATES = {"NJ", "PA", "DE", "MD"}


def _open_text_from_zip_or_file(path: Path) -> io.TextIOWrapper:
    """Open a .zip (first .txt/.csv inside) or plain text file as text."""
    path = Path(path)
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path, "r") as zf:
            # Prefer the largest text-like member
            members = [m for m in zf.namelist() if m.lower().endswith((".txt", ".csv", ".dat"))]
            if not members:
                members = zf.namelist()
            member = max(members, key=lambda m: zf.getinfo(m).file_size)
            raw = zf.read(member)
            return io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8", errors="replace")
    else:
        return open(path, "r", encoding="utf-8", errors="replace", newline="")


def iter_msha_records(
    path: Path | str,
    *,
    required_fields: Optional[List[str]] = None,
) -> Iterator[Dict[str, str]]:
    """
    Stream records from an MSHA pipe-delimited file (or zip containing one).

    Handles:
    - | delimiter
    - quoted fields that contain | or embedded newlines
    - UTF-8 with occasional bad bytes
    """
    path = Path(path)
    with _open_text_from_zip_or_file(path) as f:
        reader = csv.DictReader(f, delimiter="|", quotechar='"', restkey="_extra")
        if required_fields:
            missing = set(required_fields) - set(reader.fieldnames or [])
            if missing:
                raise ValueError(f"Missing expected columns in {path.name}: {sorted(missing)}")

        for row in reader:
            # Normalize empty strings to None-like for downstream
            cleaned = {k: (v.strip() if isinstance(v, str) and v.strip() != "" else None) for k, v in row.items()}
            yield cleaned


def filter_active_aggregates(
    records: Iterator[Dict[str, Any]],
    states: set[str] = TARGET_STATES,
) -> Iterator[Dict[str, Any]]:
    """
    Keep only active (or intermittently active) sand/gravel/stone operations
    in the target states.
    """
    for r in records:
        state = (r.get("STATE") or "").upper()
        if state not in states:
            continue

        # Canvass codes: PRIMARY_CANVASS_CD or PRIMARY_CANVASS
        canvass_raw = r.get("PRIMARY_CANVASS_CD") or r.get("PRIMARY_CANVASS") or ""
        try:
            canvass = int(str(canvass_raw).strip())
        except (ValueError, TypeError):
            canvass = None

        if canvass not in TARGET_CANVASSES:
            # Also accept by name if code is missing
            name = (r.get("PRIMARY_CANVASS") or "").upper()
            if "SAND" not in name and "GRAVEL" not in name and "STONE" not in name:
                continue

        status = (r.get("CURRENT_MINE_STATUS") or "").upper()
        # Keep Active and Intermittent; drop Abandoned, NonProducing, etc.
        if status not in {"ACTIVE", "INTERMITTENT"}:
            continue

        yield r


def parse_mines_file(path: Path | str) -> List[Dict[str, Any]]:
    """Convenience: return list of active aggregate mines in NJ/PA/DE/MD."""
    records = iter_msha_records(
        path,
        required_fields=["MINE_ID", "CURRENT_MINE_NAME", "STATE", "CURRENT_MINE_STATUS"],
    )
    return list(filter_active_aggregates(records))
