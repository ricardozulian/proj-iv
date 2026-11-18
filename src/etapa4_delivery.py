"""Tabelas e gráficos recalculados para os dois notebooks da Etapa 4."""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from db_access import find_project_root

REVIEW = (
    ("etapa4_prod_contrib", "ANP diesel", "y_fuels", "8w"),
    ("etapa4_independents", "ANP gasolina", "y_ind0", "8w"),
    ("etapa4_price_transmission", "ANP gasolina Δ", "y_exp_l08", "8w"),
    ("etapa4_demand", "varejo", "y_seasonal_exp", "3m"),
    ("etapa4_inflation", "IGP-M mom", "y_die_l03", "3m"),
    ("etapa4_inflation", "IPCA mom", "y_anp_gas", "3m"),
)


def load(name: str, root: Path | None = None) -> dict:
    root = root or find_project_root()
    return json.loads((root / "results" / f"{name}.json").read_text(encoding="utf-8"))


def incremental_table(node: dict, target: str) -> pd.DataFrame:
    rows = []
    ev = node.get("rows") or {}
    for group, blocks in ev.get("comparisons", {}).items():
        for block, comparison in blocks.items():
            rows.append({
                "alvo": target, "grupo": group, "bloco": block,
                "controle": comparison["control_group"],
                "RMSE controle": comparison["persistence_median_RMSE"],
                "RMSE extensão": comparison["median_RMSE"],
                "MAE controle": comparison["persistence_median_MAE"],
                "MAE extensão": comparison["median_MAE"],
                "ganho RMSE %": 100 * comparison["rel_RMSE_vs_pers"],
                "vitórias vs controle": f"{comparison['blocks_better_RMSE']}/{comparison['n_blocks']}",
                "critério exploratório": bool(comparison["promote_ge_5pct"]),
            })
    return pd.DataFrame(rows)


def review_comparisons(root: Path | None = None) -> list[tuple[str, str, dict]]:
    out = []
    for name, target, group, block in REVIEW:
        payload = load(name, root)
        if name == "etapa4_prod_contrib":
            node = payload["vectors"]["preco"]["targets"][target]
        elif name == "etapa4_independents":
            node = payload["weekly"]["targets"][target]
        else:
            node = payload["targets"][target]
        out.append((target, group, node["rows"]["comparisons"][group][block]))
    return out


def review_table(root: Path | None = None) -> pd.DataFrame:
    return pd.DataFrame([{
        "alvo": target, "extensão": group, "controle": c["control_group"],
        "RMSE controle": c["persistence_median_RMSE"], "RMSE extensão": c["median_RMSE"],
        "MAE controle": c["persistence_median_MAE"], "MAE extensão": c["median_MAE"],
        "ganho RMSE %": 100 * c["rel_RMSE_vs_pers"],
        "vitórias": f"{c['blocks_better_RMSE']}/{c['n_blocks']}",
        "critério exploratório": c["promote_ge_5pct"],
    } for target, group, c in review_comparisons(root)])


def target_table(root: Path | None = None) -> pd.DataFrame:
    report = load("etapa4_matrix", root)
    return pd.DataFrame([{
        "vetor": r["vector"], "alvo": r["target"], "bloco": r["horizon"],
        "experimento": r["experiment"], "menor erro observado": r["menor_erro_observado"],
        "extensão após desempate": r["melhor_ppi_x_vol"],
        "controle correspondente": r["controle_incremental_exposicao"],
        "RMSE extensão": r["RMSE_ppi_x_vol"],
        "RMSE controle": (r["comparacao_incremental_exposicao"] or {}).get("persistence_median_RMSE", r["RMSE_controle"]),
        "vitórias vs controle": f"{r['comparacao_incremental_exposicao']['blocks_better_RMSE']}/{r['comparacao_incremental_exposicao']['n_blocks']}" if r["comparacao_incremental_exposicao"] else "descritivo",
        "critério PPI × volume": r["ppi_x_vol"], "critério contexto": r["contexto"],
    } for r in report["recommendations"]])


def finance_history_table(root: Path | None = None) -> pd.DataFrame:
    rows = []
    for target, node in load("etapa4_finance_baseline", root)["targets"].items():
        winner = node["winner"]
        for method, windows in node["history_window_comparison"].items():
            full, short = windows["None"], windows["40"]
            full_rmse, short_rmse = full.get("RMSE"), short.get("RMSE")
            diff = None
            if full_rmse == full_rmse and short_rmse == short_rmse and full_rmse is not None:
                diff = full_rmse - short_rmse
            rows.append({
                "alvo": target,
                "método": method_label(method),
                "RMSE história completa": full_rmse,
                "RMSE 40 trimestres": short_rmse,
                "n": full.get("n"),
                "diferença completa − 40": diff,
                "selecionado em 2019–2021": method == winner["method"],
                "método selecionado": method_label(winner["method"]),
                "janela selecionada": window_label(winner["window"]) if method == winner["method"] else None,
            })
    return pd.DataFrame(rows)


def residual_sensitivity_rows(report: dict) -> list[dict]:
    rows = []
    for target, node in report["residual_correction"]["targets"].items():
        baseline = node.get("baseline") or {}
        method = baseline.get("method")
        window = baseline.get("window")
        for group, correction in node["corrected"].items():
            group_base = (correction.get("baseline") or baseline)
            method = group_base.get("method", method)
            window = group_base.get("window", window)
            for window_name in ("eval_1Q24_1Q26", "eval_1Q24_4Q25", "legacy_2Q26"):
                score = correction.get(window_name) or {}
                control_rmse = score.get("baseline_RMSE")
                if control_rmse is None:
                    control_rmse = (node.get("uncorrected") or {}).get(window_name, {}).get("RMSE")
                corr_rmse = score.get("RMSE")
                gain = None
                if control_rmse and corr_rmse == corr_rmse and control_rmse == control_rmse:
                    gain = 100 * (control_rmse - corr_rmse) / control_rmse
                rows.append({
                    "alvo": target,
                    "correção": group,
                    "janela": window_name,
                    "método baseline": method,
                    "janela baseline": window,
                    "n": score.get("n"),
                    "RMSE controle": control_rmse,
                    "RMSE correção": corr_rmse,
                    "ganho RMSE %": gain,
                })
    return rows


PERIOD_LABELS = {
    "eval_1Q24_1Q26": "1T24–1T26",
    "eval_1Q24_4Q25": "1T24–4T25",
    "legacy_2Q26": "2T26 (legado)",
}
EXPOSURE_LABELS = {"prod": "prod combinado", "gas": "gasolina", "die": "diesel"}


def br_num(value, nd: int = 2) -> str:
    if value is None or value != value:
        return "—"
    text = f"{float(value):,.{nd}f}"
    return text.replace(",", "X").replace(".", ",").replace("X", ".")


def window_label(window) -> str:
    if window is None:
        return "história completa"
    return f"{int(window)} trimestres"


def method_label(method: str | None) -> str:
    if not method:
        return "—"
    if method == "persistence":
        return "persistência"
    if method == "seasonal_s4":
        return "persistência sazonal s=4"
    if method == "ses":
        return "nível local (SES)"
    if method == "holt_damped":
        return "tendência aditiva amortecida"
    if method == "hw_add_damped_s4":
        return "Holt–Winters aditivo amortecido s=4"
    if method.startswith("arima_"):
        p, d, q = method.split("_")[1:4]
        return f"ARIMA({p},{d},{q})"
    if method.startswith("sarima_"):
        p, d, q, P, D, Q = method.split("_")[1:7]
        return f"SARIMA({p},{d},{q})×({P},{D},{Q})₄"
    return method


def finance_sensitivity_table(root: Path | None = None) -> pd.DataFrame:
    rows = residual_sensitivity_rows(load("etapa4_company", root))
    for row in rows:
        row["período"] = PERIOD_LABELS.get(row["janela"], row["janela"])
        row["exposição"] = EXPOSURE_LABELS.get(row["correção"], row["correção"])
        row["método"] = method_label(row.get("método baseline"))
        row["janela de história"] = window_label(row.get("janela baseline"))
    return pd.DataFrame(rows)


def finance_locked_table(root: Path | None = None) -> pd.DataFrame:
    report = load("etapa4_finance_baseline", root)
    rows = []
    for target, node in report["targets"].items():
        winner = node["winner"]
        ev = node.get("eval_1Q22_1Q26") or {}
        cmp_ = (node.get("comparison_vs_persistence") or {}).get("eval_1Q22_1Q26") or {}
        pers = cmp_.get("control_RMSE")
        if pers is None:
            pers = ((node.get("history_window_comparison") or {}).get("persistence") or {}).get("None", {}).get("RMSE")
        rel = cmp_.get("rel_RMSE")
        rows.append({
            "alvo": target,
            "método": method_label(winner.get("method")),
            "janela de história": window_label(winner.get("window")),
            "RMSE seleção 1T19–4T21": winner.get("select_RMSE"),
            "RMSE avaliação 1T22–1T26": ev.get("RMSE"),
            "RMSE persistência 1T22–1T26": pers,
            "ganho RMSE % vs persistência": None if rel is None or rel != rel else 100 * rel,
            "diagnóstico 5% vs persistência": "atendido" if cmp_.get("meets_rule") else "não atendido",
            "n avaliação": ev.get("n"),
        })
    return pd.DataFrame(rows)


def finance_sensitivity_official_table(root: Path | None = None) -> pd.DataFrame:
    table = finance_sensitivity_table(root)
    table = table[table["correção"] == "die"].copy()
    return table[[
        "alvo", "método", "janela de história", "exposição", "período", "n",
        "RMSE controle", "RMSE correção", "ganho RMSE %",
    ]].reset_index(drop=True)


def finance_eval_ranking_table(root: Path | None = None, n: int = 5) -> pd.DataFrame:
    rows = []
    for target, node in load("etapa4_finance_baseline", root)["targets"].items():
        locked = node["winner"]
        ranking = (node.get("eval_ranking_1Q22_1Q26") or [])[:n]
        for rank, row in enumerate(ranking, start=1):
            rows.append({
                "alvo": target,
                "posição descritiva 1T22–1T26": rank,
                "método": method_label(row.get("method")),
                "janela de história": window_label(row.get("window")),
                "RMSE agrupado": row.get("RMSE"),
                "é o método travado": (
                    row.get("method") == locked.get("method")
                    and row.get("window") == locked.get("window")
                ),
            })
    return pd.DataFrame(rows)


def finance_facts(root: Path | None = None) -> dict:
    report = load("etapa4_finance_baseline", root)
    company = load("etapa4_company", root)
    grid = report.get("grid") or {}
    facts = {
        "n_methods": grid.get("n_methods", 38),
        "n_configs": grid.get("n_configs", 76),
        "n_failures": report.get("n_failures", 0),
        "targets": {},
    }
    for target, node in report["targets"].items():
        winner = node["winner"]
        ev = node.get("eval_1Q22_1Q26") or {}
        cmp_ = (node.get("comparison_vs_persistence") or {}).get("eval_1Q22_1Q26") or {}
        facts["targets"][target] = {
            "method": winner.get("method"),
            "method_label": method_label(winner.get("method")),
            "window": winner.get("window"),
            "window_label": window_label(winner.get("window")),
            "select_RMSE": winner.get("select_RMSE"),
            "eval_RMSE": ev.get("RMSE"),
            "pers_RMSE": cmp_.get("control_RMSE"),
            "rel_RMSE": cmp_.get("rel_RMSE"),
            "meets_rule": bool(cmp_.get("meets_rule")),
        }
    facts["residual"] = []
    for row in residual_sensitivity_rows(company):
        if row["correção"] != "die":
            continue
        facts["residual"].append(row)
    return facts


def block_chart(root: Path | None = None) -> Path:
    root = root or find_project_root()
    folder = root / "figures/etapa4"
    folder.mkdir(exist_ok=True, parents=True)
    plt.rcParams["svg.hashsalt"] = "proj-iv-etapa4"
    fig, axes = plt.subplots(3, 2, figsize=(12, 11))
    for axis, (target, group, comparison) in zip(axes.flat, review_comparisons(root)):
        blocks = comparison["block_comparisons"]
        dates = [b["block_start"] for b in blocks]
        axis.plot(dates, [b["control_RMSE"] for b in blocks], marker="o", label=comparison["control_group"])
        axis.plot(dates, [b["candidate_RMSE"] for b in blocks], marker="o", label=group)
        axis.set_title(target)
        axis.set_ylabel("RMSE no bloco")
        axis.tick_params(axis="x", labelrotation=25)
        axis.legend(fontsize=8)
        axis.grid(alpha=.25)
    fig.suptitle("Etapa 4 — erros por bloco nas comparações da revisão")
    fig.tight_layout()
    path = folder / "erros_por_bloco.svg"
    fig.savefig(path, metadata={"Date": None})
    plt.close(fig)
    return path


def interpretation(root: Path | None = None) -> str:
    by_target = {target: (group, c) for target, group, c in review_comparisons(root)}
    diesel = by_target["ANP diesel"][1]
    gas = by_target["ANP gasolina"][1]
    dlog = by_target["ANP gasolina Δ"][1]
    varejo = by_target["varejo"][1]
    igpm = by_target["IGP-M mom"][1]
    ipca = by_target["IPCA mom"][1]
    facts = finance_facts(root)
    rec = facts["targets"]["receita RT&M"]
    luc = facts["targets"]["lucro bruto RT&M"]
    mar = facts["targets"]["margem RT&M"]
    die_rows = {(row["alvo"], row["janela"]): row for row in facts["residual"]}
    pre_rec = die_rows[("receita RT&M", "eval_1Q24_4Q25")]
    pre_luc = die_rows[("lucro bruto RT&M", "eval_1Q24_4Q25")]
    pre_mar = die_rows[("margem RT&M", "eval_1Q24_4Q25")]
    return "\n".join([
        "### Leitura dos resultados recalculados",
        "",
        "*(Incremento da Etapa 4 — 16/10/2026.)*",
        "",
        "Com gasolina e diesel em separado (`y_fuels`), o RMSE mediano do diesel ANP cai de "
        f"{br_num(diesel['persistence_median_RMSE'], 4)} para {br_num(diesel['median_RMSE'], 4)} "
        f"({br_num(100 * diesel['rel_RMSE_vs_pers'], 1)}%), mas o RMSE é menor em "
        f"{diesel['blocks_better_RMSE']} de {diesel['n_blocks']} blocos de datas: "
        "a mediana cai porque um bloco de 2026 concentra o ganho, e os outros três não melhoram. "
        "A exposição Petrobras contemporânea (`y_pbr0`) tem RMSE menor em 3 de 4 blocos contra a história só do alvo; "
        "as duas extensões não são o mesmo regressor. "
        "O critério pedia também a maioria dos blocos e o MAE mediano que não aumentasse, "
        "e por isso `y_fuels` não completa a contribuição incremental. "
        "Na gasolina ANP, a exposição dos polos independentes e as defasagens 0–8 da variação também reduzem o RMSE mediano, "
        f"com RMSE menor em {gas['blocks_better_RMSE']} de {gas['n_blocks']} blocos; o MAE, porém, sobe de "
        f"{br_num(gas['persistence_median_MAE'], 4)} para {br_num(gas['median_MAE'], 4)} na exposição independente e de "
        f"{br_num(dlog['persistence_median_MAE'], 4)} para {br_num(dlog['median_MAE'], 4)} na variação, e o critério falha. "
        f"No varejo, a exposição entra sobre o controle sazonal `{varejo['control_group']}` e o RMSE é menor em "
        f"{varejo['blocks_better_RMSE']} de {varejo['n_blocks']} blocos, sem a maioria pedida.",
        "",
        f"O Índice Geral de Preços–Mercado (IGP-M) com exposição de diesel aumenta o RMSE mediano, de "
        f"{br_num(igpm['persistence_median_RMSE'], 4)} "
        f"para {br_num(igpm['median_RMSE'], 4)}. No Índice Nacional de Preços ao Consumidor Amplo (IPCA), "
        "a variação do preço ANP da gasolina reduz o RMSE mediano de "
        f"{br_num(ipca['persistence_median_RMSE'], 4)} para {br_num(ipca['median_RMSE'], 4)} e o RMSE é menor em "
        f"{ipca['blocks_better_RMSE']} de {ipca['n_blocks']} blocos, com MAE menor. "
        "Esse regressor é a variação do preço ANP de produtores e importadores, não o desvio de paridade ponderado pelo volume. "
        "Os regressores da mesma data e as defasagens 0–8 não comprovam antecipação, atraso causal "
        "nem viabilidade ex ante, prever só com o que já teria sido publicado. "
        "A escolha entre especificações nos mesmos blocos permanece exploratória.",
        "",
        "Na grade financeira, o grupo escolheu o método com 2019–2021 e não o trocou depois (a trava). "
        f"A receita permanece com {rec['method_label']} e {rec['window_label']}. "
        f"O lucro fica com {luc['method_label']} e reduz o RMSE agrupado, a raiz sobre os trimestres juntos, "
        f"do 1º trimestre de 2022 ao 1º trimestre de 2026 em "
        f"{br_num(100 * (luc['rel_RMSE'] or 0), 2)}% frente à persistência, abaixo de 5%. "
        f"A margem fica com {mar['method_label']}, um nível médio da série; a persistência tem RMSE agrupado menor na avaliação "
        f"({br_num(mar['pers_RMSE'], 4)} contra {br_num(mar['eval_RMSE'], 4)}). "
        "Nenhum dos três atende o diagnóstico trimestral contra a persistência. Esse diagnóstico usa RMSE agrupado, "
        "MAE médio e origens com menor erro absoluto; não é a regra da mediana por bloco dos ensaios diários, semanais e mensais.",
        "",
        "Com exposição de diesel, a correção do resíduo do 1º trimestre de 2024 ao 1º trimestre de 2026 "
        "aumenta o RMSE da receita e reduz os do lucro e da margem. "
        "A comparação com 1T24–4T25 retira somente o 1º trimestre de 2026 (nove origens contra oito): "
        "as três correções aumentam o RMSE "
        f"(receita {br_num(abs(pre_rec['ganho RMSE %']), 1)}%, lucro {br_num(abs(pre_luc['ganho RMSE %']), 1)}%, "
        f"margem {br_num(abs(pre_mar['ganho RMSE %']), 1)}%), de modo que o ganho de lucro e margem nessa janela "
        "depende da inclusão do primeiro trimestre de 2026. "
        "O 2º trimestre de 2026 entra à parte, mistura ganhos e perdas e não estabelece estabilidade. "
        "Receita e lucro entram em R＄ milhões; o RMSE da margem, em pontos percentuais. "
        "O ensaio residual descreve a associação contemporânea e não promove um modelo de previsão.",
    ])
