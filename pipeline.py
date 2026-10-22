"""Reproducible synthetic operations data, validated transformations and SQL metrics."""
from __future__ import annotations

import json
import random
import sqlite3
from pathlib import Path

import pandas as pd

REGIONS = ("West", "Central", "East")


def sample_data(seed: int = 42) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = random.Random(seed)
    assets = pd.DataFrame([{"asset_id": f"A{i:03d}", "region": REGIONS[i % 3],
                            "asset_type": ("Substation", "Feeder", "Sensor")[i % 3]} for i in range(1, 37)])
    rows = []
    for i in range(360):
        region = i % 3
        rows.append({"event_id": f"E{i:04d}", "asset_id": f"A{rng.randint(1,36):03d}",
                     "day": str(pd.Timestamp("2026-09-01") + pd.Timedelta(days=i % 30))[:10],
                     "duration_min": rng.randint(8, 95) + region * 6,
                     "cost_usd": rng.randint(50, 350) + region * 25,
                     "priority": "High" if rng.random() < .23 else "Routine"})
    # Inject deliberately observable source defects; do not silently repair them.
    rows += [dict(rows[i], cost_usd=2500 + i * 11) for i in range(0, 30)]
    rows += [{"event_id": f"ORPH{i}", "asset_id": "A999", "day": "2026-09-12",
              "duration_min": 40, "cost_usd": 780, "priority": "High"} for i in range(8)]
    rows += [dict(rows[i], event_id=f"MISS{i}", duration_min=None) for i in range(7)]
    rows += [dict(rows[i], event_id=f"NEG{i}", cost_usd=-100) for i in range(5)]
    rows += [dict(rows[i], event_id=f"DATE{i}", day="not-a-date") for i in range(3)]
    return pd.DataFrame(rows), assets


def clean(events: pd.DataFrame, assets: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    if assets["asset_id"].isna().any() or assets["asset_id"].duplicated().any():
        raise ValueError("Asset dimension must have unique, non-null keys")
    data = events.copy()
    data["source_row"] = range(len(data))
    data["reason"] = ""
    invalid_id = data["event_id"].isna() | data["event_id"].astype(str).str.strip().eq("")
    data.loc[invalid_id, "reason"] = "missing event id"
    # Stable first occurrence wins, explicitly documented; corrections need a separate contract.
    duplicate = data["event_id"].duplicated(keep="first") & data["reason"].eq("")
    data.loc[duplicate, "reason"] = "duplicate event id"
    durations = pd.to_numeric(data["duration_min"], errors="coerce")
    costs = pd.to_numeric(data["cost_usd"], errors="coerce")
    invalid_numeric = durations.isna() | costs.isna() | durations.lt(0) | costs.lt(0)
    data.loc[data["reason"].eq("") & invalid_numeric, "reason"] = "missing or negative measure"
    invalid_day = pd.to_datetime(data["day"], errors="coerce").isna()
    data.loc[data["reason"].eq("") & invalid_day, "reason"] = "invalid date"
    data.loc[data["reason"].eq("") & ~data["asset_id"].isin(assets["asset_id"]), "reason"] = "unmatched asset"
    good = data[data["reason"].eq("")].drop(columns="reason").copy()
    good["duration_min"] = pd.to_numeric(good["duration_min"])
    good["cost_usd"] = pd.to_numeric(good["cost_usd"])
    joined = good.merge(assets, on="asset_id", how="left", validate="many_to_one")
    rejected = data[~data["reason"].eq("")].copy()
    audit = {"source_rows": len(events), "accepted_rows": len(joined), "quarantined_rows": len(rejected),
             "reasons": {str(k): int(v) for k, v in rejected["reason"].value_counts().items()},
             "contract": "First occurrence wins; invalid values and unmatched keys are quarantined, not imputed."}
    assert len(joined) + len(rejected) == len(events)
    return joined, rejected, audit


SUMMARY_SQL = """SELECT region, COUNT(*) AS events, SUM(cost_usd) AS cost_usd,
 AVG(duration_min) AS avg_duration_min,
 SUM(CASE WHEN duration_min > 60 THEN 1 ELSE 0 END) AS over_sla
 FROM events GROUP BY region ORDER BY region"""


def analyze(events: pd.DataFrame, assets: pd.DataFrame) -> dict:
    accepted, rejected, audit = clean(events, assets)
    with sqlite3.connect(":memory:") as con:
        accepted.to_sql("events", con, index=False, if_exists="replace")
        summary = pd.read_sql_query(SUMMARY_SQL, con)
        daily = pd.read_sql_query("SELECT day, region, COUNT(*) AS events, SUM(cost_usd) AS cost_usd FROM events GROUP BY day, region ORDER BY day, region", con)
        totals = con.execute("SELECT COUNT(*), COALESCE(SUM(cost_usd),0) FROM events").fetchone()
    if totals[0] != len(accepted) or totals[1] != accepted["cost_usd"].sum():
        raise ValueError("SQL and source totals disagree")
    raw_cost = float(pd.to_numeric(events["cost_usd"], errors="coerce").sum())
    return {"dataset": "Synthetic utility operations; no customer or employer data", "seed": 42,
            "audit": audit, "raw_cost_usd": raw_cost, "clean_cost_usd": float(totals[1]),
            "cost_distortion_usd": raw_cost - float(totals[1]),
            "summary": summary.to_dict(orient="records"), "daily": daily.to_dict(orient="records"),
            "accepted": accepted.to_dict(orient="records"),
            "quarantine": json.loads(rejected.to_json(orient="records")),
            "source": json.loads(events.to_json(orient="records")),
            "assets": assets.to_dict(orient="records"), "sql": SUMMARY_SQL,
            "checks": {"row_conservation": True, "unique_event_ids": not accepted["event_id"].duplicated().any(),
                       "no_unmatched_assets": not accepted["region"].isna().any(), "sql_source_totals_agree": True}}


def export(root: Path | None = None) -> dict:
    root = root or Path(__file__).parent
    result = analyze(*sample_data())
    docs = root / "docs"
    docs.mkdir(exist_ok=True)
    (docs / "snapshot.json").write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
    template = (root / "observatory.html").read_text(encoding="utf-8")
    (docs / "index.html").write_text(template.replace("__SNAPSHOT__", json.dumps(result, allow_nan=False)), encoding="utf-8")
    return result


if __name__ == "__main__":
    result = export()
    print(json.dumps({"audit": result["audit"], "cost_distortion_usd": result["cost_distortion_usd"], "checks": result["checks"]}, indent=2))
