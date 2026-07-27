-- Silvi Competitor Map – DuckDB schema
-- Designed for MSHA Mines + Quarterly Employment + Controller history

CREATE TABLE IF NOT EXISTS mines (
    mine_id             VARCHAR PRIMARY KEY,
    mine_name           VARCHAR,
    operator_raw        VARCHAR,
    operator_canonical  VARCHAR,
    controller_raw      VARCHAR,
    state               VARCHAR,
    county              VARCHAR,
    fips_cnty_cd        INTEGER,
    latitude            DOUBLE,
    longitude           DOUBLE,
    primary_canvass_cd  INTEGER,
    primary_canvass     VARCHAR,
    primary_sic         VARCHAR,
    current_status      VARCHAR,
    status_date         DATE,
    directions          VARCHAR,
    nearest_town        VARCHAR,
    company_type        VARCHAR,
    no_employees        INTEGER,
    ingested_at         TIMESTAMP DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS employment_quarterly (
    mine_id             VARCHAR,
    calendar_year       INTEGER,
    calendar_qtr        INTEGER,          -- 1-4
    subunit_cd          VARCHAR,
    avg_employee_cnt    DOUBLE,
    employee_hours      DOUBLE,
    coal_production     DOUBLE,           -- null for MNM
    PRIMARY KEY (mine_id, calendar_year, calendar_qtr, subunit_cd)
);

CREATE TABLE IF NOT EXISTS ownership (
    mine_id             VARCHAR,
    controller_id       VARCHAR,
    controller_name     VARCHAR,
    operator_id         VARCHAR,
    operator_name       VARCHAR,
    start_date          DATE,
    end_date            DATE
);

-- Materialized analytical views (refreshed after each ingest)

CREATE OR REPLACE VIEW v_active_producers AS
SELECT
    m.mine_id,
    m.mine_name,
    m.operator_canonical AS operator,
    m.state,
    m.county,
    m.latitude,
    m.longitude,
    m.primary_canvass,
    m.primary_sic,
    m.current_status,
    m.nearest_town
FROM mines m
WHERE m.current_status IN ('Active', 'Intermittent')
  AND m.latitude IS NOT NULL
  AND m.longitude IS NOT NULL;

-- Latest complete quarter per mine (recency floor)
CREATE OR REPLACE VIEW v_latest_quarter AS
SELECT
    mine_id,
    MAX(calendar_year * 10 + calendar_qtr) AS latest_yq
FROM employment_quarterly
GROUP BY mine_id;

-- Capacity movers with recency floor (exclude closures from years ago)
CREATE OR REPLACE VIEW v_capacity_movers AS
WITH quarterly AS (
    SELECT
        e.mine_id,
        e.calendar_year,
        e.calendar_qtr,
        e.employee_hours,
        m.mine_name,
        m.operator_canonical,
        m.state,
        m.county,
        m.latitude,
        m.longitude
    FROM employment_quarterly e
    JOIN mines m USING (mine_id)
    WHERE e.employee_hours IS NOT NULL
      AND e.employee_hours > 0
),
ranked AS (
    SELECT
        *,
        LAG(employee_hours) OVER (
            PARTITION BY mine_id
            ORDER BY calendar_year, calendar_qtr
        ) AS prev_hours,
        ROW_NUMBER() OVER (
            PARTITION BY mine_id
            ORDER BY calendar_year DESC, calendar_qtr DESC
        ) AS rn
    FROM quarterly
),
latest AS (
    SELECT * FROM ranked WHERE rn = 1
)
SELECT
    l.mine_id,
    l.mine_name,
    l.operator_canonical AS operator,
    l.state,
    l.county,
    l.latitude,
    l.longitude,
    l.calendar_year,
    l.calendar_qtr,
    l.employee_hours AS latest_hours,
    l.prev_hours,
    CASE
        WHEN l.prev_hours IS NULL OR l.prev_hours = 0 THEN NULL
        ELSE ROUND(100.0 * (l.employee_hours - l.prev_hours) / l.prev_hours, 1)
    END AS yoy_pct_change,
    -- Recency floor: only surface if the latest reported quarter is within last ~3 years
    (l.calendar_year * 10 + l.calendar_qtr) AS latest_yq
FROM latest l
WHERE (l.calendar_year * 10 + l.calendar_qtr) >= (EXTRACT(YEAR FROM current_date) - 3) * 10
ORDER BY ABS(yoy_pct_change) DESC NULLS LAST;

-- Operator capacity league table
CREATE OR REPLACE VIEW v_operator_capacity AS
SELECT
    operator_canonical AS operator,
    COUNT(*) AS site_count,
    SUM(CASE WHEN current_status IN ('Active', 'Intermittent') THEN 1 ELSE 0 END) AS active_sites,
    ROUND(SUM(COALESCE(no_employees, 0)), 0) AS total_employees_reported
FROM mines
GROUP BY operator_canonical
ORDER BY active_sites DESC, site_count DESC;
