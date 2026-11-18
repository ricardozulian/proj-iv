# -*- coding: utf-8 -*-
"""Gera o incremento da Etapa 4 sem remover o esqueleto oficial ou a Etapa 3."""

from __future__ import annotations

import json
from pathlib import Path

from db_access import find_project_root
from etapa4_delivery import br_num, finance_facts, review_comparisons


def _method_text(facts: dict) -> str:
    rec = facts["targets"]["receita RT&M"]
    luc = facts["targets"]["lucro bruto RT&M"]
    mar = facts["targets"]["margem RT&M"]
    return f"""### Etapa 4 — avaliação corrigida

*(Incremento da Etapa 4 — 16/10/2026.)*

A hipótese continua a da etapa anterior: o desvio de paridade de combustíveis ponderado pelo volume acompanha o alvo quando se controla a história recente da própria série. Esse produto entra como `prod` no mercado e como `prod_pbr` na companhia; o nome não é produção. Para o teste, o grupo usou a regressão Ridge, uma regressão linear que penaliza coeficientes grandes e, com isso, reduz o risco de colar demais no treino. A Ridge entra com intercepto, com os valores já observados do alvo um e dois períodos antes (defasagens 1 e 2) e com padronização calculada só no treino. O parâmetro de penalização α escolhe-se em {{0,1; 1; 10; 100}} em blocos internos anteriores à avaliação; no ensaio trimestral descritivo, α = 1. Dentro de cada bloco de datas, os coeficientes ficam fixos, e as defasagens observadas se atualizam a cada nova data.

A comparação ingênua desta etapa é a dummy contemporânea, a previsão que copia o último valor já conhecido: ŷ[t] = y[t−1]. Ela usa a mesma informação observada que a Ridge, e por isso serve de referência justa. A dummy fixa da Etapa 3, que não se atualizava dentro do horizonte, permanece só como referência histórica. Os rótulos 21d, 8w e 3m nomeiam blocos de avaliação, conjuntos de datas em que se mede o erro de um passo, e não previsões de 21 pregões, oito semanas ou três meses de uma só vez. Por isso os erros de um passo da Etapa 4 não se comparam diretamente aos erros de vários passos da Etapa 3.

Cada candidato e o respectivo controle usam as mesmas datas de treino e de avaliação, para que um dado faltante não encolha em silêncio a amostra de um dos lados. A exposição simples, o produto do desvio de paridade pelo volume, compara-se com `y_only`, a Ridge que usa só a história do alvo. A exposição mais sazonalidade compara-se com `y_seasonal`, a mesma Ridge com o ciclo do calendário e sem a exposição. Quando há um contexto extra, o controle é esse contexto sem a exposição. O critério exploratório dos ensaios diários, semanais e mensais pede três coisas ao mesmo tempo: a raiz do erro quadrático médio (RMSE) mediana cai pelo menos 5%; o RMSE é menor na maioria dos mesmos blocos; o erro absoluto médio (MAE) mediano não aumenta. A dummy atualizada aparece numa coluna à parte, porque um RMSE menor que o da dummy não prova que a exposição adiciona informação além da história do alvo. Quando duas especificações ficam até 2% acima do menor RMSE, o estudo fica com a mais simples. Menor erro observado, evidência exploratória e critério atendido permanecem campos distintos.

As semanas de preço começam na segunda-feira e terminam no domingo. A exposição usa o recorte `closed="left", label="left"` do pandas, equivalente a esses intervalos. A sazonalidade mensal entra como a defasagem 12, o mesmo mês do ano anterior. As exposições são contemporâneas: o valor do regressor na data t entra na previsão de t. As defasagens 0 a 8 incluem o lag zero e, por isso, não demonstram que o desvio de paridade antecipe o alvo, nem um atraso causal de oito semanas. A avaliação temporal segue a distinção entre origem, a data em que a previsão é feita, e horizonte em Hyndman e Athanasopoulos (2021).

No ensaio financeiro, o grupo comparou persistência (copiar o último trimestre), persistência sazonal com período 4 (copiar o mesmo trimestre do ano anterior), uma grade limitada de ARIMA e SARIMA trimestrais e três suavizações exponenciais aditivas: nível local, tendência amortecida e tendência amortecida com sazonalidade trimestral. ARIMA é a média móvel integrada auto-regressiva; SARIMA acrescenta o bloco sazonal. São {facts["n_methods"]} métodos e duas janelas de história (a série inteira até a origem, ou só os 40 trimestres anteriores), o que dá {facts["n_configs"]} configurações por alvo. A seleção usa os doze trimestres do 1º trimestre de 2019 ao 4º trimestre de 2021. Travar, neste texto, significa escolher o método e a janela com esses trimestres e não os trocar quando a avaliação passa a 2022–2026; a avaliação posterior mede uma escolha já feita, sem o benefício de ter visto o futuro. O 2º trimestre de 2026 entra separado, como ponto legado já inspecionado. Persistência e persistência sazonal não medem o benefício da história longa, porque as previsões coincidem nas duas janelas. ARIMA, SARIMA e as suavizações ajustam cada janela de treino. A padronização usa só o passado da origem, e a previsão volta à unidade original.

O diagnóstico financeiro contra a persistência usa o RMSE agrupado, a raiz do erro quadrático médio calculada sobre todos os trimestres da janela juntos, o MAE médio e a contagem de origens em que o erro absoluto é menor. Esse diagnóstico não é a regra da mediana por bloco dos ensaios diários, semanais e mensais, e não reabre a seleção depois de 2021. Com a escolha de 2019–2021, a receita fica em {rec["method_label"]} com {rec["window_label"]}; o lucro, em {luc["method_label"]}; a margem, em {mar["method_label"]}, que estima um nível médio da série. O resíduo da extensão financeira é o valor realizado menos essa previsão-base já escolhida na origem. A correção estima, por mínimos quadrados ordinários, um intercepto e um coeficiente para uma exposição, e exige pelo menos oito pares anteriores; com menos pares o estado é histórico insuficiente, e a linha não conta como correção ajustada.

Os ensaios de venda usam o volume contemporâneo na própria exposição e, por isso, permanecem descritivos: o regressor contém parte do que se pretende explicar. A escolha entre várias especificações nos mesmos blocos é seleção exploratória, não confirmação em uma amostra que o grupo não usou para escolher. A viabilidade ex ante, prever só com informação que já teria sido publicada na origem, não foi executada.
"""


def _discussion_text(facts: dict) -> str:
    rec = facts["targets"]["receita RT&M"]
    luc = facts["targets"]["lucro bruto RT&M"]
    mar = facts["targets"]["margem RT&M"]
    die = {(row["alvo"], row["janela"]): row for row in facts["residual"]}
    mid_rec = die[("receita RT&M", "eval_1Q24_1Q26")]
    mid_luc = die[("lucro bruto RT&M", "eval_1Q24_1Q26")]
    mid_mar = die[("margem RT&M", "eval_1Q24_1Q26")]
    pre_rec = die[("receita RT&M", "eval_1Q24_4Q25")]
    pre_luc = die[("lucro bruto RT&M", "eval_1Q24_4Q25")]
    pre_mar = die[("margem RT&M", "eval_1Q24_4Q25")]
    rel_luc = 100 * (luc["rel_RMSE"] or 0)
    return f"""# **Discussão e Conclusão**

*(Incremento da Etapa 4 — 16/10/2026.)*

A hipótese de que o desvio de paridade ponderado pelo volume acompanha os alvos não encontra o mesmo resultado em todos eles. Uma queda do RMSE em alguns blocos de datas não basta quando a maioria dos períodos não melhora ou quando o MAE aumenta, porque o critério pedia as três condições ao mesmo tempo, como mostram a Figura 29 e a Figura 32. No diesel ANP, a extensão que separa gasolina e diesel (`y_fuels`) reduz o RMSE mediano em 16,7%, mas o RMSE é menor em apenas 1 de 4 blocos: a mediana cai porque um bloco de 2026 concentra o ganho, e os outros três não melhoram. A exposição Petrobras contemporânea (`y_pbr0`) usa um único regressor, o PPI da Petrobras vezes o volume na mesma semana, e o RMSE é menor em 3 de 4 blocos contra a história só do alvo; as duas especificações não se confundem, como mostram a Figura 30 na trajetória de `y_pbr0` e a Figura 32 na comparação por bloco. O ensaio do IPCA usa a variação do preço ANP de produtores e importadores da gasolina e, por isso, não constitui evidência sobre o produto desvio × volume, como mostra a Figura 31.

Os controles sazonais, a defasagem 12 do próprio alvo, explicam parte importante da demanda e da mobilidade, como mostra a Figura 33. No varejo, a exposição reduz o RMSE mediano sobre esse controle sazonal, mas o RMSE é menor em só dois de quatro blocos, como mostra a Figura 34. Isso aproxima a análise dos Objetivos de Desenvolvimento Sustentável (ODS) 8, trabalho decente e crescimento econômico, e 11, cidades e comunidades sustentáveis, sem atribuir ao preço do combustível uma causa que o desenho não isola. Para o ODS 16, paz, justiça e instituições eficazes, o produto inclui código, hash efetivo da base, revisão de proveniência e critérios explícitos de comparação. Consistência interna do SQLite e reprodução da dummy não equivalem a auditoria independente das fontes.

Na companhia, a receita permanece com {rec["method_label"]} na escolha feita em 2019–2021. No lucro, {luc["method_label"]} com {luc["window_label"]} reduz o RMSE agrupado em {br_num(rel_luc, 2)}% frente à persistência do 1º trimestre de 2022 ao 1º trimestre de 2026, abaixo do limiar de 5%. Na margem, a configuração escolhida é {mar["method_label"]} com constante, um nível médio da série; o nome SARIMA não implica, neste caso, uma dinâmica sazonal, e a persistência tem RMSE agrupado menor na avaliação ({br_num(mar["pers_RMSE"], 4)} contra {br_num(mar["eval_RMSE"], 4)}). O ranking depois de 2021 permanece descritivo e não escolhe outro método, precisamente porque a trava impede que a avaliação posterior vire uma nova seleção.

A correção do resíduo soma um termo de exposição à previsão-base já escolhida. Com exposição de diesel do 1º trimestre de 2024 ao 1º trimestre de 2026, o RMSE da receita sobe de {br_num(mid_rec["RMSE controle"], 2)} para {br_num(mid_rec["RMSE correção"], 2)} R＄ milhões, enquanto o do lucro cai de {br_num(mid_luc["RMSE controle"], 2)} para {br_num(mid_luc["RMSE correção"], 2)} e o RMSE da margem, de {br_num(mid_mar["RMSE controle"], 2)} para {br_num(mid_mar["RMSE correção"], 2)} pontos percentuais. A Figura 35 mostra o lucro em R＄ milhões e o nível da margem em %, com a avaliação principal em 1T24–1T26 (nove origens) e o 2T26 separado. A comparação entre 1T24–1T26 (nove origens) e 1T24–4T25 (oito origens) retira somente o 1º trimestre de 2026: as três correções aumentam o RMSE nesse recorte (receita {br_num(abs(pre_rec["ganho RMSE %"]), 1)}%, lucro {br_num(abs(pre_luc["ganho RMSE %"]), 1)}%, margem {br_num(abs(pre_mar["ganho RMSE %"]), 1)}%), de modo que o ganho de lucro e margem nessa janela depende da inclusão do primeiro trimestre de 2026, como mostra a Figura 36. O 2º trimestre de 2026 entra à parte, mistura ganhos e perdas e não estabelece estabilidade. As subvenções da nota 4 do Informe Trimestral (ITR) limitam a interpretação; o estudo não atribui toda diferença a elas. O horizonte trimestral curto e a exposição construída com volume contemporâneo, o volume da mesma data que se prevê, mantêm esse resultado no campo descritivo.

As 22 semanas de gasolina revistas ficam no treino da Etapa 3, mas algumas alcançam os blocos de validação da Etapa 4. Sua proveniência permanece aberta: o changelog não explica o acréscimo. A igualdade da dummy nos dois SQLite não demonstra ausência de efeito nos modelos ajustados, porque a dummy não usa os mesmos regressores. O RMSE de `dlog`, a variação logarítmica do preço, mede o erro dessa variação, não o acerto de direção (subida ou descida). `dqty_mn` mede a variação da quantidade de ações negociadas (`total_quantity`), não o volume financeiro em reais.

A viabilidade ex ante, prever só com o calendário de divulgação e a informação que já teria estado disponível na origem, permanece **não executada**. Também não houve confirmação em uma amostra independente após a seleção. Os ajustes SARIMAX (ARIMA sazonal com regressores), Prophet, LSTM (rede recorrente de memória longa) e TimesFM da Etapa 3 permanecem históricos; a grade ARIMA/SARIMA e as suavizações trimestrais não os substituem. O vídeo de apresentação ainda exige produção e publicação pelo grupo.
"""


def _abstract_text(facts: dict) -> str:
    rec = facts["targets"]["receita RT&M"]
    luc = facts["targets"]["lucro bruto RT&M"]
    mar = facts["targets"]["margem RT&M"]
    by_target = {target: c for target, _group, c in review_comparisons()}
    diesel = by_target["ANP diesel"]
    ipca = by_target["IPCA mom"]
    return (
        "# **Resumo**\n\n"
        "*(Incremento da Etapa 4 — 16/10/2026.)*\n\n"
        "O grupo analisou se o desvio de paridade de combustíveis ponderado pelo volume acompanha preços, "
        "atividade econômica, PETR4 (ação preferencial da Petrobras na B3) e as contas de RT&M "
        "(Refino, Transporte e Comercialização) da Petrobras. "
        "O estudo usa o arquivo SQLite congelado, os modelos de referência da Etapa 3 e a regressão Ridge, "
        "uma regressão linear com penalização dos coeficientes, em avaliação temporal de um passo: "
        "em cada data, a estimativa usa valores anteriores observados do alvo e regressores contemporâneos realizados. "
        f"Na comparação com combustíveis separados (`y_fuels`), a raiz do erro quadrático médio (RMSE) mediana do diesel "
        "da Agência Nacional do Petróleo, Gás Natural e Biocombustíveis (ANP) cai "
        f"{br_num(100 * diesel['rel_RMSE_vs_pers'], 1)}%, "
        f"mas o RMSE é menor em apenas {diesel['blocks_better_RMSE']} de {diesel['n_blocks']} blocos de datas; "
        "a exposição Petrobras contemporânea (`y_pbr0`) tem RMSE menor em 3 de 4 blocos, e as duas extensões não são o mesmo regressor. "
        "No Índice Nacional de Preços ao Consumidor Amplo (IPCA), a variação do preço ANP da gasolina reduz o RMSE mediano em "
        f"{br_num(100 * ipca['rel_RMSE_vs_pers'], 1)}% "
        f"e o RMSE é menor em {ipca['blocks_better_RMSE']} de {ipca['n_blocks']} blocos; "
        "esse regressor é a variação do preço ANP de produtores e importadores, não o desvio de paridade ponderado pelo volume.\n\n"
        f"Na grade financeira de {facts['n_configs']} configurações, o grupo escolheu o método com os trimestres de 2019 a 2021 "
        "e manteve essa escolha na avaliação de 2022 a 2026 (a trava). "
        f"A receita permanece com {rec['method_label']}; o lucro, com {luc['method_label']}; a margem, com {mar['method_label']}, "
        "um nível médio da série. SARIMA é a média móvel integrada auto-regressiva sazonal; "
        "neste caso da margem, os índices nulos indicam um nível constante, não um ciclo trimestral. "
        "Nenhum dos três reduz em 5% ou mais o RMSE agrupado, calculado sobre os trimestres juntos, frente à persistência "
        "(copiar o último trimestre) na avaliação do 1º trimestre de 2022 ao 1º trimestre de 2026. "
        "A correção do resíduo soma à previsão já escolhida um termo ligado à exposição de diesel: "
        "reduz o RMSE do lucro e da margem do 1º trimestre de 2024 ao 1º trimestre de 2026 e aumenta o erro das três séries "
        "quando o 1º trimestre de 2026 sai da amostra. O ensaio descreve a associação contemporânea e não promove um modelo de previsão. "
        "O notebook reconstrói os experimentos desde a base. A viabilidade ex ante, prever só com o que já teria sido publicado "
        "na data da origem, não foi executada.\n"
    )


REBUILD = """# Reprodução integral a partir do SQLite; não depende apenas dos JSON existentes.
import io
import json
from contextlib import redirect_stdout
from etapa4_run import main as rebuild_etapa4
from etapa4_delivery import (load, target_table, review_table, interpretation,
                             finance_locked_table, finance_history_table,
                             finance_sensitivity_table, finance_sensitivity_official_table,
                             finance_eval_ranking_table, block_chart, incremental_table)
from IPython.display import Markdown, SVG, display

with redirect_stdout(io.StringIO()) as run_log:
    rebuild_etapa4()
rebuild = load("etapa4_rebuild")
assert rebuild["sha256_actual"] == rebuild["sha256_expected"]
assert rebuild["sqlite_unchanged"] and rebuild["etapa3_unchanged"]
print("Experimentos reconstruídos do SQLite:", len(rebuild["modules_rebuilt"]))
print("SHA-256 efetivo:", rebuild["sha256_actual"])
print("falhas financeiras:", load("etapa4_finance_baseline").get("n_failures"))
"""


def cell(kind: str, source: str, label: str) -> dict:
    out = {"cell_type": kind, "metadata": {"etapa4_promotion": True},
           "id": f"etapa4-{label}", "source": source.splitlines(keepends=True)}
    if kind == "code":
        out.update(execution_count=None, outputs=[])
    return out


def _figure_bundle(intro: str, stem: str, alt: str, caption: str, label: str) -> list[dict]:
    return [
        cell("markdown", intro.rstrip() + "\n", f"intro-{label}"),
        cell("markdown", f"![{alt}](../figures/etapa4/{stem}.svg)\n", f"chart-{label}"),
        cell("markdown", f"*{caption}*\n", f"caption-{label}"),
    ]


def _refresh_interpretation_outputs(nb: dict) -> None:
    from etapa4_delivery import interpretation

    text = interpretation()
    if not text.endswith("\n"):
        text += "\n"
    lines = text.splitlines(keepends=True)
    for existing in nb["cells"]:
        for out in existing.get("outputs") or []:
            data = out.get("data") or {}
            md = data.get("text/markdown")
            if not md:
                continue
            blob = "".join(md) if isinstance(md, list) else str(md)
            if "Leitura dos resultados recalculados" in blob:
                data["text/markdown"] = lines


def build_official(path: Path, facts: dict) -> None:
    nb = json.loads(path.read_text(encoding="utf-8"))
    def _promo_code_key(node: dict) -> str:
        src = "".join(node.get("source") or []).strip()
        return src[:120]

    kept = {}
    for existing in nb["cells"]:
        if existing.get("metadata", {}).get("etapa4_promotion") and existing.get("cell_type") == "code":
            kept[_promo_code_key(existing)] = (existing.get("execution_count"), existing.get("outputs") or [])
    base = [c for c in nb["cells"] if not c.get("metadata", {}).get("etapa4_promotion")]
    assert len(base) == 24, f"expected 24 base cells, got {len(base)}"
    version = "".join(base[0]["source"])
    version = version.replace(
        "O incremento está na EDA, nos modelos base e na primeira tabela de resultados.",
        "O incremento acrescenta a avaliação corrigida de um passo, a grade financeira trimestral e a discussão dos resultados contemporâneos.",
    )
    if "kernel `gas`" not in version:
        version = version.rstrip() + (
            " A grade ARIMA/SARIMA da Etapa 4 reproduz no WSL, kernel `gas` "
            "(Python 3.12.13, statsmodels 0.14.6); neste Windows o OpenBLAS aborta o ajuste.\n"
        )
    base[0]["source"] = version.splitlines(keepends=True)
    base[3]["source"] = _abstract_text(facts).splitlines(keepends=True)
    hist_notes = {
        17: (
            "*(Os parágrafos desta seção descrevem as famílias e os recortes da Etapa 3, "
            "gravados em JSON. Não usam o protocolo de um passo nem a dummy contemporânea desta etapa.)*"
        ),
        19: (
            "*(As Tabelas 1 a 4 e as Figuras 14 a 27 repetem o recorte da Etapa 3: "
            "erro de vários passos, dummy que não se atualiza no horizonte e JSON congelado. "
            "Não usam o protocolo de um passo desta etapa.)*"
        ),
    }
    for index, heading in [(17, "# **Modelos**"), (19, "# **Resultados**")]:
        source = "".join(base[index]["source"])
        note = hist_notes[index]
        if "### Referência histórica — Etapa 3" not in source:
            source = source.replace(heading, heading + "\n\n### Referência histórica — Etapa 3", 1)
        if note not in source:
            source = source.replace(
                "### Referência histórica — Etapa 3\n",
                "### Referência histórica — Etapa 3\n\n" + note + "\n",
                1,
            )
        base[index]["source"] = source.splitlines(keepends=True)
    for md in base:
        if md.get("cell_type") != "markdown":
            continue
        src = "".join(md.get("source") or [])
        changed = False
        if "responde ao choque" in src:
            src = src.replace(
                "A correlação cruzada entre o PPI e cada alvo mede em quantos dias, semanas ou meses o alvo responde ao choque.",
                "A correlação cruzada entre o PPI e cada alvo mede a associação linear em cada defasagem, em dias, semanas ou meses; o pico descreve o treino e não identifica quando o alvo responde a um choque.",
            )
            changed = True
        if "|ccf| < 0,20" in src:
            src = src.replace("|ccf| < 0,20", "ccf em módulo menor que 0,20")
            changed = True
        if changed:
            md["source"] = src.splitlines(keepends=True)
    base[20]["source"] = _discussion_text(facts).splitlines(keepends=True)
    extra = {
        16: [
            cell(
                "markdown",
                "### Revisão da base para a Etapa 4\n\n"
                "*(Incremento da Etapa 4 — 16/10/2026.)*\n\n"
                "A leitura preserva o SQLite. O hash SHA-256 efetivo, a impressão digital do arquivo, "
                "é verificado antes dos experimentos. "
                "O RT&M tem 82 trimestres no calendário, dos quais 26 trazem as contas do segmento. "
                "As exposições semanais usam segunda-feira a domingo; "
                "a soma mensal e a trimestral mantêm suas unidades. "
                "A auditoria de consistência interna não substitui a revisão das fontes originais.\n",
                "base",
            ),
            cell(
                "code",
                "from etapa4_data import CURRENT_FREEZE, load_frames_at, sqlite_file\n"
                "from etapa4_features import add_exposure_variants\n"
                "frames4 = add_exposure_variants(load_frames_at(sqlite_file(CURRENT_FREEZE, project_root), project_root))\n"
                "display(frames4['price_week'][['prod_gas_mn', 'prod_die_mn']].tail())\n"
                "print('Semanas: segunda-feira a domingo; exposição contemporânea em milhões de reais.')\n",
                "features",
            ),
        ],
        18: [cell("markdown", _method_text(facts), "method"), cell("code", REBUILD, "rebuild")],
        19: [
            cell(
                "markdown",
                "## Resultados recalculados da Etapa 4\n\n"
                "*(Incremento da Etapa 4 — 16/10/2026.)*\n\n"
                "A tabela por alvo separa dois números que não são o mesmo julgamento: a menor perda observada "
                "e a extensão escolhida depois do desempate de 2%, que fica com a especificação mais simples "
                "quando o RMSE está perto do mínimo. "
                "O critério de contribuição compara a exposição com o controle correspondente "
                "(história só do alvo, história com sazonalidade, ou o mesmo contexto sem a exposição), "
                "não apenas com a dummy. "
                "As seis comparações da revisão aparecem à parte; os resultados da Etapa 3 acima permanecem históricos.\n",
                "results",
            ),
            cell(
                "code",
                "display(target_table().round(5))\n"
                "display(review_table().round(5))\n"
                "display(Markdown(interpretation()))\n",
                "tables",
            ),
            cell(
                "markdown",
                "A Figura 28 compara o RMSE de cada extensão com o respectivo controle nos blocos de avaliação. "
                "Cada painel usa a unidade do próprio alvo; a altura das curvas não deve ser comparada entre painéis.\n",
                "intro-blocks",
            ),
            cell(
                "markdown",
                "![Figura 28 — RMSE por bloco](../figures/etapa4/erros_por_bloco.svg)\n",
                "blocks",
            ),
            cell(
                "markdown",
                "*Figura 28 — RMSE por bloco nas seis comparações selecionadas da Etapa 4. "
                "Fonte: elaborado pelos autores a partir dos resultados da Etapa 4.*\n",
                "caption-blocks",
            ),
            *_figure_bundle(
                "### Síntese da contribuição incremental\n\n"
                "*(Incremento da Etapa 4 — 16/10/2026.)*\n\n"
                "A Figura 29 reúne a redução ou o aumento percentual do RMSE mediano, as vitórias por bloco e a mudança do MAE mediano, "
                "sempre frente ao controle correspondente. "
                "As três medidas devem ser lidas juntas: reduzir o RMSE mediano em pelo menos 5% não basta para atender ao critério exploratório. "
                "O resultado do IPCA usa preço ANP e aparece separado das exposições PPI × volume.",
                "contribuicao_incremental",
                "Figura 29 — Contribuição incremental",
                "Figura 29 — Contribuição incremental nas comparações selecionadas. "
                "A barra à direita indica RMSE mediano menor que o do controle identificado na linha. "
                "As anotações distinguem redução e aumento do RMSE e do MAE, calculados contra esse controle. "
                "Seis comparações, com 32 observações semanais (dezembro de 2025 a julho de 2026) ou 12 mensais "
                "(maio de 2025 a abril de 2026). "
                "Fonte: elaborado pelos autores a partir dos resultados da Etapa 4.",
                "contribuicao",
            ),
            *_figure_bundle(
                "### Preços e inflação: observado e estimado\n\n"
                "*(Incremento da Etapa 4 — 16/10/2026.)*\n\n"
                "A Figura 30 mostra o preço observado do diesel ANP, a estimativa baseada na história do alvo e a estimativa "
                "com exposição Petrobras contemporânea (`y_pbr0`). As faixas identificam os blocos de avaliação. "
                "As Figuras 30 e 31 mostram quando as diferenças entre os modelos aparecem ao longo da avaliação. "
                "A comparação por bloco é apresentada na Figura 32.",
                "temporal_diesel_anp",
                "Figura 30 — Diesel ANP observado e estimativas",
                "Figura 30 — Diesel ANP observado e estimativas de `y_only` e `y_pbr0`, em R＄/L. "
                "Quatro blocos semanais de 8 de dezembro de 2025 a 13 de julho de 2026 (32 observações). "
                "As faixas indicam os blocos de avaliação. O modelo é ajustado no início de cada bloco, e seus coeficientes permanecem fixos dentro dele. "
                "As estimativas de um passo usam valores anteriores observados do alvo e regressores contemporâneos realizados. "
                "As linhas ligam datas consecutivas; a viabilidade ex ante não foi avaliada. "
                "Erro = observado − estimado: positivo, o modelo subestima o observado; negativo, o modelo superestima. "
                "Fonte: elaborado pelos autores a partir dos resultados da Etapa 4.",
                "temporal-diesel",
            ),
            *_figure_bundle(
                "A Figura 31 apresenta o IPCA observado, o controle baseado na história do alvo e a extensão com variação "
                "do preço ANP da gasolina. Essa série de preços corresponde a produtores e importadores. "
                "O gráfico mostra uma associação contemporânea, sem demonstrar antecipação da inflação.",
                "temporal_ipca",
                "Figura 31 — IPCA observado e estimativas",
                "Figura 31 — IPCA mensal observado e estimativas de `y_only` e `y_anp_gas`, em %. "
                "Quatro blocos mensais de maio de 2025 a abril de 2026 (12 observações). "
                "As faixas indicam os blocos de avaliação. O modelo é ajustado no início de cada bloco, e seus coeficientes permanecem fixos dentro dele. "
                "As estimativas de um passo usam valores anteriores observados do alvo e regressores contemporâneos realizados. "
                "As linhas ligam datas consecutivas; a viabilidade ex ante não foi avaliada. "
                "Erro = observado − estimado: positivo, o modelo subestima o observado; negativo, o modelo superestima. "
                "O regressor de contexto é preço ANP, não PPI × volume. "
                "Fonte: elaborado pelos autores a partir dos resultados da Etapa 4.",
                "temporal-ipca",
            ),
            *_figure_bundle(
                "As trajetórias das Figuras 30 e 31 são complementadas pela Figura 32, que mostra a redução do RMSE em cada bloco. "
                "As duas especificações de diesel usam regressores distintos: `y_fuels` separa as exposições por combustível, "
                "enquanto `y_pbr0` usa uma exposição contemporânea. A comparação preserva o controle de cada experimento.",
                "estabilidade_por_bloco",
                "Figura 32 — Redução do RMSE por bloco",
                "Figura 32 — Redução percentual do RMSE por bloco para duas especificações de diesel ANP e uma extensão de IPCA. "
                "Valores positivos indicam menor erro que o controle. Os períodos semanais e mensais são identificados separadamente. "
                "Fonte: elaborado pelos autores a partir dos resultados da Etapa 4.",
                "estabilidade",
            ),
            *_figure_bundle(
                "### Demanda e mobilidade: sazonalidade e exposição\n\n"
                "*(Incremento da Etapa 4 — 16/10/2026.)*\n\n"
                "A Figura 33 separa a contribuição da sazonalidade da contribuição adicional da exposição. "
                "Para cada alvo, o RMSE mediano do modelo baseado apenas na história recebe índice 100. "
                "As outras barras representam o controle com defasagem 12 e esse mesmo controle acrescido de exposição.",
                "sazonalidade_e_exposicao",
                "Figura 33 — RMSE mediano relativo à história do alvo",
                "Figura 33 — RMSE mediano relativo à história do alvo, definida como 100. "
                "Valores menores indicam menor erro. Os índices permitem comparar reduções relativas, "
                "não os erros absolutos de séries com unidades diferentes. "
                "Quatro alvos, blocos mensais de três meses. "
                "Fonte: elaborado pelos autores a partir dos resultados da Etapa 4.",
                "sazonalidade",
            ),
            *_figure_bundle(
                "A Figura 34 detalha a evolução temporal do varejo, com a série observada, o controle sazonal e a extensão com exposição. "
                "A aproximação entre estimado e observado varia entre os blocos; o gráfico deve ser interpretado em conjunto "
                "com as métricas agregadas e a comparação por bloco.",
                "temporal_varejo",
                "Figura 34 — Varejo observado e estimativas",
                "Figura 34 — Varejo observado e estimativas de `y_seasonal` e `y_seasonal_exp`, "
                "índice mensal do Volume de vendas no varejo (PMC). "
                "Quatro blocos mensais de maio de 2025 a abril de 2026 (12 observações). "
                "As faixas indicam os blocos de avaliação. O modelo é ajustado no início de cada bloco, e seus coeficientes permanecem fixos dentro dele. "
                "As estimativas de um passo usam valores anteriores observados do alvo e regressores contemporâneos realizados. "
                "As linhas ligam datas consecutivas; a viabilidade ex ante não foi avaliada. "
                "Erro = observado − estimado: positivo, o modelo subestima o observado; negativo, o modelo superestima. "
                "Fonte: elaborado pelos autores a partir dos resultados da Etapa 4.",
                "temporal-varejo",
            ),
            cell(
                "markdown",
                "### História financeira e correção do resíduo\n\n"
                "*(Incremento da Etapa 4 — 16/10/2026.)*\n\n"
                "A tabela compacta traz o método e a janela que o grupo escolheu com os trimestres de 2019 a 2021 "
                "e não trocou depois (a trava), o RMSE agrupado dessa seleção e o da avaliação do 1º trimestre de 2022 "
                "ao 1º trimestre de 2026, e a persistência como referência explícita. "
                "O RMSE agrupado junta todos os trimestres da janela numa só raiz; "
                "não é a mediana por bloco usada nos ensaios diários, semanais e mensais. "
                "A margem escolhida estima um nível médio; o nome SARIMA(0,0,0)×(0,0,0)₄ não descreve um ciclo sazonal. "
                "O ranking posterior a 2021 aparece no caderno auxiliar e não escolhe outro método.\n\n"
                "A segunda tabela compara a correção do resíduo, o valor realizado menos essa previsão-base, "
                "quando se acrescenta a exposição de diesel, nas mesmas datas elegíveis. "
                "Os três períodos (1º trimestre de 2024 a 1º trimestre de 2026, o mesmo recorte sem o 1º trimestre de 2026, "
                "e o ponto legado do 2º trimestre de 2026) entram em linhas separadas, "
                "porque um ganho que some sem o 1T26 não se lê como estabilidade. "
                "Receita e lucro estão em R＄ milhões. Nas tabelas, o RMSE da margem está em pontos percentuais; "
                "a Figura 35 mostra o nível da margem em %. "
                "A grade completa e as exposições de gasolina e de `prod` combinado ficam no caderno auxiliar.\n",
                "finance",
            ),
            cell(
                "code",
                "display(finance_locked_table().round(4))\n"
                "display(finance_sensitivity_official_table().round(4))\n",
                "finance-tables",
            ),
            *_figure_bundle(
                "A Figura 35 mostra o lucro bruto e a margem de RT&M observados, a previsão-base do método escolhido "
                "em 2019–2021 e a correção com exposição de diesel. O destaque do 1T26 e a separação do ponto legado 2T26 "
                "permitem examinar a influência desses trimestres sem reunir as duas avaliações. "
                "A avaliação principal da correção abrange 1T24–1T26, com nove origens. "
                "O 2T26 é apresentado separadamente e não integra essa comparação.",
                "correcao_financeira_no_tempo",
                "Figura 35 — Lucro bruto e margem de RT&M",
                "Figura 35 — Lucro bruto e margem de RT&M: observado, baseline travado e correção com diesel, de 1T24 a 2T26. "
                "Lucro em R＄ milhões; margem em %. Dez trimestres. "
                "A avaliação principal da correção abrange 1T24–1T26, com nove origens. "
                "O 2T26 é apresentado separadamente e não integra essa comparação. "
                "A correção usa exposição contemporânea e permanece descritiva. "
                "Fonte: elaborado pelos autores a partir dos resultados da Etapa 4.",
                "correcao-financeira",
            ),
            *_figure_bundle(
                "A Figura 36 quantifica a sensibilidade observada na Figura 35. Compara a redução do RMSE de receita, "
                "lucro e margem em 1T24–1T26, com nove origens, e em 1T24–4T25, com oito. "
                "A diferença entre os recortes é somente a retirada do 1T26; o 2T26 não integra essas barras.",
                "sensibilidade_1t26",
                "Figura 36 — Sensibilidade da correção financeira ao 1T26",
                "Figura 36 — Redução percentual do RMSE pela correção com diesel, frente ao baseline travado. "
                "A análise de sensibilidade compara 1T24–1T26, com nove origens, e 1T24–4T25, com oito. "
                "A segunda janela retira somente o 1T26. O 2T26 permanece separado. "
                "Valores positivos indicam redução do erro; valores negativos indicam aumento. "
                "Fonte: elaborado pelos autores a partir dos resultados da Etapa 4.",
                "sensibilidade",
            ),
        ],
    }
    nb["cells"] = [c for index, original in enumerate(base) for c in [original, *extra.get(index, [])]]
    for existing in nb["cells"]:
        key = _promo_code_key(existing) if existing.get("cell_type") == "code" else None
        if key in kept:
            existing["execution_count"], existing["outputs"] = kept[key]
    _refresh_interpretation_outputs(nb)
    nb["metadata"]["etapa4_protocol"] = "etapa4_review_20261016"
    path.write_text(json.dumps(nb, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def build_auxiliary(path: Path, facts: dict) -> None:
    nb = json.loads(path.read_text(encoding="utf-8"))
    rec = facts["targets"]["receita RT&M"]
    luc = facts["targets"]["lucro bruto RT&M"]
    mar = facts["targets"]["margem RT&M"]
    changes = {
        0: (
            '<img src="../images/mackenzie_logo.jpg" width="25%" align="right"/>\n\n'
            "# Etapa 4 — experimentos (caderno auxiliar)\n\n"
            "Este caderno guarda as grades completas e os ensaios secundários. "
            "A entrega oficial é `proj-iv_grupo19_etapa4.ipynb`. "
            "A primeira célula reconstrói os experimentos a partir dos dois arquivos SQLite e confere os hashes SHA-256, "
            "a impressão digital de cada arquivo.\n\n"
            "O motivador permanece o desvio de paridade ponderado pelo volume, o Índice de Paridade de Preços (PPI) vezes o volume. "
            "A regressão Ridge, linear com penalização dos coeficientes, usa as defasagens já observadas do alvo, "
            "e a dummy contemporânea copia o último valor conhecido em cada data. "
            "Os blocos de 21 pregões, oito semanas ou três meses são janelas em que se mede o erro de um passo, "
            "não previsões de vários passos de uma só vez. "
            "O critério de contribuição compara a exposição com o controle correspondente: "
            "a raiz do erro quadrático médio (RMSE) mediana cai pelo menos 5%, o RMSE é menor na maioria dos blocos, "
            "e o erro absoluto médio (MAE) mediano não aumenta. "
            "A evidência permanece exploratória e contemporânea. "
            "A viabilidade ex ante, prever só com o que já teria sido publicado na origem, não foi executada."
        ),
        7: (
            "## 3. Histórico financeiro (82 trimestres)\n\n"
            "O ensaio compara persistência (copiar o último trimestre), persistência sazonal com período 4 "
            "(copiar o mesmo trimestre do ano anterior), a grade limitada de ARIMA e SARIMA (período 4) "
            "e três suavizações exponenciais aditivas (nível local, tendência amortecida, tendência amortecida com sazonalidade trimestral). "
            "ARIMA é a média móvel integrada auto-regressiva; SARIMA acrescenta o bloco sazonal. "
            f"Cada configuração usa a história completa até a origem e, em paralelo, só os 40 trimestres anteriores, "
            f"o que soma {facts['n_configs']} ensaios por alvo. "
            "A seleção usa só o 1º trimestre de 2019 ao 4º trimestre de 2021. "
            "Travar, neste caderno, significa escolher o método e a janela com esses trimestres e não os trocar "
            "quando a avaliação passa ao 1º trimestre de 2022–1º trimestre de 2026; o 2º trimestre de 2026 aparece separado. "
            "As previsões de persistência não dependem do comprimento total da história, porque copiam um valor já observado. "
            f"Na escolha de 2019–2021, a receita fica em {rec['method_label']}, o lucro em {luc['method_label']} "
            f"e a margem em {mar['method_label']} (nível médio), todos com {rec['window_label']}."
        ),
        13: (
            "## 5. Transmissão de preço (semanal, variação ANP)\n\n"
            "A ANP é a Agência Nacional do Petróleo, Gás Natural e Biocombustíveis. "
            "Os grupos incluem a história do alvo, a mudança de lista da Petrobras, a exposição simples, "
            "as defasagens 0–4 e 0–8 e os sinais separados de gasolina e diesel. "
            "As exposições usam semanas de segunda-feira a domingo. "
            "A dummy usa a variação observada anterior em cada data; Δ=0, prever variação nula, é um referencial distinto. "
            "Os quatro blocos contêm oito avaliações de um passo cada. "
            "As 22 revisões de gasolina ficam no treino da Etapa 3, mas algumas alcançam a validação da Etapa 4."
        ),
        16: (
            "## 6. Demanda e mobilidade (mensal)\n\n"
            "O grupo emparelhou diesel com tráfego pesado, vendas e indústria; gasolina com tráfego leve, vendas e varejo. "
            "A sazonalidade usa a defasagem 12, o mesmo mês do ano anterior. "
            "A exposição com sazonalidade compara com o mesmo controle sazonal, não com a dummy. "
            "As observações e as datas de treino e avaliação são comuns entre os grupos. A dummy se atualiza a cada mês. "
            "As relações com vendas são descritivas, porque o volume da mesma data também entra na exposição."
        ),
        19: (
            "## 7. PETR4 — variação e volatilidade realizada\n\n"
            "PETR4 é a ação preferencial da Petrobras na B3. "
            "Os alvos são a variação logarítmica do preço (`dlog`) e a volatilidade móvel de 5 e 21 pregões, "
            "o desvio-padrão da variação nessas janelas. "
            "Os grupos incluem história, variação da exposição, exposições acumuladas e `dqty_mn`, "
            "a variação da quantidade de ações negociadas (`total_quantity`), não o volume financeiro em reais. "
            "A combinação exposição mais quantidade compara com a quantidade sem exposição. "
            "A dummy se atualiza em cada pregão; Δ=0 permanece um referencial próprio. "
            "O RMSE da variação não mede o acerto de direção (subida ou descida)."
        ),
        22: (
            "## 8. Inflação (IPCA, IPCA-15, IGP-M)\n\n"
            "O IPCA é o Índice Nacional de Preços ao Consumidor Amplo; o IPCA-15 é a prévia de quinze dias; "
            "o IGP-M é o Índice Geral de Preços–Mercado. "
            "Os ensaios usam cada série mensal separadamente, com história, sazonalidade, exposição por combustível "
            "e variação do preço ANP. "
            "Candidato e controle usam as mesmas observações. A dummy se atualiza a cada mês. "
            "A variação ANP da gasolina é um regressor de contexto, o preço de produtores e importadores, "
            "não o desvio de paridade ponderado pelo volume. "
            "Os blocos mensais não comprovam viabilidade de previsão com dados que já teriam estado publicados em tempo real."
        ),
        25: (
            "## 9. Companhia — história casada e correção do resíduo\n\n"
            "O grupo fez dois ensaios descritivos, sem a regra de contribuição dos outros vetores, "
            "porque a janela do 1º trimestre de 2022 ao 2º trimestre de 2026 tem 18 trimestres e a validação usa quatro origens. "
            "A informação permanece contemporânea, da mesma data que se prevê. "
            "Cada especificação leva um regressor de exposição: `prod_pbr` combinado (desvio de paridade da Petrobras vezes o volume), "
            "só gasolina ou só diesel. "
            "O volume da companhia é a taxa da Petrobras em milhares de barris por dia (mbpd), convertida para litros no trimestre.\n\n"
            "**História casada.** Ridge com penalização α = 1, treino a partir do 1º trimestre de 2022, "
            "quatro trimestres antes do 2º trimestre de 2026 (2º trimestre de 2025 ao 1º trimestre de 2026). "
            "A margem derivada é 100 × lucro bruto previsto / receita prevista; a célula omite o ponto se a receita prevista for menor ou igual a zero. "
            "O grupo também relatou os quatro trimestres sem o 1º trimestre de 2026. "
            "A nota 4 do Informe Trimestral (ITR) registra subvenção ao diesel de R＄ 672 milhões no 1º trimestre de 2026 "
            "e de R＄ 9,737 bilhões no 2º trimestre de 2026, com parcela de gasolina neste último.\n\n"
            "**Correção do resíduo.** O referencial é o método e a janela escolhidos na seção 3 com 2019–2021, a trava. "
            "O resíduo é o valor realizado menos essa previsão-base, do 1º trimestre de 2022 em diante. "
            "A correção é mínimos quadrados ordinários (OLS) com intercepto e uma exposição, no mínimo oito pares anteriores; "
            "com menos pares o estado é histórico insuficiente, e a linha não conta como correção ajustada. "
            "A avaliação cobre o 1º trimestre de 2024 ao 1º trimestre de 2026; o 2º trimestre de 2026 fica à parte; "
            "um recorte até o 4º trimestre de 2025 tira 2026. "
            "A diferença de erro não se imputa só à subvenção. O ensaio é descritivo e não promove modelo.\n\n"
            "Reexecutar: `python src/etapa4_company.py`"
        ),
        31: (
            "## 11. Matriz por alvo\n\n"
            "A matriz reúne comparações por blocos de avaliação: 21 pregões, oito semanas, três meses e quatro trimestres descritivos. "
            "Menor erro observado, evidência exploratória e critério incremental são apresentados separadamente, "
            "porque o menor RMSE da grade não é o mesmo julgamento que o critério das três condições. "
            "O desempate de 2% mantém a especificação mais simples. "
            "Nenhuma escolha entre essas grades equivale a confirmação em uma amostra que o grupo não usou para escolher."
        ),
        3: (
            "A auditoria verifica o hash real, as contagens e o RT&M (Refino, Transporte e Comercialização) completo. "
            "As 22 revisões da gasolina ficam no treino da Etapa 3, mas algumas alcançam a validação da Etapa 4. "
            "Sua proveniência permanece aberta; a igualdade da dummy nos dois arquivos não garante igualdade dos modelos ajustados, "
            "porque a dummy não usa os mesmos regressores."
        ),
        9: (
            "### Leitura — história financeira\n\n"
            "A persistência usa só o último trimestre; a persistência sazonal usa o mesmo trimestre do ano anterior. "
            "Esses métodos não medem o benefício da história longa, porque copiam um valor já observado, "
            "com ou sem os 40 trimestres extras. "
            "Conclusões sobre o comprimento da história usam ARIMA, SARIMA e suavização exponencial amortecida, "
            "que ajustam cada janela de treino. "
            f"Com a escolha de 2019–2021, a receita fica em {rec['method_label']}; o lucro, em {luc['method_label']}; "
            f"a margem, em {mar['method_label']}, um nível médio. "
            "O ranking do 1º trimestre de 2022 ao 1º trimestre de 2026 é só descritivo e não escolhe de novo, "
            "porque a trava impede que a avaliação posterior vire uma nova seleção. "
            "O método escolhido em 2019–2021 pode ter RMSE agrupado maior que o da persistência na avaliação. "
            "O RMSE financeiro nesta seção junta todos os trimestres da janela numa só raiz, "
            "distinto da mediana por bloco dos outros vetores."
        ),
        12: (
            "### Leitura — contribuição da exposição\n\n"
            "As métricas foram recalculadas com a dummy atualizada em cada data, o calendário semanal de segunda a domingo "
            "e amostras comuns entre candidato e controle. "
            "A classificação contra a dummy é apenas diagnóstica: um RMSE menor que o da persistência não prova "
            "que a exposição acrescente informação além da história do alvo. "
            "A contribuição incremental usa o controle correspondente e aparece na tabela adicional. "
            "Nem toda queda de RMSE vem acompanhada de maioria de blocos com erro menor ou de MAE que não aumenta, "
            "e o critério pede as três condições."
        ),
        15: (
            "### Leitura — transmissão\n\n"
            "Os blocos de quatro e oito semanas contêm estimativas de um passo, com as defasagens observadas atualizadas. "
            "As defasagens 0–8 incluem a exposição da própria data; por isso não comprovam que o desvio de paridade "
            "antecipe o preço, nem uma transmissão causal em oito semanas. "
            "O RMSE e o MAE podem apontar direções diferentes: o primeiro penaliza erros grandes, o segundo trata todos os desvios por igual."
        ),
        18: (
            "### Leitura — demanda e mobilidade\n\n"
            "Os controles sazonais, a defasagem 12 do próprio alvo, explicam parte relevante dos resultados. "
            "A exposição sazonal compara diretamente com `y_seasonal`, não com a dummy. "
            "O estudo mantém os resultados instáveis e os casos em que a exposição aumenta o erro. "
            "As exposições de vendas contêm o próprio volume da mesma data e permanecem descritivas. "
            "A discussão se relaciona aos Objetivos de Desenvolvimento Sustentável (ODS) 8 e 11."
        ),
        21: (
            "### Leitura — PETR4\n\n"
            "Os ganhos da exposição frente ao histórico do alvo são pequenos ou instáveis entre os blocos. "
            "O RMSE de `dlog` mede o erro da variação logarítmica do preço, não o acerto de direção. "
            "`dqty_mn` é a variação da quantidade de ações negociadas (`total_quantity`), não o volume financeiro em reais."
        ),
        24: (
            "### Leitura — inflação\n\n"
            "A comparação precisa distinguir a exposição desvio de paridade vezes volume da variação do preço ANP na bomba. "
            "No IPCA, `y_anp_gas` usa a variação do preço ANP de produtores e importadores da gasolina, não o PPI. "
            "As métricas abaixo foram recalculadas em amostras comuns; os números do protocolo anterior, "
            "com dummy fixa e semanas diferentes, não sustentam a classificação atual."
        ),
        27: (
            "### Leitura — companhia\n\n"
            "O ensaio é descritivo, inclusive no volume, que entra na própria exposição. "
            f"A correção usa a previsão-base da trava de 2019–2021 ({rec['method_label']} na receita, "
            f"{luc['method_label']} no lucro, {mar['method_label']} na margem), "
            "não um resíduo genérico de persistência. "
            "Lucro e margem precisam ser lidos com e sem o 1º trimestre de 2026: o ganho em 1T24–1T26 "
            "(nove origens) some no recorte 1T24–4T25 (oito origens). O 2º trimestre de 2026 entra à parte. "
            "As subvenções do Informe Trimestral são uma limitação de interpretação, não uma explicação causal isolada. "
            "Uma única observação no 2º trimestre de 2026 não confirma estabilidade."
        ),
        30: (
            "### Leitura — independentes\n\n"
            "Os candidatos compartilham as mesmas datas em que existem PPI da Petrobras e PPI dos polos independentes, "
            "a partir de novembro de 2022. "
            "O gap, a diferença entre esses dois desvios, não é margem de varejo. "
            "O ganho de uma especificação em blocos usados para seleção permanece exploratório."
        ),
        33: (
            "### Leitura — matriz por alvo\n\n"
            "O critério exige queda de RMSE mediano de pelo menos 5%, RMSE menor na maioria dos mesmos blocos "
            "e MAE mediano que não aumenta contra o controle correspondente. "
            "O desempate de 2% prefere a especificação mais simples. "
            "A matriz separa menor erro observado, evidência exploratória e critério atendido, "
            "porque o menor RMSE da grade não é o mesmo julgamento que as três condições. "
            "Não houve confirmação em amostra independente nem validação ex ante.\n\n"
            "As comparações recalculadas aparecem abaixo nas tabelas da entrega; "
            "não se reproduzem as antigas afirmações de ganho em todos os blocos."
        ),
    }
    for index, source in changes.items():
        nb["cells"][index]["source"] = (source + "\n").splitlines(keepends=True)
    for index, c in enumerate(nb["cells"]):
        if c["cell_type"] != "code":
            continue
        source = "".join(c["source"])
        if index == 2:
            if "# Reprodução integral" not in source:
                source = source.replace("audit = json.loads", REBUILD + "\n\naudit = json.loads", 1)
            old_import = (
                "from etapa4_delivery import (load, target_table, review_table, interpretation,\n"
                "                             finance_history_table, finance_sensitivity_table, block_chart, incremental_table)"
            )
            new_import = (
                "from etapa4_delivery import (load, target_table, review_table, interpretation,\n"
                "                             finance_locked_table, finance_history_table,\n"
                "                             finance_sensitivity_table, finance_sensitivity_official_table,\n"
                "                             finance_eval_ranking_table, block_chart, incremental_table)"
            )
            if old_import in source:
                source = source.replace(old_import, new_import, 1)
        source = (
            source.replace('"horizonte":', '"bloco de avaliação":')
            .replace('"promove":', '"critério vs dummy (não incremental)":')
            .replace('"blocos melhores":', '"vitórias vs dummy":')
            .replace('"contribui":', '"critério exploratório PPI×vol":')
            .replace('"sobrevive":', '"resultado exploratório":')
        )
        if index == 8:
            head = source.split("\ndisplay(finance_history_table()", 1)[0]
            if 'print("A persistência' in head:
                head = head[: head.index('print("A persistência')]
            if "display(finance_locked_table()" in head:
                head = head.split("\ndisplay(finance_locked_table()", 1)[0]
            source = (
                head.rstrip()
                + "\n\ndisplay(finance_locked_table().round(4))\n"
                + "display(finance_history_table().round(4))\n"
                + "display(finance_eval_ranking_table().round(4))\n"
                + "print('O ranking 1T22–1T26 é descritivo e não escolhe outro método depois de 2021.')\n"
            )
        if index == 32 and "display(review_table()" not in source:
            source += (
                "\ndisplay(target_table().round(5))\n"
                "display(review_table().round(5))\n"
                "display(Markdown(interpretation()))\n"
                "display(SVG(filename=str(block_chart(project_root))))\n"
            )
        if index in (14, 17, 20, 23) and "incremental_table(t, lab)" not in source:
            variable = {14: "pt", 17: "dm", 20: "vol", 23: "inf"}[index]
            source += f"\nfor lab, t in {variable}['targets'].items():\n    display(incremental_table(t, lab).round(5))\n"
        c["source"] = source.splitlines(keepends=True)
    _refresh_interpretation_outputs(nb)
    nb["metadata"]["etapa4_protocol"] = "etapa4_review_20261016"
    path.write_text(json.dumps(nb, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def main() -> None:
    root = find_project_root()
    from etapa4_charts import write_all
    write_all(root)
    facts = finance_facts(root)
    official = root / "notebooks/proj-iv_grupo19_etapa4.ipynb"
    auxiliary = root / "notebooks/etapa4_experimentos.ipynb"
    build_official(official, facts)
    build_auxiliary(auxiliary, facts)
    json.loads(official.read_text(encoding="utf-8"))
    json.loads(auxiliary.read_text(encoding="utf-8"))
    print("Notebooks atualizados (prosa da Etapa 4); saídas de código preservadas quando o id coincide.")


if __name__ == "__main__":
    main()
