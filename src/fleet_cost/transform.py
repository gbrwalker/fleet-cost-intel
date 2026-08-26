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
REFERENCIA = Path("reference")
CONFIG = Path("config")


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
    return pd.read_csv(REFERENCIA / "piso_antt.csv", comment="#",
                       dtype={"eixos": int})


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


def contra_piso(custo: pd.DataFrame, piso: pd.DataFrame) -> pd.DataFrame:
    """Join fuel cost per km against the regulated floor per km.

    `margem_por_km` is the floor minus the fuel cost. It is NOT profit: fuel is
    one cost among several, and the floor is a legal minimum, not a market
    price. Named `margem_sobre_combustivel` for that reason — a column called
    `lucro` would be read as profit by whoever opens the file next.
    """
    if custo.empty or piso.empty:
        return custo
    j = custo.merge(piso, how="cross")
    j["margem_sobre_combustivel_por_km"] = (
        j["piso_por_km"] - j["custo_por_km"]
    ).round(4)
    return j
