"""Compare the current freeze with the 27 Sep 2026 Etapa 3 export.

Read-only. Writes results/etapa4_audit.json and results/etapa4_gasoline_weeks.csv.
Does not change etapa3 outputs or notebooks.
"""

from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

_SRC = Path(__file__).resolve().parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from db_access import find_project_root
from etapa4_data import CURRENT_FREEZE, CURRENT_SHA256, SEP_EXPORT, SEP_SHA256, sqlite_file
from paths import results_dir

TABLES = [
    "abcr_traffic_index",
    "anp_distributor_weekly_diesel",
    "anp_distributor_weekly_gasoline",
    "anp_fuel_sales",
    "equity_daily",
    "export_changelog",
    "fuel_price_national_weekly",
    "ibge_indicators",
    "inflation_monthly",
    "pbr_quarterly_diesel_gasoline",
    "pbr_quarterly_sales",
    "petrobras_distributor_weekly_diesel",
    "petrobras_distributor_weekly_gasoline",
    "ppi_daily",
    "ppi_reference_table",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def connect(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def table_count(con: sqlite3.Connection, table: str) -> int:
    return int(con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])


def rtm_audit(con: sqlite3.Connection) -> dict:
    row = con.execute(
        """
        SELECT COUNT(*) AS n,
               COUNT(rtm_sales_revenue_rsmn) AS n_sales,
               COUNT(rtm_gross_profit_rsmn) AS n_gp,
               COUNT(rtm_gross_margin_pct) AS n_margin,
               COUNT(source_fin_doc) FILTER (
                   WHERE source_fin_doc IS NOT NULL AND source_fin_doc <> ''
               ) AS n_fin,
               MIN(year) AS min_year,
               MAX(year) AS max_year
        FROM pbr_quarterly_diesel_gasoline
        """
    ).fetchone()
    q419 = con.execute(
        """
        SELECT rtm_sales_revenue_rsmn, rtm_gross_profit_rsmn, rtm_gross_margin_pct
        FROM pbr_quarterly_diesel_gasoline WHERE quarter = '4Q19'
        """
    ).fetchone()
    derived = [
        dict(r)
        for r in con.execute(
            """
            SELECT quarter, rtm_sales_revenue_rsmn, rtm_gross_profit_rsmn,
                   substr(extraction_note, 1, 160) AS note
            FROM pbr_quarterly_diesel_gasoline
            WHERE extraction_note LIKE '%derived%'
            ORDER BY year, quarter_num
            """
        )
    ]
    neg = [
        dict(r)
        for r in con.execute(
            """
            SELECT quarter, rtm_sales_revenue_rsmn, rtm_gross_profit_rsmn,
                   rtm_gross_margin_pct
            FROM pbr_quarterly_diesel_gasoline
            WHERE rtm_gross_profit_rsmn < 0 OR rtm_sales_revenue_rsmn < 0
            ORDER BY year, quarter_num
            """
        )
    ]
    vol = con.execute(
        """
        SELECT COUNT(diesel_mbpd) AS n_die, COUNT(gasoline_mbpd) AS n_gas,
               COUNT(diesel_revenue_rsmn) AS n_die_rev,
               COUNT(gasoline_revenue_rsmn) AS n_gas_rev
        FROM pbr_quarterly_diesel_gasoline
        """
    ).fetchone()
    since_2022 = con.execute(
        """
        SELECT COUNT(*) AS n, COUNT(rtm_sales_revenue_rsmn) AS n_rtm
        FROM pbr_quarterly_diesel_gasoline WHERE year >= 2022
        """
    ).fetchone()
    return {
        "n": row["n"],
        "n_sales": row["n_sales"],
        "n_gp": row["n_gp"],
        "n_margin": row["n_margin"],
        "n_fin": row["n_fin"],
        "min_year": row["min_year"],
        "max_year": row["max_year"],
        "q419": {
            "sales": q419[0] if q419 else None,
            "gp": q419[1] if q419 else None,
            "margin": q419[2] if q419 else None,
        },
        "derived_quarters": derived,
        "negative_gp_or_sales": neg,
        "diesel_mbpd_n": vol["n_die"],
        "gasoline_mbpd_n": vol["n_gas"],
        "diesel_revenue_n": vol["n_die_rev"],
        "gasoline_revenue_n": vol["n_gas_rev"],
        "since_2022_n": since_2022["n"],
        "since_2022_rtm": since_2022["n_rtm"],
    }


def gasoline_diffs(cur: sqlite3.Connection, sep: sqlite3.Connection) -> list[dict]:
    cur_rows = {
        r["week_start"]: dict(r)
        for r in cur.execute(
            "SELECT week_start, week_end, avg_price_rs_l, source_record_count, computed_at "
            "FROM petrobras_distributor_weekly_gasoline"
        )
    }
    sep_rows = {
        r["week_start"]: dict(r)
        for r in sep.execute(
            "SELECT week_start, week_end, avg_price_rs_l, source_record_count, computed_at "
            "FROM petrobras_distributor_weekly_gasoline"
        )
    }
    keys = sorted(set(cur_rows) | set(sep_rows))
    out = []
    for k in keys:
        a, b = cur_rows.get(k), sep_rows.get(k)
        if a is None or b is None:
            out.append(
                {
                    "week_start": k,
                    "in_current": a is not None,
                    "in_sep": b is not None,
                    "cur_price": None if a is None else a["avg_price_rs_l"],
                    "sep_price": None if b is None else b["avg_price_rs_l"],
                    "delta": None,
                    "cur_n": None if a is None else a["source_record_count"],
                    "sep_n": None if b is None else b["source_record_count"],
                }
            )
            continue
        delta = float(a["avg_price_rs_l"]) - float(b["avg_price_rs_l"])
        n_delta = int(a["source_record_count"]) - int(b["source_record_count"])
        if abs(delta) > 1e-15 or n_delta != 0 or a["week_end"] != b["week_end"]:
            out.append(
                {
                    "week_start": k,
                    "week_end": a["week_end"],
                    "in_current": True,
                    "in_sep": True,
                    "cur_price": a["avg_price_rs_l"],
                    "sep_price": b["avg_price_rs_l"],
                    "delta": delta,
                    "cur_n": a["source_record_count"],
                    "sep_n": b["source_record_count"],
                    "n_delta": n_delta,
                }
            )
    return out


def rtm_2022_match(cur: sqlite3.Connection, sep: sqlite3.Connection) -> dict:
    cols = (
        "quarter, diesel_mbpd, gasoline_mbpd, diesel_revenue_rsmn, "
        "gasoline_revenue_rsmn, rtm_sales_revenue_rsmn, rtm_gross_profit_rsmn, "
        "rtm_gross_margin_pct"
    )
    a = {r["quarter"]: dict(r) for r in cur.execute(f"SELECT {cols} FROM pbr_quarterly_diesel_gasoline WHERE year>=2022")}
    b = {r["quarter"]: dict(r) for r in sep.execute(f"SELECT {cols} FROM pbr_quarterly_diesel_gasoline WHERE year>=2022")}
    mism = []
    for q in sorted(set(a) | set(b)):
        if a.get(q) != b.get(q):
            mism.append(q)
    return {"n_current": len(a), "n_sep": len(b), "mismatches": mism}


def changelog(con: sqlite3.Connection) -> list[dict]:
    return [
        dict(r)
        for r in con.execute(
            "SELECT id, changed_at, table_name, scope, substr(cause,1,240) AS cause "
            "FROM export_changelog ORDER BY id"
        )
    ]


def main() -> None:
    root = find_project_root()
    cur_path = sqlite_file(CURRENT_FREEZE, root)
    sep_path = sqlite_file(SEP_EXPORT, root)
    cur_sha = sha256_file(cur_path)
    sep_sha = sha256_file(sep_path)
    cur = connect(cur_path)
    sep = connect(sep_path)

    counts = {
        t: {"current": table_count(cur, t), "sep": table_count(sep, t)} for t in TABLES
    }
    gas = gasoline_diffs(cur, sep)
    report = {
        "completed_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "current": {
            "file": CURRENT_FREEZE,
            "bytes": cur_path.stat().st_size,
            "sha256": cur_sha,
            "sha256_expected": CURRENT_SHA256,
            "sha_ok": cur_sha == CURRENT_SHA256,
        },
        "sep_export": {
            "file": SEP_EXPORT,
            "bytes": sep_path.stat().st_size,
            "sha256": sep_sha,
            "sha256_expected": SEP_SHA256,
            "sha_ok": sep_sha == SEP_SHA256,
        },
        "integrity": {
            "current": cur.execute("PRAGMA integrity_check").fetchone()[0],
            "sep": sep.execute("PRAGMA integrity_check").fetchone()[0],
        },
        "row_counts": counts,
        "rtm_current": rtm_audit(cur),
        "rtm_sep": rtm_audit(sep),
        "rtm_2022_match": rtm_2022_match(cur, sep),
        "gasoline_week_diffs_n": len(gas),
        "gasoline_week_diffs": gas,
        "changelog_current": changelog(cur),
        "changelog_sep_n": table_count(sep, "export_changelog"),
        "notes": [
            "Etapa 3 metrics remain results/etapa3_metrics.json against the September export.",
            "Do not treat current-freeze Petrobras gasoline naive RMSE as a model change until the 22 weeks are sourced.",
        ],
    }
    out_dir = results_dir(root)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "etapa4_audit.json"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    csv_path = out_dir / "etapa4_gasoline_weeks.csv"
    if gas:
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(gas[0].keys()))
            writer.writeheader()
            writer.writerows(gas)
    cur.close()
    sep.close()
    print(f"wrote {json_path}")
    print(f"sha current {cur_sha} ok={cur_sha == CURRENT_SHA256}")
    print(f"sha sep {sep_sha} ok={sep_sha == SEP_SHA256}")
    print(f"RT&M current {report['rtm_current']['n_sales']}/{report['rtm_current']['n']}")
    print(f"RT&M sep {report['rtm_sep']['n_sales']}/{report['rtm_sep']['n']}")
    print(f"2022+ mismatches {report['rtm_2022_match']['mismatches']}")
    print(f"gasoline week diffs {len(gas)}")
    if gas:
        deltas = [abs(r["delta"]) for r in gas if r.get("delta") is not None]
        print(f"max abs gasoline delta {max(deltas) if deltas else None}")


if __name__ == "__main__":
    main()
