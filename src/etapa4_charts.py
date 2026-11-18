# -*- coding: utf-8 -*-
"""Presentation figures for Etapa 4 from saved JSON. No new model fitting."""

from __future__ import annotations

import csv
import json
import math
import textwrap
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.gridspec import GridSpec

from db_access import find_project_root
from etapa4_delivery import REVIEW, review_comparisons

FONTE = "Fonte: elaborado pelos autores a partir dos resultados da Etapa 4."
STEMS = (
    "contribuicao_incremental",
    "estabilidade_por_bloco",
    "sazonalidade_e_exposicao",
    "correcao_financeira_no_tempo",
    "sensibilidade_1t26",
    "temporal_diesel_anp",
    "temporal_ipca",
    "temporal_varejo",
)
COLOR_OBS = "#222222"
COLOR_CTRL = "#6e6e6e"
COLOR_EXP = "#1f4e79"
COLOR_PBR = "#1b7f5a"
COLOR_FUELS = "#2c6fb5"
COLOR_IPCA = "#c45c00"
COLOR_PPI = "#1f4e79"
COLOR_BASE = "#6a51a3"
COLOR_CORR = "#c0392b"
COLOR_ZERO = "#333333"
COLOR_GUIDE = "#9a9a9a"
COLOR_1T26 = "#f7e3a1"
SEASON_TARGETS = ("tráfego pesado", "tráfego leve", "indústria", "varejo")
SEASON_GROUPS = ("y_only", "y_seasonal", "y_seasonal_exp")
FINANCE_QKEY_1T26 = 2026 * 4 + 1
FINANCE_QKEY_2T26 = 2026 * 4 + 2
FINANCE_QKEY_1T24 = 2024 * 4 + 1


class ChartError(RuntimeError):
    """Raised when candidate and control series cannot be matched."""


def load_json(name: str, root: Path | None = None) -> dict:
    root = root or find_project_root()
    return json.loads((root / "results" / f"{name}.json").read_text(encoding="utf-8"))


def figures_dir(root: Path | None = None) -> Path:
    folder = (root or find_project_root()) / "figures" / "etapa4"
    folder.mkdir(exist_ok=True, parents=True)
    return folder


def improvement_pct(control: float, candidate: float) -> float:
    if control is None or candidate is None:
        return math.nan
    if control != control or candidate != candidate:
        return math.nan
    if control == 0:
        return math.nan
    return 100.0 * (control - candidate) / control


def br_num(value, nd: int = 1) -> str:
    if value is None or value != value:
        return "—"
    text = f"{float(value):,.{nd}f}"
    return text.replace(",", "X").replace(".", ",").replace("X", ".")


def br_signed_pct(value, nd: int = 1) -> str:
    if value is None or value != value:
        return "—"
    text = br_num(abs(value), nd) + "%"
    if value > 0:
        return "+" + text
    if value < 0:
        return "−" + text
    return text


def error_change_phrase(pct, metric: str, nd: int = 1) -> str:
    if pct is None or pct != pct:
        return f"{metric} indefinido"
    mag = br_num(abs(pct), nd) + "%"
    if pct > 0:
        return f"Redução do {metric}: {mag}"
    if pct < 0:
        return f"Aumento do {metric}: {mag}"
    return f"{metric} inalterado"


def qkey_label(qkey: int) -> str:
    year, rem = divmod(int(qkey), 4)
    if rem == 0:
        year -= 1
        rem = 4
    return f"{rem}T{str(year)[2:]}"


def target_node(stem: str, target: str, root: Path | None = None) -> dict:
    payload = load_json(stem, root)
    if stem == "etapa4_prod_contrib":
        for vector in payload["vectors"].values():
            if target in vector.get("targets", {}):
                return vector["targets"][target]
        raise KeyError(target)
    if stem == "etapa4_independents":
        weekly = payload.get("weekly", {}).get("targets", {})
        if target in weekly:
            return weekly[target]
        daily = payload.get("daily", {}).get("targets", {})
        if target in daily:
            return daily[target]
        raise KeyError(target)
    return payload["targets"][target]


def full_blocks(node: dict, group: str, horizon: str) -> list[dict]:
    rows = node["rows"]["groups"][group]
    return [r for r in rows if r["horizon"] == horizon]


def match_blocks(candidate: list[dict], control: list[dict]) -> list[tuple[dict, dict]]:
    by_key = {}
    for rec in control:
        key = (rec["block_start"], rec["block_end"], rec["horizon"])
        if key in by_key:
            raise ChartError(f"duplicate control block {key}")
        by_key[key] = rec
    matched = []
    seen_dates: dict[str, tuple] = {}
    for rec in candidate:
        key = (rec["block_start"], rec["block_end"], rec["horizon"])
        if key not in by_key:
            raise ChartError(f"missing control block {key}")
        ctrl = by_key[key]
        if rec.get("dates") != ctrl.get("dates"):
            raise ChartError(f"date mismatch in {key}")
        if rec.get("actual") != ctrl.get("actual"):
            raise ChartError(f"actual mismatch in {key}")
        if rec.get("n") != ctrl.get("n"):
            raise ChartError(f"n mismatch in {key}")
        for date in rec["dates"]:
            if date in seen_dates:
                raise ChartError(
                    f"duplicate evaluation date {date} in {seen_dates[date]} and {key}"
                )
            seen_dates[date] = key
        matched.append((rec, ctrl))
    return matched


def _style() -> None:
    plt.rcParams.update({
        "font.family": "DejaVu Sans",
        "font.size": 11,
        "axes.titlesize": 13,
        "axes.labelsize": 11,
        "legend.fontsize": 9,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "axes.unicode_minus": False,
        "svg.hashsalt": "proj-iv-etapa4-charts",
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
    })


def save_figure(fig, stem: str, root: Path | None = None) -> tuple[Path, Path]:
    folder = figures_dir(root)
    svg = folder / f"{stem}.svg"
    png = folder / f"{stem}.png"
    fig.savefig(svg, metadata={"Date": None}, bbox_inches="tight", facecolor="white")
    fig.savefig(png, dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return svg, png


def save_table(rows: list[dict], stem: str, root: Path | None = None) -> Path:
    folder = figures_dir(root)
    path = folder / f"{stem}.csv"
    if not rows:
        path.write_text("", encoding="utf-8")
        return path
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return path


def _fonte(fig) -> None:
    fig.text(0.5, 0.01, FONTE, ha="center", va="bottom", fontsize=8, color="#444444")


def _wrapped_note(ax, text: str, *, width: int = 118, y: float = -0.42) -> None:
    """Put a footnote under an axes, wrapped to the axes width so tight bbox does not widen."""
    body = textwrap.fill(" ".join(text.split()), width=width)
    ax.text(
        0.0, y, body,
        transform=ax.transAxes,
        fontsize=7.3, color="#333", ha="left", va="top",
        linespacing=1.28, clip_on=False,
    )


def _period_label(start: str, end: str) -> str:
    a = pd.Timestamp(start)
    b = pd.Timestamp(end)
    return f"{a.strftime('%d/%m/%y')}–{b.strftime('%d/%m/%y')}"


def comparison_rows(root: Path | None = None) -> list[dict]:
    rows = []
    for (stem, target, group, block), (_t, _g, cmp_) in zip(
        REVIEW, review_comparisons(root)
    ):
        rmse_pct = 100.0 * cmp_["rel_RMSE_vs_pers"]
        mae_pct = improvement_pct(cmp_["persistence_median_MAE"], cmp_["median_MAE"])
        rows.append({
            "stem": stem,
            "alvo": target,
            "grupo": group,
            "bloco": block,
            "controle": cmp_["control_group"],
            "rmse_controle": cmp_["persistence_median_RMSE"],
            "rmse_candidato": cmp_["median_RMSE"],
            "mae_controle": cmp_["persistence_median_MAE"],
            "mae_candidato": cmp_["median_MAE"],
            "ganho_rmse_pct": rmse_pct,
            "ganho_mae_pct": mae_pct,
            "vitorias": cmp_["blocks_better_RMSE"],
            "n_blocos": cmp_["n_blocks"],
            "criterio": bool(cmp_["promote_ge_5pct"]),
            "contexto_preco_anp": target == "IPCA mom",
            "n": sum(b["n"] for b in cmp_["block_comparisons"]),
            "inicio": cmp_["block_comparisons"][0]["block_start"],
            "fim": cmp_["block_comparisons"][-1]["block_end"],
        })
    return rows


def fig_contribuicao(root: Path | None = None) -> tuple[Path, Path, Path]:
    rows = comparison_rows(root)
    labels = []
    for row in rows:
        extra = " — preço ANP" if row["contexto_preco_anp"] else ""
        labels.append(f"{row['alvo']}\n{row['grupo']} vs {row['controle']}{extra}")
    values = [row["ganho_rmse_pct"] for row in rows]
    colors = [COLOR_IPCA if row["contexto_preco_anp"] else COLOR_PPI for row in rows]
    y = np.arange(len(rows))[::-1]

    fig, ax = plt.subplots(figsize=(13.33, 7.5))
    ax.barh(y, values, color=colors, height=0.62, zorder=3)
    ax.axvline(0, color=COLOR_ZERO, lw=1.1, zorder=4)
    ax.axvline(5, color=COLOR_GUIDE, lw=1.0, ls=":", zorder=2)
    ax.set_yticks(y)
    ax.set_yticklabels(labels)
    ax.set_xlabel("Variação do RMSE mediano frente ao controle (%)  ·  barra à direita = menor erro")
    ax.set_title("Onde a exposição acrescenta informação?")
    ax.grid(axis="x", alpha=0.25, zorder=0)
    xmax = max(20.0, max(values) + 4)
    xmin = min(-12.0, min(values) - 2)
    ax.set_xlim(xmin, xmax + 38)
    for yi, row, val in zip(y, rows, values):
        crit = "critério sim" if row["criterio"] else "critério não"
        note = (
            f"{error_change_phrase(val, 'RMSE')}  ·  "
            f"{row['vitorias']}/{row['n_blocos']} blocos  ·  {crit}\n"
            f"{error_change_phrase(row['ganho_mae_pct'], 'MAE')}  ·  frente a {row['controle']}"
        )
        ax.text(xmax + 0.6, yi, note, va="center", ha="left", fontsize=7.8, color="#222", linespacing=1.3)
    ax.text(
        5.0, -0.72,
        "5%",
        fontsize=8, color=COLOR_GUIDE, ha="center", va="top",
    )
    ax.annotate(
        "Reduções e aumentos de RMSE e MAE são calculados contra o controle de cada linha. "
        "IPCA: variação do preço ANP de produtores e importadores, não PPI × volume.",
        xy=(0, 0), xytext=(0.02, -0.14), textcoords="axes fraction",
        fontsize=8.2, color="#333", annotation_clip=False,
    )
    _fonte(fig)
    fig.subplots_adjust(left=0.28, right=0.99, top=0.90, bottom=0.18)
    svg, png = save_figure(fig, "contribuicao_incremental", root)
    table = save_table(rows, "contribuicao_incremental", root)
    return svg, png, table


def _block_gain_rows(stem: str, target: str, group: str, horizon: str, root: Path | None) -> list[dict]:
    node = target_node(stem, target, root)
    cmp_ = node["rows"]["comparisons"][group][horizon]
    rows = []
    for block in cmp_["block_comparisons"]:
        rows.append({
            "stem": stem,
            "alvo": target,
            "grupo": group,
            "controle": cmp_["control_group"],
            "bloco": horizon,
            "inicio": block["block_start"],
            "fim": block["block_end"],
            "n": block["n"],
            "rmse_controle": block["control_RMSE"],
            "rmse_candidato": block["candidate_RMSE"],
            "ganho_rmse_pct": improvement_pct(block["control_RMSE"], block["candidate_RMSE"]),
            "vitorias": f"{cmp_['blocks_better_RMSE']}/{cmp_['n_blocks']}",
        })
    return rows


def fig_estabilidade(root: Path | None = None) -> tuple[Path, Path, Path]:
    panels = [
        ("etapa4_prod_contrib", "ANP diesel", "y_fuels", "8w",
         COLOR_FUELS, "ANP diesel — y_fuels vs y_only  (1/4 blocos)"),
        ("etapa4_independents", "ANP diesel", "y_pbr0", "8w",
         COLOR_PBR, "ANP diesel — y_pbr0 vs y_only  (3/4 blocos)"),
        ("etapa4_inflation", "IPCA mom", "y_anp_gas", "3m",
         COLOR_IPCA, "IPCA — y_anp_gas vs y_only  (4/4 blocos; preço ANP)"),
    ]
    all_rows = []
    fig, axes = plt.subplots(3, 1, figsize=(13.33, 7.5), sharey=True)
    fig.suptitle("O resultado se repete entre períodos?", y=0.98)
    for ax, (stem, target, group, horizon, color, title) in zip(axes, panels):
        rows = _block_gain_rows(stem, target, group, horizon, root)
        all_rows.extend(rows)
        x = np.arange(len(rows))
        vals = [r["ganho_rmse_pct"] for r in rows]
        ax.bar(x, vals, color=color, width=0.62, zorder=3)
        ax.axhline(0, color=COLOR_ZERO, lw=1.1, zorder=4)
        ax.set_xticks(x)
        ax.set_xticklabels([_period_label(r["inicio"], r["fim"]) for r in rows], fontsize=8.5)
        ax.set_title(title, loc="left", fontsize=11)
        ax.grid(axis="y", alpha=0.25, zorder=0)
        for xi, val in zip(x, vals):
            va = "bottom" if val >= 0 else "top"
            off = 0.8 if val >= 0 else -0.8
            ax.text(xi, val + off, br_signed_pct(val), ha="center", va=va, fontsize=8)
    axes[1].set_ylabel("Redução do RMSE no bloco (%)")
    axes[0].set_ylim(-20, 45)
    _fonte(fig)
    fig.subplots_adjust(left=0.08, right=0.98, top=0.90, bottom=0.10, hspace=0.55)
    svg, png = save_figure(fig, "estabilidade_por_bloco", root)
    table = save_table(all_rows, "estabilidade_por_bloco", root)
    return svg, png, table


def _median_rmse(node: dict, group: str, horizon: str) -> float:
    recs = full_blocks(node, group, horizon)
    if not recs:
        return math.nan
    return float(np.median([r["RMSE"] for r in recs]))


def fig_sazonalidade(root: Path | None = None) -> tuple[Path, Path, Path]:
    demand = load_json("etapa4_demand", root)
    rows = []
    indices = {g: [] for g in SEASON_GROUPS}
    for target in SEASON_TARGETS:
        node = demand["targets"][target]
        base = _median_rmse(node, "y_only", "3m")
        wins = node["rows"]["comparisons"]["y_seasonal_exp"]["3m"]
        for group in SEASON_GROUPS:
            rmse = _median_rmse(node, group, "3m")
            idx = 100.0 * rmse / base if base else math.nan
            indices[group].append(idx)
            rows.append({
                "stem": "etapa4_demand",
                "alvo": target,
                "grupo": group,
                "controle": "y_only",
                "bloco": "3m",
                "rmse_mediano": rmse,
                "indice_rmse": idx,
                "vitorias_exp_vs_sazonal": f"{wins['blocks_better_RMSE']}/{wins['n_blocks']}",
            })
    x = np.arange(len(SEASON_TARGETS))
    width = 0.26
    fig, ax = plt.subplots(figsize=(13.33, 7.5))
    series = [
        ("y_only", "história do alvo", "#8a8a8a", -width),
        ("y_seasonal", "história + defasagem 12", "#4c78a8", 0.0),
        ("y_seasonal_exp", "sazonal + exposição", "#e45756", width),
    ]
    for group, label, color, shift in series:
        ax.bar(x + shift, indices[group], width=width, color=color, label=label, zorder=3)
        for xi, val in zip(x + shift, indices[group]):
            ax.text(xi, val + 1.5, f"{val:.0f}", ha="center", va="bottom", fontsize=8)
    ax.axhline(100, color=COLOR_ZERO, lw=1.1, zorder=4)
    ax.set_xticks(x)
    ax.set_xticklabels(SEASON_TARGETS)
    ax.set_ylabel("Índice de RMSE — história do alvo = 100; menor é melhor")
    ax.set_title("Quanto do ganho vem da sazonalidade?")
    ax.set_ylim(0, 125)
    ax.legend(loc="upper right")
    ax.grid(axis="y", alpha=0.25, zorder=0)
    ax.text(
        3.0, 52,
        "varejo: exposição\nvence 2 de 4 blocos",
        ha="center", va="bottom", fontsize=8.5, color="#333",
    )
    _fonte(fig)
    fig.subplots_adjust(left=0.08, right=0.98, top=0.90, bottom=0.12)
    svg, png = save_figure(fig, "sazonalidade_e_exposicao", root)
    table = save_table(rows, "sazonalidade_e_exposicao", root)
    return svg, png, table


def _finance_points(root: Path | None, target: str) -> list[dict]:
    company = load_json("etapa4_company", root)
    baseline = load_json("etapa4_finance_baseline", root)
    die = company["residual_correction"]["targets"][target]["corrected"]["die"]
    winner = baseline["targets"][target]["winner"]["method"]
    points = sorted(die["points"], key=lambda r: r["qkey"])
    methods = {p["method"] for p in points}
    if methods != {winner}:
        raise ChartError(f"baseline method mismatch for {target}: {methods} vs {winner}")
    return points


def fig_correcao_financeira(root: Path | None = None) -> tuple[Path, Path, Path]:
    specs = [
        ("lucro bruto RT&M", "Lucro bruto (R$ milhões)", False),
        ("margem RT&M", "Margem (%)", True),
    ]
    fig, axes = plt.subplots(2, 1, figsize=(13.33, 7.5), sharex=True)
    fig.suptitle("Como a correção financeira se comporta no tempo?", y=0.98)
    rows = []
    for ax, (target, ylabel, _is_pct) in zip(axes, specs):
        points = _finance_points(root, target)
        x = np.arange(len(points))
        labels = [qkey_label(p["qkey"]) for p in points]
        actual = np.array([p["actual"] for p in points], float)
        base = np.array([p["baseline_hat"] for p in points], float)
        hat = np.array([p["hat"] for p in points], float)
        idx_1t26 = next(i for i, p in enumerate(points) if p["qkey"] == FINANCE_QKEY_1T26)
        idx_2t26 = next(i for i, p in enumerate(points) if p["qkey"] == FINANCE_QKEY_2T26)
        ax.axvspan(idx_1t26 - 0.4, idx_1t26 + 0.4, color=COLOR_1T26, alpha=0.7, zorder=0)
        ax.axvline(idx_2t26 - 0.5, color="#888888", ls="--", lw=1.0, zorder=2)
        main = slice(0, idx_2t26)
        ax.plot(x[main], actual[main], color=COLOR_OBS, marker="o", lw=1.8, ms=5.5, label="Observado", zorder=4)
        ax.plot(x[main], base[main], color=COLOR_BASE, marker="s", lw=1.5, ms=5, ls="--", label="Baseline travado", zorder=3)
        ax.plot(x[main], hat[main], color=COLOR_CORR, marker="D", lw=1.5, ms=5, label="Correção com diesel", zorder=3)
        ax.plot(x[idx_2t26], actual[idx_2t26], color=COLOR_OBS, marker="o", ms=6.5, zorder=4)
        ax.plot(x[idx_2t26], base[idx_2t26], color=COLOR_BASE, marker="s", ms=6, zorder=3)
        ax.plot(x[idx_2t26], hat[idx_2t26], color=COLOR_CORR, marker="D", ms=6, zorder=3)
        ax.set_ylabel(ylabel)
        ax.grid(alpha=0.25, zorder=0)
        ax.set_xticks(x)
        ax.set_xticklabels(labels)
        y_hi = max(actual.max(), base.max(), hat.max())
        y_lo = min(actual.min(), base.min(), hat.min())
        ax.set_ylim(y_lo - 0.08 * (y_hi - y_lo), y_hi + 0.16 * (y_hi - y_lo))
        if ax is axes[0]:
            ax.legend(loc="upper left", ncol=3, framealpha=0.92)
            ax.annotate(
                "1T26",
                xy=(idx_1t26, actual[idx_1t26]),
                xytext=(idx_1t26 - 1.6, actual[idx_1t26] - 0.12 * (y_hi - y_lo)),
                fontsize=8.5, color="#7a5b00",
                arrowprops=dict(arrowstyle="-", color="#7a5b00", lw=0.8),
            )
            ax.text(
                idx_2t26 - 0.42, y_hi + 0.12 * (y_hi - y_lo),
                "2T26 — ponto legado",
                ha="right", va="top", rotation=90, fontsize=8, color="#555",
            )
        for p, act, bhat, hhat in zip(points, actual, base, hat):
            rows.append({
                "stem": "etapa4_company",
                "alvo": target,
                "grupo": "die",
                "controle": "baseline_travado",
                "qkey": p["qkey"],
                "trimestre": qkey_label(p["qkey"]),
                "legado": p["qkey"] == FINANCE_QKEY_2T26,
                "destaque_1t26": p["qkey"] == FINANCE_QKEY_1T26,
                "observado": act,
                "baseline_hat": bhat,
                "correcao_hat": hhat,
                "metodo": p["method"],
                "status": p["status"],
            })
    fig.text(
        0.08, 0.045,
        "Avaliação principal da correção: 1T24–1T26, com nove origens. "
        "O 2T26 é apresentado separadamente e não integra essa comparação.",
        fontsize=8, color="#444",
    )
    _fonte(fig)
    fig.subplots_adjust(left=0.08, right=0.98, top=0.90, bottom=0.14, hspace=0.18)
    svg, png = save_figure(fig, "correcao_financeira_no_tempo", root)
    table = save_table(rows, "correcao_financeira_no_tempo", root)
    return svg, png, table


def fig_sensibilidade(root: Path | None = None) -> tuple[Path, Path, Path]:
    company = load_json("etapa4_company", root)
    order = [
        ("receita RT&M", "Receita"),
        ("lucro bruto RT&M", "Lucro bruto"),
        ("margem RT&M", "Margem"),
    ]
    windows = [
        ("eval_1Q24_1Q26", "1T24–1T26 (9 origens, com 1T26)", "#4c78a8"),
        ("eval_1Q24_4Q25", "1T24–4T25 (8 origens, sem 1T26)", "#e45756"),
    ]
    rows = []
    values = {w: [] for w, _l, _c in windows}
    for target, _label in order:
        die = company["residual_correction"]["targets"][target]["corrected"]["die"]
        for window, _label_w, _color in windows:
            score = die[window]
            gain = improvement_pct(score["baseline_RMSE"], score["RMSE"])
            values[window].append(gain)
            rows.append({
                "stem": "etapa4_company",
                "alvo": target,
                "grupo": "die",
                "controle": "baseline_travado",
                "janela": window,
                "n": score.get("n"),
                "rmse_controle": score["baseline_RMSE"],
                "rmse_correcao": score["RMSE"],
                "ganho_rmse_pct": gain,
            })
    x = np.arange(len(order))
    width = 0.36
    fig, ax = plt.subplots(figsize=(13.33, 7.5))
    for i, (window, label, color) in enumerate(windows):
        shift = -width / 2 if i == 0 else width / 2
        ax.bar(x + shift, values[window], width=width, color=color, label=label, zorder=3)
        for xi, val in zip(x + shift, values[window]):
            va = "bottom" if val >= 0 else "top"
            off = 2.5 if val >= 0 else -2.5
            ax.text(xi, val + off, br_signed_pct(val), ha="center", va=va, fontsize=9, fontweight="bold")
    ax.axhline(0, color=COLOR_ZERO, lw=1.1, zorder=4)
    ax.set_xticks(x)
    ax.set_xticklabels([lab for _t, lab in order])
    ax.set_ylabel("Redução do RMSE agrupado (%)  ·  positivo = menor erro que o baseline travado")
    ax.set_title("O ganho financeiro depende do 1º trimestre de 2026?")
    ax.legend(loc="lower left")
    ax.grid(axis="y", alpha=0.25, zorder=0)
    ax.set_ylim(-110, 55)
    ax.text(
        0.99, 0.04,
        "Sensibilidade: 1T24–1T26 (9 origens) versus 1T24–4T25 (8 origens). A segunda janela retira somente o 1T26. O 2T26 permanece separado.",
        transform=ax.transAxes, fontsize=8, ha="right", color="#333",
    )
    _fonte(fig)
    fig.subplots_adjust(left=0.10, right=0.98, top=0.90, bottom=0.12)
    svg, png = save_figure(fig, "sensibilidade_1t26", root)
    table = save_table(rows, "sensibilidade_1t26", root)
    return svg, png, table


def _temporal_rows(stem, target, group, control, horizon, root) -> tuple[list[tuple[dict, dict]], list[dict]]:
    node = target_node(stem, target, root)
    matched = match_blocks(full_blocks(node, group, horizon), full_blocks(node, control, horizon))
    rows = []
    for cand, ctrl in matched:
        for date, actual, hat_c, hat_k in zip(
            cand["dates"], cand["actual"], cand["predicted"], ctrl["predicted"]
        ):
            rows.append({
                "stem": stem,
                "alvo": target,
                "grupo": group,
                "controle": control,
                "bloco": horizon,
                "inicio_bloco": cand["block_start"],
                "fim_bloco": cand["block_end"],
                "data": date,
                "observado": actual,
                "estimado_controle": hat_k,
                "estimado_exposicao": hat_c,
                "erro_controle": actual - hat_k,
                "erro_exposicao": actual - hat_c,
            })
    return matched, rows


BAND_EVEN = "#f3f3f3"
BAND_ODD = "#dce6f2"
NOTE_TEMPORAL = (
    "As faixas indicam os blocos de avaliação. O modelo é ajustado no início de cada bloco, "
    "e seus coeficientes permanecem fixos dentro dele. As estimativas de um passo usam valores "
    "anteriores observados do alvo e regressores contemporâneos realizados. As linhas ligam datas "
    "consecutivas; a viabilidade ex ante não foi avaliada.\n"
    "Erro = observado − estimado: positivo, o modelo subestima o observado; negativo, o modelo superestima."
)


def _typical_step_days(dates: list) -> float:
    stamps = pd.to_datetime(sorted(dates))
    if len(stamps) < 2:
        return 7.0
    deltas = np.array([(stamps[i] - stamps[i - 1]) / pd.Timedelta(days=1) for i in range(1, len(stamps))])
    positive = deltas[deltas > 0]
    return float(np.median(positive)) if len(positive) else 7.0


def _split_segments(dates, values, max_gap_days: float):
    dates = pd.to_datetime(list(dates))
    values = np.asarray(values, float)
    if len(dates) == 0:
        return []
    segments = []
    start = 0
    for i in range(1, len(dates)):
        gap = (dates[i] - dates[i - 1]) / pd.Timedelta(days=1)
        if gap > max_gap_days:
            segments.append((dates[start:i], values[start:i]))
            start = i
    segments.append((dates[start:], values[start:]))
    return segments


def _plot_connected(ax, dates, values, max_gap_days: float, **kwargs):
    label = kwargs.pop("label", None)
    first = True
    for seg_dates, seg_vals in _split_segments(dates, values, max_gap_days):
        ax.plot(seg_dates, seg_vals, label=label if first else None, **kwargs)
        first = False


def _block_spans(records: list[dict], step_days: float) -> list[tuple[int, pd.Timestamp, pd.Timestamp]]:
    by_block: dict[int, list[dict]] = {}
    order = []
    for rec in records:
        bid = rec["block"]
        if bid not in by_block:
            order.append(bid)
            by_block[bid] = []
        by_block[bid].append(rec)
    half = pd.Timedelta(days=0.5 * step_days)
    spans = []
    for i, bid in enumerate(order):
        pts = by_block[bid]
        d0 = pts[0]["date"]
        d1 = pts[-1]["date"]
        if i == 0:
            left = d0 - half
        else:
            prev_end = by_block[order[i - 1]][-1]["date"]
            left = prev_end + (d0 - prev_end) / 2
        if i == len(order) - 1:
            right = d1 + half
        else:
            nxt = by_block[order[i + 1]][0]["date"]
            right = d1 + (nxt - d1) / 2
        spans.append((i, left, right))
    return spans


def _plot_temporal(
    matched: list[tuple[dict, dict]],
    title: str,
    ylabel: str,
    control_label: str,
    exposure_label: str,
    exposure_color: str,
    stem: str,
    root: Path | None,
) -> tuple[Path, Path]:
    matched = sorted(matched, key=lambda pair: pair[0]["block_start"])
    records = []
    for block_i, (cand, ctrl) in enumerate(matched):
        for date, actual, hat_c, hat_k in zip(
            cand["dates"], cand["actual"], cand["predicted"], ctrl["predicted"]
        ):
            records.append({
                "date": pd.Timestamp(date),
                "block": block_i,
                "actual": float(actual),
                "hat_c": float(hat_c),
                "hat_k": float(hat_k),
            })
    records.sort(key=lambda rec: rec["date"])
    dates = [rec["date"] for rec in records]
    actual = [rec["actual"] for rec in records]
    hat_k = [rec["hat_k"] for rec in records]
    hat_c = [rec["hat_c"] for rec in records]
    step = _typical_step_days(dates)
    max_gap = 1.5 * step
    spans = _block_spans(records, step)

    fig = plt.figure(figsize=(13.33, 7.5))
    gs = GridSpec(2, 1, height_ratios=[3.1, 1.15], hspace=0.10, figure=fig)
    ax = fig.add_subplot(gs[0])
    ax_e = fig.add_subplot(gs[1], sharex=ax)
    for i, left, right in spans:
        color = BAND_EVEN if i % 2 == 0 else BAND_ODD
        ax.axvspan(left, right, color=color, zorder=0)
        ax_e.axvspan(left, right, color=color, zorder=0)
        mid = left + (right - left) / 2
        ax.text(
            mid, 1.02, f"Bloco {i + 1}",
            transform=ax.get_xaxis_transform(),
            ha="center", va="bottom", fontsize=8.5, color="#4a4a4a",
            clip_on=False, zorder=2,
        )
        if i > 0:
            ax.axvline(left, color="#6a6a6a", lw=1.0, ls=(0, (4, 3)), zorder=1)
            ax_e.axvline(left, color="#6a6a6a", lw=1.0, ls=(0, (4, 3)), zorder=1)
    _plot_connected(
        ax, dates, actual, max_gap,
        color=COLOR_OBS, marker="o", ms=3.6, lw=1.6, label="Observado", zorder=4,
    )
    _plot_connected(
        ax, dates, hat_k, max_gap,
        color=COLOR_CTRL, marker="s", ms=3.2, lw=1.3, ls="--", label=control_label, zorder=3,
    )
    _plot_connected(
        ax, dates, hat_c, max_gap,
        color=exposure_color, marker="D", ms=3.2, lw=1.3, label=exposure_label, zorder=3,
    )
    err_k = np.asarray(actual) - np.asarray(hat_k)
    err_c = np.asarray(actual) - np.asarray(hat_c)
    _plot_connected(
        ax_e, dates, err_k, max_gap,
        color=COLOR_CTRL, marker="s", ms=3.0, lw=1.1, ls="--", zorder=3,
    )
    _plot_connected(
        ax_e, dates, err_c, max_gap,
        color=exposure_color, marker="D", ms=3.0, lw=1.1, zorder=3,
    )
    ax.set_title(title, pad=26)
    ax.set_ylabel(ylabel)
    ax.legend(loc="upper left", ncol=3, framealpha=0.92)
    ax.grid(axis="y", alpha=0.25, zorder=0)
    ax_e.axhline(0, color=COLOR_ZERO, lw=1.7, zorder=4)
    ax_e.set_ylabel("Erro: observado − estimado")
    ax_e.grid(axis="y", alpha=0.25, zorder=0)
    ax_e.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m/%y"))
    ax.tick_params(labelbottom=False)
    _wrapped_note(ax_e, NOTE_TEMPORAL)
    _fonte(fig)
    fig.subplots_adjust(left=0.08, right=0.98, top=0.86, bottom=0.22)
    svg, png = save_figure(fig, stem, root)
    return svg, png


def fig_temporal_diesel(root: Path | None = None) -> tuple[Path, Path, Path]:
    matched, rows = _temporal_rows(
        "etapa4_independents", "ANP diesel", "y_pbr0", "y_only", "8w", root
    )
    svg, png = _plot_temporal(
        matched,
        "Diesel ANP: observado e estimativas de um passo",
        "Preço ANP (R$/L)",
        "Controle y_only",
        "Exposição y_pbr0",
        COLOR_PBR,
        "temporal_diesel_anp",
        root,
    )
    table = save_table(rows, "temporal_diesel_anp", root)
    return svg, png, table


def fig_temporal_ipca(root: Path | None = None) -> tuple[Path, Path, Path]:
    matched, rows = _temporal_rows(
        "etapa4_inflation", "IPCA mom", "y_anp_gas", "y_only", "3m", root
    )
    svg, png = _plot_temporal(
        matched,
        "IPCA: observado e estimativas de um passo",
        "Variação mensal do IPCA (%)",
        "Controle y_only",
        "Contexto y_anp_gas (preço ANP)",
        COLOR_IPCA,
        "temporal_ipca",
        root,
    )
    table = save_table(rows, "temporal_ipca", root)
    return svg, png, table


def fig_temporal_varejo(root: Path | None = None) -> tuple[Path, Path, Path]:
    matched, rows = _temporal_rows(
        "etapa4_demand", "varejo", "y_seasonal_exp", "y_seasonal", "3m", root
    )
    svg, png = _plot_temporal(
        matched,
        "Varejo: observado, controle sazonal e exposição",
        "Volume de vendas no varejo (PMC), índice mensal",
        "Controle y_seasonal",
        "Exposição y_seasonal_exp",
        COLOR_CORR,
        "temporal_varejo",
        root,
    )
    table = save_table(rows, "temporal_varejo", root)
    return svg, png, table


def verify_checkpoints(root: Path | None = None) -> list[str]:
    issues = []

    def near(got, expected, tol, label):
        if got is None or got != got or abs(got - expected) > tol:
            issues.append(f"{label}: got {got}, expected ~{expected}")

    diesel = target_node("etapa4_prod_contrib", "ANP diesel", root)["rows"]["comparisons"]["y_fuels"]["8w"]
    near(diesel["persistence_median_RMSE"], 0.3379, 5e-4, "diesel y_fuels control RMSE")
    near(diesel["median_RMSE"], 0.2815, 5e-4, "diesel y_fuels RMSE")
    near(100 * diesel["rel_RMSE_vs_pers"], 16.7, 0.15, "diesel y_fuels gain")
    if diesel["blocks_better_RMSE"] != 1 or diesel["n_blocks"] != 4:
        issues.append("diesel y_fuels wins != 1/4")

    pbr = target_node("etapa4_independents", "ANP diesel", root)["rows"]["comparisons"]["y_pbr0"]["8w"]
    near(pbr["persistence_median_RMSE"], 0.3375, 5e-4, "diesel y_pbr0 control RMSE")
    near(pbr["median_RMSE"], 0.2893, 5e-4, "diesel y_pbr0 RMSE")
    if pbr["blocks_better_RMSE"] != 3 or pbr["n_blocks"] != 4:
        issues.append("diesel y_pbr0 wins != 3/4")

    ipca = target_node("etapa4_inflation", "IPCA mom", root)["rows"]["comparisons"]["y_anp_gas"]["3m"]
    near(ipca["persistence_median_RMSE"], 0.2505, 5e-4, "IPCA control RMSE")
    near(ipca["median_RMSE"], 0.1995, 5e-4, "IPCA RMSE")
    near(100 * ipca["rel_RMSE_vs_pers"], 20.4, 0.15, "IPCA gain")
    if ipca["blocks_better_RMSE"] != 4:
        issues.append("IPCA wins != 4/4")

    demand = load_json("etapa4_demand", root)
    expected_idx = {
        "tráfego pesado": (100, 34, 38),
        "tráfego leve": (100, 58, 61),
        "indústria": (100, 41, 61),
        "varejo": (100, 45, 36),
    }
    for target, exp in expected_idx.items():
        node = demand["targets"][target]
        base = _median_rmse(node, "y_only", "3m")
        got = tuple(int(round(100 * _median_rmse(node, g, "3m") / base)) for g in SEASON_GROUPS)
        if got != exp:
            issues.append(f"{target} RMSE index {got} != {exp}")
    varejo_wins = demand["targets"]["varejo"]["rows"]["comparisons"]["y_seasonal_exp"]["3m"]
    if varejo_wins["blocks_better_RMSE"] != 2:
        issues.append("varejo wins != 2/4")

    company = load_json("etapa4_company", root)
    expected_fin = {
        ("receita RT&M", "eval_1Q24_1Q26"): -65.8,
        ("receita RT&M", "eval_1Q24_4Q25"): -4.9,
        ("lucro bruto RT&M", "eval_1Q24_1Q26"): 36.5,
        ("lucro bruto RT&M", "eval_1Q24_4Q25"): -9.6,
        ("margem RT&M", "eval_1Q24_1Q26"): 9.2,
        ("margem RT&M", "eval_1Q24_4Q25"): -87.4,
    }
    for (target, window), exp in expected_fin.items():
        sc = company["residual_correction"]["targets"][target]["corrected"]["die"][window]
        got = improvement_pct(sc["baseline_RMSE"], sc["RMSE"])
        near(got, exp, 0.15, f"{target} {window}")
        n_exp = 9 if window.endswith("1Q26") else 8
        if sc.get("n") != n_exp:
            issues.append(f"{target} {window} n={sc.get('n')} != {n_exp}")

    baseline = load_json("etapa4_finance_baseline", root)
    for target in ("lucro bruto RT&M", "margem RT&M"):
        winner = baseline["targets"][target]["winner"]["method"]
        pts = company["residual_correction"]["targets"][target]["corrected"]["die"]["points"]
        if {p["method"] for p in pts} != {winner}:
            issues.append(f"finance method mismatch {target}")
        qkeys = [p["qkey"] for p in pts]
        if qkeys[0] != FINANCE_QKEY_1T24 or qkeys[-1] != FINANCE_QKEY_2T26:
            issues.append(f"finance qkey range {target}: {qkeys[0]}..{qkeys[-1]}")

    for stem, target, group, control, horizon in (
        ("etapa4_independents", "ANP diesel", "y_pbr0", "y_only", "8w"),
        ("etapa4_inflation", "IPCA mom", "y_anp_gas", "y_only", "3m"),
        ("etapa4_demand", "varejo", "y_seasonal_exp", "y_seasonal", "3m"),
    ):
        match_blocks(
            full_blocks(target_node(stem, target, root), group, horizon),
            full_blocks(target_node(stem, target, root), control, horizon),
        )

    varejo_dates = [
        pd.Timestamp(row["data"])
        for row in _temporal_rows(
            "etapa4_demand", "varejo", "y_seasonal_exp", "y_seasonal", "3m", root
        )[1]
    ]
    if len(varejo_dates) != 12:
        issues.append(f"varejo n={len(varejo_dates)} != 12")
    for prev, cur in zip(varejo_dates, varejo_dates[1:]):
        months = (cur.year - prev.year) * 12 + (cur.month - prev.month)
        if months != 1:
            issues.append(f"varejo gap {prev.date()} -> {cur.date()}")
    return issues


def write_all(root: Path | None = None) -> dict[str, tuple[Path, Path, Path]]:
    root = root or find_project_root()
    issues = verify_checkpoints(root)
    if issues:
        raise ChartError("checkpoint mismatch:\n" + "\n".join(issues))
    _style()
    out = {
        "contribuicao_incremental": fig_contribuicao(root),
        "estabilidade_por_bloco": fig_estabilidade(root),
        "sazonalidade_e_exposicao": fig_sazonalidade(root),
        "correcao_financeira_no_tempo": fig_correcao_financeira(root),
        "sensibilidade_1t26": fig_sensibilidade(root),
        "temporal_diesel_anp": fig_temporal_diesel(root),
        "temporal_ipca": fig_temporal_ipca(root),
        "temporal_varejo": fig_temporal_varejo(root),
    }
    preserved = figures_dir(root) / "erros_por_bloco.svg"
    if not preserved.exists():
        raise ChartError("missing preserved figure figures/etapa4/erros_por_bloco.svg")
    return out


def main() -> None:
    root = find_project_root()
    written = write_all(root)
    for stem, (svg, png, table) in written.items():
        print(stem, svg.name, png.name, table.name, png.stat().st_size)
    print("checkpoints ok; preserved erros_por_bloco.svg")


if __name__ == "__main__":
    main()
