"""Business rules: cost per kilometre, and the comparison against the floor.

Idempotency layer 2 of 3: the fact table has natural key (uf, ano_mes,
produto). Reprocessing a window overwrites exactly the rows in that window and
never appends duplicates.

**Aggregation is also a privacy decision, not just a modelling one.** The raw
ANP file identifies every filling station by CNPJ and street address. This
project publishes state-level aggregates and drops those columns at the
normalize step. See docs/DECISIONS.md.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

import yaml

CHAVE = ["uf", "ano_mes", "produto"]
# Absolutos, a partir da raiz do projeto. Relativos, um `cd` — ou um teste que
# troca o diretório — fazia o pacote não achar o próprio arquivo de referência.
_RAIZ = Path(__file__).resolve().parents[2]
REFERENCIA = _RAIZ / "reference"
CONFIG = _RAIZ / "config"


def carregar_consumo() -> dict:
    """Fuel consumption is a DECLARED PARAMETER, not a measurement.

    No reliable public source gives average km/l by vehicle class, so the
    number is configuration with a stated origin and a sensitivity range. The
    published output carries the central value and both ends — which is the
    honest way to answer when a parameter is an assumption.
    """
    return yaml.safe_load((CONFIG / "consumo.yaml").read_text(encoding="utf-8"))


def carregar_piso() -> pd.DataFrame:
    """ANTT minimum freight floor — hand-maintained reference table.

    Checked on 2026-08-26: ANTT's open data portal carries 106 datasets and
    none of them is the freight floor. It lives in ANNEX II of resolutions, as
    PDF, plus an official web calculator. Scraping resolution PDFs was
    rejected: it would be the most fragile part of the project, refreshed two
    or three times a year, and fragile for the wrong reason — it teaches PDF
    parsing, not pipelines.
    """
    # `comment="#"` because provenance lives at the top of the file: the
    # resolution number and the date it was transcribed travel WITH the
    # numbers, not in a sibling doc that drifts out of sync.
    df = pd.read_csv(REFERENCIA / "piso_antt.csv", comment="#",
                     dtype={"eixos": int})
    if (df["ccd_por_km"] <= 0).any():
        raise ValueError(
            "reference/piso_antt.csv has a non-positive CCD. The file shipped "
            "with placeholder zeros until 2026-08-26; a zero floor silently "
            "turns every margin into the fuel cost with the sign flipped."
        )
    return df


def precos_por_uf(df: pd.DataFrame) -> pd.DataFrame:
    """Collapse station-level observations to (uf, ano_mes, produto).

    `n_postos` and `n_observacoes` travel with the aggregate on purpose: a mean
    over three stations and a mean over three hundred are not the same claim,
    and whoever reads the output deserves to tell them apart.
    """
    if df.empty:
        return pd.DataFrame(columns=CHAVE + ["preco_medio", "preco_mediano",
                                             "n_observacoes", "n_municipios"])
    g = df.groupby(CHAVE, dropna=True)
    out = g.agg(
        preco_medio=("preco_venda", "mean"),
        preco_mediano=("preco_venda", "median"),
        preco_min=("preco_venda", "min"),
        preco_max=("preco_venda", "max"),
        n_observacoes=("preco_venda", "size"),
        n_municipios=("municipio", "nunique"),
    ).reset_index()
    for c in ("preco_medio", "preco_mediano", "preco_min", "preco_max"):
        out[c] = out[c].round(4)
    return out


def custo_por_km(precos: pd.DataFrame, consumo: dict) -> pd.DataFrame:
    """Cost per km at the central consumption value and at both ends."""
    cfg = consumo["consumo_medio"]
    linhas = []
    for perfil, v in cfg.items():
        for rotulo, kml in (("central", v["km_por_litro"]),
                            ("otimista", v["faixa"]["max"]),
                            ("pessimista", v["faixa"]["min"])):
            bloco = precos.copy()
            bloco["perfil"] = perfil
            bloco["cenario"] = rotulo
            bloco["km_por_litro"] = kml
            bloco["custo_por_km"] = (bloco["preco_medio"] / kml).round(4)
            linhas.append(bloco)
    return pd.concat(linhas, ignore_index=True) if linhas else precos


def contra_piso(custo: pd.DataFrame, piso: pd.DataFrame,
                distancias_km=(100, 500, 1000)) -> pd.DataFrame:
    """Fuel cost per km against the regulated floor, at reference distances.

    **The floor is not a per-km rate**, and modelling it as one was the first
    version's mistake. The regulated formula is:

        floor (R$ per trip) = distance_km * ccd_per_km + cc_fixed

    `cc_fixed` is loading and unloading, charged once per trip, so it amortises
    over distance. For 2 axles the floor is R$ 8.50/km at 100 km and R$ 4.43/km
    at 1000 km — a factor of two. Publishing one "floor per km" with no
    distance attached would be wrong by that factor, in whichever direction the
    reader happens to assume.

    So the output carries the distance, and every row says which one it used.

    `margem_sobre_combustivel_por_km` is the floor minus the fuel cost. It is
    NOT profit: fuel is one cost among several, and the floor is a legal
    minimum, not a market price. The column is named for what it measures — a
    column called `lucro` would be read as profit by whoever opens the file
    next.
    """
    if custo.empty or piso.empty:
        return custo
    linhas = []
    for d in distancias_km:
        bloco = piso.copy()
        bloco["distancia_km"] = d
        bloco["piso_por_km"] = (
            (bloco["ccd_por_km"] * d + bloco["cc_fixo"]) / d).round(4)
        linhas.append(bloco)
    piso_km = pd.concat(linhas, ignore_index=True)

    j = custo.merge(piso_km, how="cross")
    j["margem_sobre_combustivel_por_km"] = (
        j["piso_por_km"] - j["custo_por_km"]
    ).round(4)
    return j
