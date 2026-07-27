"""
FastAPI surface for the Silvi competitor map.

Endpoints match the status report:
  GET /api/health
  GET /api/producers          (GeoJSON)
  GET /api/plants
  GET /api/capacity/movers
  GET /api/capacity/operators
  GET /api/lettings           (stub)
  GET /api/opportunity/{id}   (stub)
  GET /api/prices             (stub – needs bid tabs)
  GET /api/contractors        (stub)
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, List
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import duckdb

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "processed" / "competitor_map.duckdb"

app = FastAPI(
    title="Silvi Competitor Map API",
    description="MSHA-derived competitive intelligence for aggregate producers in NJ/PA/DE/MD",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_con():
    if not DB_PATH.exists():
        raise HTTPException(
            status_code=503,
            detail="Database not built. Run: python -m src.ingest.run_ingest",
        )
    return duckdb.connect(str(DB_PATH), read_only=True)


@app.get("/api/health")
def health():
    try:
        con = get_con()
        n = con.execute("SELECT COUNT(*) FROM mines").fetchone()[0]
        con.close()
        return {"status": "ok", "mines": n, "db": str(DB_PATH)}
    except Exception as e:
        return {"status": "degraded", "error": str(e)}


@app.get("/api/producers")
def producers(
    state: Optional[str] = Query(None, description="Filter by state (NJ,PA,DE,MD)"),
    limit: int = Query(1000, ge=1, le=5000),
):
    """GeoJSON FeatureCollection of active producers, sized by latest hours."""
    con = get_con()
    sql = """
        SELECT
            m.mine_id,
            m.mine_name,
            m.operator_canonical AS operator,
            m.state,
            m.county,
            m.latitude,
            m.longitude,
            m.primary_canvass,
            m.current_status,
            COALESCE(c.latest_hours, 0) AS hours,
            c.yoy_pct_change
        FROM mines m
        LEFT JOIN v_capacity_movers c USING (mine_id)
        WHERE m.latitude IS NOT NULL AND m.longitude IS NOT NULL
    """
    params = []
    if state:
        sql += " AND m.state = ?"
        params.append(state.upper())
    sql += " LIMIT ?"
    params.append(limit)

    rows = con.execute(sql, params).fetchall()
    cols = [d[0] for d in con.description]
    con.close()

    features = []
    for row in rows:
        d = dict(zip(cols, row))
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [d["longitude"], d["latitude"]],
            },
            "properties": {
                k: v for k, v in d.items() if k not in ("latitude", "longitude")
            },
        })

    return {
        "type": "FeatureCollection",
        "features": features,
        "meta": {"count": len(features)},
    }


@app.get("/api/plants")
def plants(state: Optional[str] = None, operator: Optional[str] = None):
    con = get_con()
    sql = "SELECT * FROM v_active_producers WHERE 1=1"
    params = []
    if state:
        sql += " AND state = ?"
        params.append(state.upper())
    if operator:
        sql += " AND operator ILIKE ?"
        params.append(f"%{operator}%")
    rows = con.execute(sql, params).fetchdf()
    con.close()
    return rows.to_dict(orient="records")


@app.get("/api/capacity/movers")
def capacity_movers(limit: int = Query(50, ge=1, le=200)):
    con = get_con()
    rows = con.execute(
        "SELECT * FROM v_capacity_movers LIMIT ?", [limit]
    ).fetchdf()
    con.close()
    return rows.to_dict(orient="records")


@app.get("/api/capacity/operators")
def capacity_operators(limit: int = Query(50, ge=1, le=200)):
    con = get_con()
    rows = con.execute(
        "SELECT * FROM v_operator_capacity LIMIT ?", [limit]
    ).fetchdf()
    con.close()
    return rows.to_dict(orient="records")


# --- Stubs for demand-side pieces (need bid tabs + lettings data) ---

@app.get("/api/lettings")
def lettings():
    return {
        "status": "stub",
        "message": "NJDOT lettings enabled once calendar scraper is live; PennDOT/DelDOT/MDOT still disabled.",
        "items": [],
    }


@app.get("/api/opportunity/{opp_id}")
def opportunity(opp_id: str):
    return {"status": "stub", "id": opp_id}


@app.get("/api/prices")
def prices():
    return {
        "status": "stub",
        "message": "Requires bid-tab PDFs in data/raw/bidtabs/ + ANTHROPIC_API_KEY",
    }


@app.get("/api/contractors")
def contractors():
    return {"status": "stub", "message": "Populated from bid-tab extraction"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.api.main:app", host="0.0.0.0", port=8000, reload=True)
