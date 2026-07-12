"""SQLite 기반 결과 아카이브."""

from __future__ import annotations
import sqlite3
import json
import os
from datetime import datetime
import pandas as pd

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'archive.db')


def _get_conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS allocations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            year_month TEXT NOT NULL,
            cluster TEXT NOT NULL,
            district TEXT NOT NULL,
            baseline_monthly_tons REAL,
            current_monthly_tons REAL,
            reduction_rate REAL,
            score REAL,
            shift REAL,
            k INTEGER,
            units INTEGER,
            total_mwh REAL,
            energy_mwh REAL,
            subsidy_krw REAL,
            cluster_baseline_energy_mwh REAL,
            cluster_actual_energy_mwh REAL,
            cluster_shortfall_mwh REAL,
            cluster_subsidy_krw REAL,
            saved_at TEXT,
            UNIQUE(year_month, district)
        )
    """)
    conn.commit()
    return conn


def save_results(year_month: str, cluster_results: list[dict]) -> None:
    """계산 결과를 DB에 저장. 같은 year_month+district면 덮어씀."""
    conn = _get_conn()
    now = datetime.now().isoformat()

    for cr in cluster_results:
        cluster = cr['cluster']
        dondt = cr['dondt']
        energy = cr['energy']
        district_alloc = cr['district_alloc']

        for district in dondt['districts']:
            da = district_alloc.get(district, {})
            conn.execute("""
                INSERT INTO allocations
                    (year_month, cluster, district,
                     baseline_monthly_tons, current_monthly_tons,
                     reduction_rate, score, shift, k, units,
                     total_mwh, energy_mwh, subsidy_krw,
                     cluster_baseline_energy_mwh, cluster_actual_energy_mwh,
                     cluster_shortfall_mwh, cluster_subsidy_krw, saved_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(year_month, district) DO UPDATE SET
                    cluster=excluded.cluster,
                    baseline_monthly_tons=excluded.baseline_monthly_tons,
                    current_monthly_tons=excluded.current_monthly_tons,
                    reduction_rate=excluded.reduction_rate,
                    score=excluded.score,
                    shift=excluded.shift,
                    k=excluded.k,
                    units=excluded.units,
                    total_mwh=excluded.total_mwh,
                    energy_mwh=excluded.energy_mwh,
                    subsidy_krw=excluded.subsidy_krw,
                    cluster_baseline_energy_mwh=excluded.cluster_baseline_energy_mwh,
                    cluster_actual_energy_mwh=excluded.cluster_actual_energy_mwh,
                    cluster_shortfall_mwh=excluded.cluster_shortfall_mwh,
                    cluster_subsidy_krw=excluded.cluster_subsidy_krw,
                    saved_at=excluded.saved_at
            """, (
                year_month, cluster, district,
                dondt['baseline_emissions'].get(district, 0),
                dondt['current_emissions'].get(district, 0),
                dondt['reduction_rates'].get(district, 0),
                dondt['scores'].get(district, 0),
                dondt['shift'],
                dondt['k'],
                da.get('units', 0),
                da.get('total_mwh', 0),
                da.get('energy_mwh', 0),
                da.get('subsidy_krw', 0),
                energy['baseline_energy_mwh'],
                energy['actual_energy_mwh'],
                energy['shortfall_mwh'],
                energy['subsidy_krw'],
                now,
            ))
    conn.commit()
    conn.close()


def load_all() -> pd.DataFrame:
    """전체 아카이브 로드."""
    conn = _get_conn()
    df = pd.read_sql("SELECT * FROM allocations ORDER BY year_month, cluster, district", conn)
    conn.close()
    return df


def load_month(year_month: str) -> pd.DataFrame:
    conn = _get_conn()
    df = pd.read_sql(
        "SELECT * FROM allocations WHERE year_month=? ORDER BY cluster, district",
        conn, params=(year_month,)
    )
    conn.close()
    return df


def list_months() -> list[str]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT DISTINCT year_month FROM allocations ORDER BY year_month DESC"
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]
