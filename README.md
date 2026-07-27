# Silvi Competitor Map

Competitive intelligence system for aggregate producers (sand, gravel, stone) across **NJ / PA / DE / MD**, built on live federal MSHA data.

## What works today

| Component | Status | Notes |
|-----------|--------|-------|
| MSHA Mines ingest | ✅ | Robust parser handles embedded newlines in `DIRECTIONS_TO_MINE` |
| Quarterly employment | ✅ |  Hours used as production proxy |
| Entity resolution | ✅ | 199 → 177 operators; New Enterprise consolidated correctly |
| Capacity movers view | ✅ | Recency floor prevents 2006–2009 closures from ranking as “movers” |
| Operator league table | ✅ | |
| GeoJSON API + map | ✅ | Points sized by hours, colored by YoY |
| Valhalla HGV routing | ⚠️ | Client ready; public instance TLS-blocked from some sandboxes → haversine fallback labeled |
| NJDOT bid-tab extractor | 📝 | Written against real layout; needs PDFs + API key |
| Letting calendars | 📝 | NJDOT path known; others stubbed |

## Quick start (local)

```bash
git clone https://github.com/doron333/silvi-competitor-map.git
cd silvi-competitor-map
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Option A – start.py downloads the MSHA files and serves the map
python start.py

# Option B – manual
# Download Mines.zip + MinesProdQuarterly.zip into data/raw/ from
# https://arlweb.msha.gov/OpenGovernmentData/OGIMSHA.asp
python -m src.ingest.run_ingest
uvicorn src.api.main:app --reload --port 8000
```

Then open http://localhost:8000 (the map) or the API endpoints under /api/...

## Deploy on Railway

1. railway.app → New Project → Deploy from GitHub repo → select `doron333/silvi-competitor-map`
2. Railway detects the Procfile / railway.toml and runs `python start.py`
3. First deploy takes 1–3 minutes (downloads ~60 MB of MSHA data + builds DuckDB)
4. Map is live at your Railway public URL

Optional env vars:
- `FORCE_INGEST=1` – force re-download + rebuild on next restart
- `PORT` – injected automatically by Railway

Note: DuckDB lives on the container filesystem. Attach a Railway Volume at `/app/data` if you want the database to survive restarts.

## Four real bugs that were fixed during the original build

1. **DuckDB `ignore_errors=true` silently dropped 28 394 of 91 919 rows**  
   Embedded newlines inside quoted `DIRECTIONS_TO_MINE` fields caused the entire MD + DE + half of PA to vanish. Fixed with a proper CSV state-machine (Python `csv` module).

2. **SQL comment containing a semicolon** (`-- convert CY/SY to tons; 1.0 when…`)  
   Split a `CREATE TABLE` in half. Comment stripper now runs before statement splitting.

3. **Legal-suffix stripping ran mid-name**  
   “New Enterprise Stone & Lime” became “new stone lime”. Suffixes now strip only from the tail.

4. **Capacity movers surfaced 2006–2009 closures**  
   A mine’s final reported quarter always looks like a catastrophic drop. Added an explicit recency floor (last ~3 years).

## Signal currently visible on real data

- Amrize Whitehall (Lehigh Co, PA) +121 % YoY hours  
- Savage Stone & Amrize Hagerstown idling ≈ 35 %  
- Operator league led by Heidelberg / New Enterprise (dozens of sites)

## Project layout

```
src/
  ingest/
    msha_parser.py      # robust | delimited reader
    entity_resolver.py  # operator name collapse
    run_ingest.py       # end-to-end loader
  db/
    schema.sql          # tables + analytical views
  api/
    main.py             # FastAPI
data/
  raw/                  # drop the MSHA zips here
  processed/            # competitor_map.duckdb
frontend/               # (optional simple Leaflet map)
```

## Next pieces (not yet live)

- Drop real NJDOT bid-tab PDFs into `data/raw/bidtabs/` and supply `ANTHROPIC_API_KEY` to unlock unit prices, quantities, and contractor lead lists.
- Point the Valhalla client at a reachable instance (or self-hosted) so haul-distance rankings use real HGV costing instead of the labeled haversine fallback.
- Enable PennDOT / DelDOT / MDOT letting calendars once their public listing paths are verified.

## Caveat

Lettings currently geocode to **county centroid**, not jobsite. Good enough for ranking opportunities by haul distance; not good enough to quote. The API will flag this and expose `POST /lettings/{id}/location` once the demand side is wired.
