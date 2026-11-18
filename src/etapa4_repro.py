"""Reproduce Etapa 3 naive on the September export and the current freeze.

Writes results/etapa4_repro_naive.json. Does not overwrite etapa3_metrics.json.
"""

from __future__ import annotations

import json
import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path

_SRC = Path(__file__).resolve().parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import etapa3_models as e3
from db_access import find_project_root
from etapa4_data import (
    CURRENT_FREEZE,
    CURRENT_SHA256,
    SEP_EXPORT,
    SEP_SHA256,
    load_frames_at,
    sqlite_file,
)
from paths import metrics_path, results_dir


def _key(row: dict) -> tuple:
    return (row["vector"], row["target"], row["model"], row["horizon"])


def compare_naive(ref_rows: list[dict], new_rows: list[dict]) -> list[dict]:
    ref = {_key(r): r for r in ref_rows if r.get("model") == "naive"}
    new = {_key(r): r for r in new_rows if r.get("model") == "naive"}
    out = []
    for k in sorted(set(ref) | set(new)):
        a, b = ref.get(k), new.get(k)
        item = {
            "vector": k[0],
            "target": k[1],
            "horizon": k[3],
            "ref_RMSE": None if a is None else a.get("RMSE"),
            "new_RMSE": None if b is None else b.get("RMSE"),
        }
        if a is not None and b is not None:
            item["rmse_delta"] = float(b["RMSE"]) - float(a["RMSE"])
            item["match"] = abs(float(b["RMSE"]) - float(a["RMSE"])) < 1e-12
        else:
            item["match"] = False
        out.append(item)
    return out


def main() -> None:
    root = find_project_root()
    ref_payload = json.loads(metrics_path(root).read_text(encoding="utf-8"))
    ref_rows = ref_payload.get("rows", [])

    sep_path = sqlite_file(SEP_EXPORT, root)
    cur_path = sqlite_file(CURRENT_FREEZE, root)
    print(f"naive on {sep_path.name}")
    sep_frames = load_frames_at(sep_path, root)
    sep_rows, _ = e3.run_naive(sep_frames)
    print(f"naive on {cur_path.name}")
    cur_frames = load_frames_at(cur_path, root)
    cur_rows, _ = e3.run_naive(cur_frames)

    vs_json = compare_naive(ref_rows, sep_rows)
    vs_cur = compare_naive(sep_rows, cur_rows)
    report = {
        "completed_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "etapa3_metrics": str(metrics_path(root).relative_to(root)).replace("\\", "/"),
        "sep_export": {"file": SEP_EXPORT, "sha256_expected": SEP_SHA256, "sha256_actual": hashlib.sha256(sep_path.read_bytes()).hexdigest()},
        "current_freeze": {"file": CURRENT_FREEZE, "sha256_expected": CURRENT_SHA256, "sha256_actual": hashlib.sha256(cur_path.read_bytes()).hexdigest()},
        "naive_sep_vs_etapa3_json": vs_json,
        "naive_current_vs_sep": vs_cur,
        "all_sep_match_json": all(r.get("match") for r in vs_json),
        "all_current_match_sep": all(r.get("match") for r in vs_cur),
        "changed_vs_sep": [r for r in vs_cur if not r.get("match")],
        "note": "SARIMAX/Prophet/TimesFM stay on the Mac JSON. This run is naive only.",
    }
    out = results_dir(root) / "etapa4_repro_naive.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"wrote {out}")
    print("sep vs etapa3 json match", report["all_sep_match_json"])
    print("current vs sep match", report["all_current_match_sep"])
    for r in report["changed_vs_sep"]:
        print(" changed", r)


if __name__ == "__main__":
    main()
