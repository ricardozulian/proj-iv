"""Per-target experiment matrix for Etapa 4.

Reads results/etapa4_*.json. Writes results/etapa4_matrix.json and .md.
Does not overwrite etapa3_metrics.json.
"""

from __future__ import annotations

import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

_SRC = Path(__file__).resolve().parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from db_access import find_project_root
from etapa4_data import CURRENT_FREEZE, CURRENT_SHA256, SEP_EXPORT, SEP_SHA256
from paths import results_dir

THRESH_PROMOTE = 0.05
THRESH_TIE = 0.02

DECISION_H = {
    ("mercado", "PETR4"): "21d",
    ("mercado", "PETR4 dlog"): "21d",
    ("mercado", "RV 5 pregões"): "21d",
    ("mercado", "RV 21 pregões"): "21d",
    ("preço", "ANP gasolina"): "8w",
    ("preço", "ANP diesel"): "8w",
    ("preço", "Petrobras gasolina"): "8w",
    ("preço", "Petrobras diesel"): "8w",
    ("preço", "ANP gasolina Δ"): "8w",
    ("preço", "ANP diesel Δ"): "8w",
    ("atividade", "tráfego pesado"): "3m",
    ("atividade", "tráfego leve"): "3m",
    ("atividade", "vendas diesel ANP"): "3m",
    ("atividade", "vendas gasolina ANP"): "3m",
    ("atividade", "indústria"): "3m",
    ("atividade", "varejo"): "3m",
    ("atividade", "desemprego"): "3m",
    ("inflação", "IPCA mom"): "3m",
    ("inflação", "IPCA-15 mom"): "3m",
    ("inflação", "IGP-M mom"): "3m",
    ("companhia", "diesel mbpd"): "4q",
    ("companhia", "gasolina mbpd"): "4q",
    ("companhia", "receita RT&M"): "4q",
    ("companhia", "lucro bruto RT&M"): "4q",
    ("companhia", "margem RT&M"): "4q",
    ("companhia", "margem derivada"): "4q",
}

PRIMARY_EXP = {
    ("mercado", "PETR4"): "prod_contrib",
    ("mercado", "PETR4 dlog"): "petr4_vol",
    ("mercado", "RV 5 pregões"): "petr4_vol",
    ("mercado", "RV 21 pregões"): "petr4_vol",
    ("preço", "ANP gasolina"): "prod_contrib",
    ("preço", "ANP diesel"): "prod_contrib",
    ("preço", "Petrobras gasolina"): "prod_contrib",
    ("preço", "Petrobras diesel"): "prod_contrib",
    ("preço", "ANP gasolina Δ"): "price_transmission",
    ("preço", "ANP diesel Δ"): "price_transmission",
    ("atividade", "tráfego pesado"): "demand",
    ("atividade", "tráfego leve"): "demand",
    ("atividade", "vendas diesel ANP"): "demand",
    ("atividade", "vendas gasolina ANP"): "demand",
    ("atividade", "indústria"): "demand",
    ("atividade", "varejo"): "demand",
    ("atividade", "desemprego"): "prod_contrib",
    ("inflação", "IPCA mom"): "inflation",
    ("inflação", "IPCA-15 mom"): "inflation",
    ("inflação", "IGP-M mom"): "inflation",
    ("companhia", "diesel mbpd"): "company_matched",
    ("companhia", "gasolina mbpd"): "company_matched",
    ("companhia", "receita RT&M"): "company_matched",
    ("companhia", "lucro bruto RT&M"): "company_matched",
    ("companhia", "margem RT&M"): "company_matched",
    ("companhia", "margem derivada"): "company_matched",
}

DESCRIPTIVE_VECTORS = {"companhia"}
SHORT_H = {"21d": "5d", "8w": "4w", "3m": "1m"}


def _load(results: Path, name: str) -> dict:
    path = results / name
    return json.loads(path.read_text(encoding="utf-8"))


def family(group: str) -> str:
    g = group.lower()
    if g in {"dummy", "persistence", "uncorrected"} or g.startswith("hist_persistence"):
        return "dummy"
    if g.startswith("hist_seasonal"):
        return "seasonal"
    if g == "y_only":
        return "history"
    if g == "zero_change":
        return "zero"
    if g in {"y_seasonal", "seasonal_s12"}:
        return "seasonal"
    if "gap" in g:
        return "ppi_gap"
    if g.startswith("corr_"):
        return "ppi_x_vol"
    if "anp" in g or g in {"y_list", "y_dqty"}:
        return "context"
    if any(
        tok in g
        for tok in (
            "prod",
            "exp",
            "fuel",
            "dprod",
            "trail",
            "pbr",
            "ind",
            "asym",
            "die_l",
            "gas_l",
            "y_die",
            "y_gas",
        )
    ):
        return "ppi_x_vol"
    if "seasonal" in g:
        return "seasonal"
    return "other"


def _rel(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or not b:
        return None
    return (b - a) / b


def _finite(x) -> bool:
    return x is not None and x == x and not (isinstance(x, float) and math.isinf(x))


def row(
    vector: str,
    target: str,
    horizon: str,
    experiment: str,
    group: str,
    s: dict,
    *,
    descriptive: bool = False,
    rmse_key: str = "median_RMSE",
    dummy_key: str = "persistence_median_RMSE",
    rel_key: str = "rel_RMSE_vs_pers",
    mae_key: str = "median_MAE",
    dummy_mae_key: str = "persistence_median_MAE",
    win_key: str = "blocks_better_RMSE",
    n_key: str = "n_blocks",
) -> dict | None:
    rmse = s.get(rmse_key, s.get("RMSE"))
    dummy = s.get(dummy_key, s.get("dummy_RMSE"))
    if not _finite(rmse):
        return None
    rel = s.get(rel_key, s.get("rel_RMSE_vs_dummy"))
    if rel is None:
        rel = _rel(rmse, dummy)
    n = s.get(n_key, s.get("n"))
    wins = s.get(win_key)
    return {
        "vector": vector,
        "target": target,
        "horizon": horizon,
        "experiment": experiment,
        "group": group,
        "family": family(group),
        "RMSE": rmse,
        "dummy_RMSE": dummy,
        "rel_vs_dummy": rel,
        "MAE": s.get(mae_key, s.get("MAE")),
        "dummy_MAE": s.get(dummy_mae_key, s.get("dummy_MAE")),
        "blocks_better": wins,
        "n_blocks": n,
        "promote_vs_dummy": s.get("promote_ge_5pct"),
        "descriptive": descriptive,
    }


def from_summary(
    node: dict,
    vector: str,
    target: str,
    experiment: str,
    horizons: tuple[str, ...],
    descriptive: bool = False,
) -> list[dict]:
    out = []
    summary = node.get("summary") or {}
    for g, hs in summary.items():
        for h in horizons:
            s = (hs or {}).get(h) or {}
            r = row(vector, target, h, experiment, g, s, descriptive=descriptive or target.startswith("vendas "))
            if r:
                ev = node.get("rows") or {}
                r["incremental"] = ((ev.get("comparisons") or {}).get(g) or {}).get(h)
                r["complexity"] = (ev.get("feature_counts") or {}).get(g, 2)
                r["control_group"] = (r["incremental"] or {}).get("control_group")
                out.append(r)
    extra = {
        "zero_change": "zero_change",
        "seasonal_s12": "seasonal_s12",
    }
    for key, gname in extra.items():
        pack = node.get(key) or {}
        for h in horizons:
            s = pack.get(h) or {}
            r = row(vector, target, h, experiment, gname, s, descriptive=descriptive)
            if r:
                out.append(r)
    return out


def collect(results: Path) -> list[dict]:
    rows: list[dict] = []
    contrib = _load(results, "etapa4_prod_contrib.json")
    m = contrib["vectors"]["mercado_PETR4"]
    rows += from_summary(m, "mercado", "PETR4", "prod_contrib", ("5d", "21d"))
    for lab, t in contrib["vectors"]["preco"]["targets"].items():
        rows += from_summary(t, "preço", lab, "prod_contrib", ("4w", "8w"))
    for lab, t in contrib["vectors"]["atividade"]["targets"].items():
        rows += from_summary(t, "atividade", lab, "prod_contrib", ("1m", "3m"))
    for lab, t in contrib["vectors"]["companhia"]["targets"].items():
        rows += from_summary(t, "companhia", lab, "prod_contrib", ("1q",), descriptive=True)

    pt = _load(results, "etapa4_price_transmission.json")
    for lab, t in pt["targets"].items():
        rows += from_summary(t, "preço", lab, "price_transmission", ("4w", "8w"))

    dm = _load(results, "etapa4_demand.json")
    for lab, t in dm["targets"].items():
        rows += from_summary(t, "atividade", lab, "demand", ("1m", "3m"))

    vol = _load(results, "etapa4_petr4_vol.json")
    for lab, t in vol["targets"].items():
        rows += from_summary(t, "mercado", lab, "petr4_vol", ("5d", "21d"))

    inf = _load(results, "etapa4_inflation.json")
    for lab, t in inf["targets"].items():
        rows += from_summary(t, "inflação", lab, "inflation", ("1m", "3m"))

    ind = _load(results, "etapa4_independents.json")
    for lab, t in ind["daily"]["targets"].items():
        rows += from_summary(t, "mercado", lab, "independents", ("5d", "21d"))
    for lab, t in ind["weekly"]["targets"].items():
        rows += from_summary(t, "preço", lab, "independents", ("4w", "8w"))

    co = _load(results, "etapa4_company.json")
    for lab, t in co["matched_history"]["targets"].items():
        for g, node in t.items():
            s = node.get("all_4q") or {}
            r = row("companhia", lab, "4q", "company_matched", g, s, descriptive=True, rmse_key="RMSE")
            if r:
                rows.append(r)
    for g, node in co["matched_history"]["derived_margin"].items():
        s = node.get("all_4q") or {}
        r = row(
            "companhia",
            "margem derivada",
            "4q",
            "company_matched",
            g,
            s,
            descriptive=True,
            rmse_key="RMSE",
        )
        if r:
            rows.append(r)
    for lab, t in co["residual_correction"]["targets"].items():
        u = (t.get("uncorrected") or {}).get("eval_1Q24_1Q26") or {}
        r = row("companhia", lab, "1T24-1T26", "company_resid", "uncorrected", u, descriptive=True, rmse_key="RMSE")
        if r:
            rows.append(r)
        u25 = (t.get("uncorrected") or {}).get("eval_1Q24_4Q25") or {}
        r = row("companhia", lab, "1T24-4T25", "company_resid", "uncorrected", u25, descriptive=True, rmse_key="RMSE")
        if r:
            rows.append(r)
        for xlab, node in (t.get("corrected") or {}).items():
            s = node.get("eval_1Q24_1Q26") or {}
            r = row(
                "companhia",
                lab,
                "1T24-1T26",
                "company_resid",
                f"corr_{xlab}",
                s,
                descriptive=True,
                rmse_key="RMSE",
            )
            if r:
                rows.append(r)
            s25 = node.get("eval_1Q24_4Q25") or {}
            r = row(
                "companhia",
                lab,
                "1T24-4T25",
                "company_resid",
                f"corr_{xlab}",
                s25,
                descriptive=True,
                rmse_key="RMSE",
            )
            if r:
                rows.append(r)

    fin = _load(results, "etapa4_finance_baseline.json")
    for lab, t in fin["targets"].items():
        w = t.get("winner") or {}
        ev = t.get("eval_1Q22_1Q26") or {}
        s = {
            "RMSE": ev.get("RMSE"),
            "dummy_RMSE": ev.get("RMSE"),
            "rel_RMSE_vs_dummy": 0.0,
            "MAE": ev.get("MAE"),
            "n": ev.get("n"),
        }
        r = row(
            "companhia",
            lab,
            "1T22-1T26",
            "finance_baseline",
            f"hist_{w.get('method')}",
            s,
            descriptive=True,
            rmse_key="RMSE",
        )
        if r:
            rows.append(r)
        leg = t.get("legacy_2Q26") or {}
        s2 = {
            "RMSE": leg.get("RMSE"),
            "dummy_RMSE": leg.get("RMSE"),
            "n": leg.get("n"),
        }
        r = row(
            "companhia",
            lab,
            "2T26",
            "finance_baseline",
            f"hist_{w.get('method')}",
            s2,
            descriptive=True,
            rmse_key="RMSE",
        )
        if r:
            rows.append(r)
    return rows


def inject_dummy(cands: list[dict]) -> None:
    seen: set[tuple] = set()
    extras: list[dict] = []
    for r in cands:
        key = (r["vector"], r["target"], r["horizon"], r["experiment"])
        if key in seen:
            continue
        if r["group"] == "dummy":
            seen.add(key)
            continue
        d_rmse = r.get("dummy_RMSE")
        if not _finite(d_rmse):
            continue
        seen.add(key)
        extras.append(
            {
                "vector": r["vector"],
                "target": r["target"],
                "horizon": r["horizon"],
                "experiment": r["experiment"],
                "group": "dummy",
                "family": "dummy",
                "RMSE": d_rmse,
                "dummy_RMSE": d_rmse,
                "rel_vs_dummy": 0.0,
                "MAE": r.get("dummy_MAE"),
                "dummy_MAE": r.get("dummy_MAE"),
                "blocks_better": None,
                "n_blocks": r.get("n_blocks"),
                "promote_vs_dummy": False,
                "descriptive": r["descriptive"],
            }
        )
    cands.extend(extras)


def annotate_vs_y(cands: list[dict]) -> None:
    by: dict[tuple, list] = {}
    for r in cands:
        by.setdefault((r["vector"], r["target"], r["horizon"], r["experiment"]), []).append(r)
    y_any: dict[tuple, float] = {}
    for r in cands:
        if r["group"] == "y_only":
            y_any.setdefault((r["vector"], r["target"], r["horizon"], r["experiment"]), r["RMSE"])
    for r in cands:
        yo = None
        for sib in by.get((r["vector"], r["target"], r["horizon"], r["experiment"]), []):
            if sib["group"] == "y_only":
                yo = sib["RMSE"]
                break
        if yo is None:
            yo = y_any.get((r["vector"], r["target"], r["horizon"], r["experiment"]))
        r["y_only_RMSE"] = yo
        r["rel_vs_y_only"] = _rel(r["RMSE"], yo) if yo else None


def _min_rmse(pool: list[dict]) -> dict | None:
    ok = [p for p in pool if _finite(p.get("RMSE"))]
    if not ok:
        return None
    minimum = min(p["RMSE"] for p in ok)
    tied = [p for p in ok if p["RMSE"] <= minimum * (1 + THRESH_TIE)]
    return min(tied, key=lambda p: (p.get("complexity", 0 if p["family"] in {"dummy", "zero"} else 2), p["RMSE"], p["group"]))


def contributes(best: dict | None, control: dict | None, y_only: dict | None, descriptive: bool) -> str:
    if descriptive:
        return "descritivo"
    if best is None:
        return "não"
    comparison = best.get("incremental") or {}
    required = (comparison.get("rel_RMSE_vs_pers"), comparison.get("median_MAE"), comparison.get("persistence_median_MAE"))
    if not all(_finite(value) for value in required):
        return "não"
    n = comparison.get("n_blocks", 0)
    wins = comparison.get("blocks_better_RMSE", 0)
    return "sim" if required[0] >= THRESH_PROMOTE and n > 0 and wins > n / 2 and required[1] <= required[2] else "não"


def gap_contributes(
    best_gap: dict | None,
    control: dict | None,
    y_only: dict | None,
    best_vol: dict | None,
    descriptive: bool,
) -> str:
    flag = contributes(best_gap, control, y_only, descriptive)
    if flag != "sim":
        return flag
    if best_vol is None:
        return "sim"
    vs_vol = _rel(best_gap["RMSE"], best_vol["RMSE"])
    if vs_vol is None or vs_vol < THRESH_PROMOTE:
        return "não"
    return "sim"


def formulate(
    control: dict | None,
    y_only: dict | None,
    best_vol: dict | None,
    best_gap: dict | None,
    best_ctx: dict | None,
    descriptive: bool,
) -> dict:
    vol_flag = contributes(best_vol, control, y_only, descriptive)
    gap_flag = gap_contributes(best_gap, control, y_only, best_vol, descriptive)
    ctx_flag = contributes(best_ctx, control, y_only, descriptive)
    ctrl_name = control["group"] if control else "dummy"
    if descriptive:
        form = ctrl_name
        if best_vol and control:
            vs = _rel(best_vol["RMSE"], control["RMSE"])
            if vs is not None and vs >= THRESH_PROMOTE:
                form = best_vol["group"]
        return {
            "ppi_x_vol": vol_flag,
            "ppi_relativo": gap_flag,
            "contexto": "descritivo",
            "formulacao": form,
            "controle": ctrl_name,
            "melhor_ppi_x_vol": (best_vol or {}).get("group"),
            "melhor_ppi_gap": (best_gap or {}).get("group"),
            "melhor_contexto": (best_ctx or {}).get("group"),
        }
    pick = ctrl_name
    if vol_flag == "sim":
        pick = best_vol["group"]
    elif gap_flag == "sim":
        pick = best_gap["group"]
    elif ctx_flag == "sim":
        pick = best_ctx["group"]
    return {
        "ppi_x_vol": vol_flag,
        "ppi_relativo": gap_flag,
        "contexto": ctx_flag,
        "formulacao": pick,
        "controle": ctrl_name,
        "melhor_ppi_x_vol": (best_vol or {}).get("group"),
        "melhor_ppi_gap": (best_gap or {}).get("group"),
        "melhor_contexto": (best_ctx or {}).get("group"),
    }


def _fmt(x) -> str:
    if x is None or not _finite(x):
        return "—"
    if abs(x) >= 100:
        return f"{x:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")
    if abs(x) >= 1:
        return f"{x:.3f}".replace(".", ",")
    return f"{x:.4f}".replace(".", ",")


def leitura(
    alvo: str,
    h: str,
    rec: dict,
    control: dict | None,
    y_only: dict | None,
    best_vol: dict | None,
    best_gap: dict | None,
    best_ctx: dict | None,
) -> str:
    ctrl = control["group"] if control else "dummy"
    c_rmse = _fmt(control["RMSE"] if control else None)
    y_name = y_only["group"] if y_only else ctrl
    y_rmse = _fmt(y_only["RMSE"] if y_only else None)
    if rec["ppi_x_vol"] == "sim" and best_vol:
        comparison = best_vol["incremental"]
        return (
            f"{alvo} (bloco {h}): `{best_vol['group']}` atende ao critério exploratório "
            f"contra `{best_vol['control_group']}`: RMSE {_fmt(best_vol['RMSE'])} vs "
            f"{_fmt(comparison['persistence_median_RMSE'])}; vitórias "
            f"{comparison['blocks_better_RMSE']}/{comparison['n_blocks']}. Não é evidência ex ante."
        )
    if rec["ppi_relativo"] == "sim" and best_gap:
        return (
            f"{alvo} ({h}): o gap independentes−Petrobras contribui com `{best_gap['group']}` "
            f"(RMSE {_fmt(best_gap['RMSE'])} vs {y_rmse} de `{y_name}`); "
            f"a exposição Petrobras × volume não passa da história do alvo."
        )
    if rec.get("contexto") == "sim" and best_ctx:
        return (
            f"{alvo} ({h}): PPI × volume não contribui; o contexto `{best_ctx['group']}` "
            f"passa da história do alvo (RMSE {_fmt(best_ctx['RMSE'])} vs {y_rmse} de `{y_name}`)."
        )
    if rec["ppi_x_vol"] == "descritivo":
        extra = ""
        if best_vol and y_only:
            extra = (
                f" Melhor exposição `{best_vol['group']}` RMSE {_fmt(best_vol['RMSE'])} "
                f"vs `y_only` {y_rmse}."
            )
        return f"{alvo} ({h}): evidência descritiva (amostra trimestral). Controle `{ctrl}` RMSE {c_rmse}.{extra}"
    return (
        f"{alvo} ({h}): PPI × volume não contribui além do controle `{ctrl}` "
        f"(RMSE {c_rmse}). Formulação: `{rec['formulacao']}`."
    )


def _survive_label(rec: dict) -> str:
    if rec["ppi_x_vol"] == "descritivo":
        return "descritivo"
    if rec["ppi_x_vol"] == "sim":
        return "critério exploratório atendido (PPI × volume)"
    if rec["ppi_relativo"] == "sim":
        return "critério exploratório atendido (gap independentes)"
    if rec.get("contexto") == "sim":
        return "critério exploratório atendido (contexto)"
    return "sem contribuição incremental demonstrada"


def recommend_pool(
    pool: list[dict],
    pool_all_exp: list[dict],
    vector: str,
    target: str,
    h: str,
    descriptive: bool,
) -> dict | None:
    if not pool:
        return None
    y_only = _min_rmse([r for r in pool if r["family"] == "history"])
    dummy = _min_rmse([r for r in pool if r["family"] == "dummy"])
    seasonal = _min_rmse([r for r in pool if r["family"] == "seasonal"])
    zero = _min_rmse([r for r in pool if r["family"] == "zero"])
    controls = [c for c in (dummy, y_only, seasonal, zero) if c]
    control = _min_rmse(controls)
    best_vol = _min_rmse([r for r in pool if r["family"] == "ppi_x_vol"])
    best_gap = _min_rmse([r for r in pool if r["family"] == "ppi_gap"])
    best_ctx = _min_rmse([r for r in pool if r["family"] == "context"])
    if best_vol and best_vol.get("control_group"):
        control = next((r for r in pool if r["group"] == best_vol["control_group"]), control)
    rec = formulate(control, y_only, best_vol, best_gap, best_ctx, descriptive)
    rec.update(
        {
            "vector": vector,
            "target": target,
            "horizon": h,
            "experiment": pool[0]["experiment"],
            "descriptive": descriptive,
            "RMSE_controle": control["RMSE"] if control else None,
            "RMSE_y_only": y_only["RMSE"] if y_only else None,
            "RMSE_ppi_x_vol": best_vol["RMSE"] if best_vol else None,
            "RMSE_ppi_gap": best_gap["RMSE"] if best_gap else None,
            "RMSE_contexto": best_ctx["RMSE"] if best_ctx else None,
            "ganho_vol_vs_y_only": _rel(best_vol["RMSE"], y_only["RMSE"]) if best_vol and y_only else None,
            "ganho_vol_vs_dummy": _rel(best_vol["RMSE"], dummy["RMSE"]) if best_vol and dummy else None,
            "ganho_gap_vs_y_only": _rel(best_gap["RMSE"], y_only["RMSE"]) if best_gap and y_only else None,
            "ganho_ctx_vs_y_only": _rel(best_ctx["RMSE"], y_only["RMSE"]) if best_ctx and y_only else None,
            "n_blocos": (best_vol or control or pool[0]).get("n_blocks"),
            "menor_erro_observado": min(pool, key=lambda r: r["RMSE"])["group"],
            "comparacao_incremental_exposicao": (best_vol or {}).get("incremental"),
            "controle_incremental_exposicao": (best_vol or {}).get("control_group"),
            "comparacao_incremental_contexto": (best_ctx or {}).get("incremental"),
            "evidencia": "seleção exploratória nos mesmos blocos; não é confirmação independente",
        }
    )
    rec["sobrevive_validacao"] = _survive_label(rec)
    rec["leitura"] = leitura(target, h, rec, control, y_only, best_vol, best_gap, best_ctx)
    rec["nota_curto"] = None
    short = SHORT_H.get(h)
    if short and not descriptive:
        pool_s = [r for r in pool_all_exp if r["horizon"] == short]
        if pool_s:
            y_s = _min_rmse([r for r in pool_s if r["family"] == "history"])
            c_s = _min_rmse([r for r in pool_s if r["family"] in {"dummy", "history", "seasonal", "zero"}])
            v_s = _min_rmse([r for r in pool_s if r["family"] == "ppi_x_vol"])
            g_s = _min_rmse([r for r in pool_s if r["family"] == "ppi_gap"])
            x_s = _min_rmse([r for r in pool_s if r["family"] == "context"])
            flag_s = contributes(v_s, c_s, y_s, False)
            gap_s = gap_contributes(g_s, c_s, y_s, v_s, False)
            ctx_s = contributes(x_s, c_s, y_s, False)
            if (
                flag_s != rec["ppi_x_vol"]
                or gap_s != rec["ppi_relativo"]
                or ctx_s != rec.get("contexto")
            ):
                rec["nota_curto"] = (
                    f"No bloco {short} ({pool[0]['experiment']}), "
                    f"PPI×vol={flag_s}, gap={gap_s}, contexto={ctx_s} "
                    f"(melhor vol `{v_s['group'] if v_s else '—'}`)."
                )
    return rec


def merge_recs(per_exp: list[dict], primary_name: str | None) -> dict:
    primary = next((r for r in per_exp if r["experiment"] == primary_name), per_exp[0])
    vol_yes = [r for r in per_exp if r["ppi_x_vol"] == "sim"]
    gap_yes = [r for r in per_exp if r["ppi_relativo"] == "sim"]
    ctx_yes = [r for r in per_exp if r.get("contexto") == "sim"]
    if vol_yes:
        chosen = next((r for r in vol_yes if r["experiment"] == primary_name), vol_yes[0])
    elif gap_yes:
        chosen = next((r for r in gap_yes if r["experiment"] == primary_name), gap_yes[0])
    elif ctx_yes:
        chosen = next((r for r in ctx_yes if r["experiment"] == primary_name), ctx_yes[0])
    else:
        chosen = primary
    out = dict(chosen)
    out["experiments"] = [r["experiment"] for r in per_exp]
    if any(r["ppi_x_vol"] == "sim" for r in per_exp):
        out["ppi_x_vol"] = "sim"
    if any(r["ppi_relativo"] == "sim" for r in per_exp):
        out["ppi_relativo"] = "sim"
    if any(r.get("contexto") == "sim" for r in per_exp):
        out["contexto"] = "sim"
    out["sobrevive_validacao"] = _survive_label(out)
    notes = [r["nota_curto"] for r in per_exp if r.get("nota_curto")]
    out["nota_curto"] = " ".join(notes) if notes else None
    alts = []
    for r in per_exp:
        if r is chosen:
            continue
        if r["ppi_x_vol"] == "sim" or r["ppi_relativo"] == "sim" or r.get("contexto") == "sim":
            alts.append(f"`{r['formulacao']}` ({r['experiment']})")
    out["nota_alt"] = ("Também promove: " + "; ".join(alts)) if alts else None
    out["leitura"] = chosen["leitura"]
    return out


def recommend(cands: list[dict]) -> list[dict]:
    recs = []
    keys = sorted({(r["vector"], r["target"]) for r in cands})
    for vector, target in keys:
        h = DECISION_H.get((vector, target))
        if h is None:
            continue
        pool_all = [r for r in cands if r["vector"] == vector and r["target"] == target]
        pool = [r for r in pool_all if r["horizon"] == h]
        if not pool:
            continue
        descriptive = vector in DESCRIPTIVE_VECTORS or any(r["descriptive"] for r in pool)
        per_exp = []
        for exp in sorted({r["experiment"] for r in pool}):
            sub = [r for r in pool if r["experiment"] == exp]
            sub_all = [r for r in pool_all if r["experiment"] == exp]
            rec = recommend_pool(sub, sub_all, vector, target, h, descriptive)
            if rec:
                per_exp.append(rec)
        if not per_exp:
            continue
        recs.append(merge_recs(per_exp, PRIMARY_EXP.get((vector, target))))
    order = {k: i for i, k in enumerate(DECISION_H)}
    recs.sort(key=lambda r: order.get((r["vector"], r["target"]), 999))
    return recs


def three_questions(recs: list[dict]) -> dict:
    yes = [r for r in recs if r["ppi_x_vol"] == "sim"]
    gap = [r for r in recs if r["ppi_relativo"] == "sim"]
    ctx = [r for r in recs if r.get("contexto") == "sim" and r["ppi_x_vol"] != "sim"]
    no = [
        r
        for r in recs
        if r["ppi_x_vol"] == "não" and r["ppi_relativo"] != "sim" and r.get("contexto") != "sim"
    ]
    desc = [r for r in recs if r["ppi_x_vol"] == "descritivo"]
    return {
        "onde_contribui": [f"{r['target']} ({r['horizon']}): `{r['formulacao']}`" for r in yes],
        "onde_gap_contribui": [f"{r['target']} ({r['horizon']}): `{r['formulacao']}`" for r in gap],
        "onde_contexto_contribui": [f"{r['target']} ({r['horizon']}): `{r['formulacao']}`" for r in ctx],
        "formulacao_por_alvo": [
            {"alvo": r["target"], "horizonte": r["horizon"], "formulacao": r["formulacao"]}
            for r in recs
        ],
        "sobrevivem_validacao": [
            {"alvo": r["target"], "horizonte": r["horizon"], "relacao": r["sobrevive_validacao"]}
            for r in recs
        ],
        "nao_contribuem_exposicao": [r["target"] for r in no],
        "descritivos": [r["target"] for r in desc],
    }


def protocol(results: Path) -> dict:
    contrib = _load(results, "etapa4_prod_contrib.json")
    pt = _load(results, "etapa4_price_transmission.json")
    dm = _load(results, "etapa4_demand.json")
    vol = _load(results, "etapa4_petr4_vol.json")
    inf = _load(results, "etapa4_inflation.json")
    ind = _load(results, "etapa4_independents.json")
    co = _load(results, "etapa4_company.json")
    return {
        "feature_definitions": {
            "prod_mn": "pbr_gas_R × vol_gas_l + pbr_die_R × vol_die_l, R$ millions / day (week mean, month sum)",
            "prod_pbr_mn": "Petrobras mbpd × 1000 × 159 L × PPI deviation, quarter sum",
            "prod_ind_mn": "independent PPI × same ANP national volume",
            "gap": "ind_R − pbr_R (R$/L); not a retail margin",
            "dqty_mn": "change in number of shares traded in millions; total_quantity (not financial cash volume)",
            "y_lags": "realized target lags 1 and 2 (one-step)",
        },
        "information": "contemporaneous / realized exposure on the horizon; no ex-ante forecast",
        "training": {
            "daily_min_train": 40,
            "monthly_min_train": 24,
            "quarterly_min_pairs": 8,
            "ridge_alphas": [0.1, 1.0, 10.0, 100.0],
            "quarterly_alpha": 1.0,
            "windows": "trailing validation blocks; expanding train up to the block start",
        },
        "fold_dates": {
            "mercado_daily": contrib["vectors"]["mercado_PETR4"]["blocks"],
            "preco_weekly": contrib["vectors"]["preco"]["blocks"],
            "atividade_monthly": contrib["vectors"]["atividade"]["blocks"],
            "price_transmission": pt["blocks"],
            "demand": dm["blocks"],
            "petr4_vol": vol["blocks"],
            "inflation": inf["blocks"],
            "independents_daily": ind["daily"].get("blocks"),
            "independents_weekly": ind["weekly"].get("blocks"),
            "company_matched": co["matched_history"]["blocks"],
        },
        "metrics": ["MAE", "RMSE", "median across blocks", "worst_block_RMSE", "paired block comparisons"],
        "promotion": "median RMSE improvement >=5%, majority of identical blocks and median MAE no worse against the corresponding control (y_only, y_seasonal, or same context without exposure); updated dummy reported separately",
        "tie": "RMSE difference < 2% keeps the simpler model",
    }


def write_md(path: Path, report: dict) -> None:
    lines = []
    a = lines.append
    a("# Etapa 4 — matriz por alvo")
    a("")
    a(f"Gerada em {report['completed_at_utc']}. Informação **contemporânea** (exposição realizada no horizonte).")
    a("")
    a("## Base, modelo e exclusões")
    a("")
    a(f"- Freeze: `{report['sqlite']}` SHA-256 `{report['sha256']}`.")
    a(f"- Referência Etapa 3: `{SEP_EXPORT}` SHA-256 `{SEP_SHA256}`.")
    a("- Modelo: Ridge em um passo, intercepto, defasagens 1–2 do alvo realizadas, α ∈ {0,1; 1; 10; 100} no diário/semanal/mensal; α = 1 no trimestre casado.")
    a("- Dummy atualizada em cada data: y[t−1], com a mesma informação observada dos lags da Ridge. Os rótulos 8w, 3m e 21d indicam blocos, não previsões fixas de vários passos.")
    a("- Critério exploratório: RMSE mediano melhora ≥5%, vitória na maioria dos mesmos blocos e MAE mediano não superior contra o controle correspondente: `y_only`, `y_seasonal` ou o mesmo contexto sem exposição. A dummy aparece à parte. Empates de até 2% preservam a especificação mais simples.")
    a("- Comparação **dentro** de cada experimento (amostra idêntica). Independentes usam datas comuns a partir de 01/11/2022.")
    naive = report["data_revision"]
    a(
        f"- Naive setembro = `etapa3_metrics.json`: {naive['naive_sep_equals_etapa3']}. "
        f"Naive freeze = naive setembro: {naive['naive_current_equals_sep']}."
    )
    a("- As 22 revisões da gasolina ficam no treino da Etapa 3, mas algumas alcançam a validação da Etapa 4. Proveniência aberta; igualdade da dummy não prova ausência de efeito nos modelos ajustados.")
    a("- Exclusões: viabilidade ex ante não executada; modelos históricos da Etapa 3 não reajustados; novo ensaio financeiro ARIMA/SARIMA/SES/Holt executado; PPI independente a partir de 01/11/2022; trimestre e volumes com exposição contemporânea descritivos; subvenções ITR nota 4 em 2026.")
    a("")
    a("## Definições de exposição")
    a("")
    a("- `prod_mn`: desvio PPI Petrobras × volume ANP (R$ milhões/dia; média na semana, soma no mês).")
    a("- `prod_pbr_mn`: mbpd Petrobras × 1000 × 159 L × desvio PPI, soma no trimestre.")
    a("- `prod_ind_mn`: PPI dos polos independentes × o mesmo volume ANP nacional.")
    a("- `gap`: desvio independente − desvio Petrobras (R$/L). Não é margem de varejo.")
    a("- `dqty_mn`: variação da quantidade de ações negociadas na B3, em milhões (`total_quantity`), não volume financeiro.")
    a("")
    a("## Janelas de treino e blocos")
    a("")
    folds = report.get("protocol", {}).get("fold_dates", {})
    a("- Diário e semanal: min_train = 40 observações comuns. Mensal: min_train = 24. Trimestre casado: min_pairs = 8, α = 1.")
    a(f"- Mercado diário: {folds.get('mercado_daily')}.")
    a(f"- Preço semanal: {folds.get('preco_weekly')}.")
    a(f"- Atividade/inflação mensal: {folds.get('atividade_monthly')}.")
    a(f"- Companhia (4 trimestres casados): {folds.get('company_matched')}.")
    a("- Independentes: mesma grade, amostra comum a partir de 01/11/2022.")
    a("")
    a("## Três efeitos separados")
    a("")
    a("1. **Revisão da base.** Naive idêntica nos dois SQLite. RT&M passa de 26 para 82 trimestres; 1T22–2T26 inalterado. 4T19 = 72.464 / 8.010.")
    a("2. **História financeira.** Persistência usa o último trimestre; persistência sazonal usa t−4. Estes métodos não medem o benefício da história longa. ARIMA, SARIMA, SES e Holt comparam as janelas completa e de 40 trimestres no ensaio financeiro recalculado.")
    a("3. **Exposição PPI × volume.** Ver a tabela. Contribuição além da história do alvo só onde `ppi_x_vol` = sim.")
    a("")
    a("## Comparações exploratórias (bloco de avaliação)")
    a("")
    a("| Vetor | Alvo | Bloco | Controle | RMSE ctrl | PPI×vol | RMSE | vs y_only | Critério exploratório | Formulação |")
    a("|---|---|---|---|---:|---|---:|---:|---|---|")
    for r in report["recommendations"]:
        vs = r.get("ganho_vol_vs_y_only")
        vs_s = "—" if vs is None else f"{vs:+.1%}"
        rmse_v = r.get("RMSE_ppi_x_vol")
        rmse_v_s = "—" if rmse_v is None else f"{rmse_v:.4g}"
        ctrl_rmse = r.get("RMSE_controle")
        ctrl_s = "—" if ctrl_rmse is None else f"{ctrl_rmse:.4g}"
        a(
            f"| {r['vector']} | {r['target']} | {r['horizon']} | `{r['controle']}` | "
            f"{ctrl_s} | `{r.get('melhor_ppi_x_vol') or '—'}` | {rmse_v_s} | {vs_s} | "
            f"{r['ppi_x_vol']} | `{r['formulacao']}` |"
        )
    a("")
    a("## Leitura por alvo")
    a("")
    for r in report["recommendations"]:
        a(f"- {r['leitura']}")
        if r.get("nota_curto"):
            a(f"  - {r['nota_curto']}")
        if r.get("nota_alt"):
            a(f"  - {r['nota_alt']}")
    a("")
    q = report["three_questions"]
    a("## Onde PPI × volume contribui")
    a("")
    if q["onde_contribui"]:
        for item in q["onde_contribui"]:
            a(f"- {item}")
    else:
        a("- Nenhum alvo nesse bloco atende ao critério exploratório completo.")
    a("")
    a("## Onde o gap independentes−Petrobras contribui")
    a("")
    if q["onde_gap_contribui"]:
        for item in q["onde_gap_contribui"]:
            a(f"- {item}")
    else:
        a("- Nenhum alvo nesse bloco atende ao critério exploratório.")
    a("")
    a("## Onde o contexto (não PPI × volume) contribui")
    a("")
    if q["onde_contexto_contribui"]:
        for item in q["onde_contexto_contribui"]:
            a(f"- {item}")
    else:
        a("- Nenhum alvo nesse bloco atende ao critério exploratório.")
    a("")
    a("## Critério exploratório e limites da seleção")
    a("")
    for item in q["sobrevivem_validacao"]:
        a(f"- {item['alvo']} ({item['horizonte']}): {item['relacao']}")
    a("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    root = find_project_root()
    results = results_dir(root)
    cands = collect(results)
    inject_dummy(cands)
    annotate_vs_y(cands)
    recs = recommend(cands)
    repro = _load(results, "etapa4_repro_naive.json")
    naive_ok = all(x.get("match") for x in repro.get("naive_sep_vs_etapa3_json", []))
    naive_cur = all(x.get("match") for x in repro.get("naive_current_vs_sep", []))
    report = {
        "completed_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sqlite": CURRENT_FREEZE,
        "sha256": CURRENT_SHA256,
        "sep_export": SEP_EXPORT,
        "sep_sha256": SEP_SHA256,
        "information": "contemporaneous / realized lags",
        "model": {
            "family": "Ridge one-step with intercept",
            "y_lags": [1, 2],
            "alphas": [0.1, 1.0, 10.0, 100.0],
            "quarterly_alpha": 1.0,
            "promote": "median RMSE >=5%, majority wins, median MAE no worse against corresponding control; exploratory selection, no independent confirmation",
            "tie": "RMSE difference < 2% keeps the simpler model",
        },
        "protocol": protocol(results),
        "data_revision": {
            "naive_sep_equals_etapa3": naive_ok,
            "naive_current_equals_sep": naive_cur,
            "gasoline_22_weeks": "Etapa 3 train only; overlaps some Etapa 4 validation blocks; provenance open; dummy equality does not validate fitted models",
            "rtm_82": True,
        },
        "exclusions": [
            "forecast feasibility (ex ante) not run",
            "Etapa 3 models not refit; new financial ARIMA/SARIMA/SES/Holt comparison executed separately",
            "independent PPI missing before 2022-11-01",
            "quarterly n=4 descriptive; no promotion rule",
            "1Q26/2Q26 ITR note-4 subsidies",
        ],
        "failure_reasons": [
            "PPI×volume below 5% vs y_only (history of the target already captures the series)",
            "gain on median RMSE with a minority of blocks",
            "MAE worse than the control",
            "short horizon (4w / 5d / 1m) often prefers dummy or zero-change",
            "independent sample starts 2022-11-01; older ABICOM layout omits polos",
        ],
        "candidates": cands,
        "recommendations": recs,
        "three_questions": three_questions(recs),
    }
    out = results / "etapa4_matrix.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    md = results / "etapa4_matrix.md"
    write_md(md, report)
    print("wrote", out)
    print("wrote", md)
    print("recommendations", len(recs), "candidates", len(cands))
    for r in recs:
        print(
            f"  {r['vector']:10} {r['target']:22} {r['horizon']:6} "
            f"vol={r['ppi_x_vol']:10} ctx={str(r.get('contexto')):10} "
            f"form={r['formulacao']}"
        )


if __name__ == "__main__":
    main()
