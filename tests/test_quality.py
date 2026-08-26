"""Every gate must ABORT. A gate that warns has already failed at its job."""
from __future__ import annotations

import pandas as pd
import pytest

from fleet_cost import quality
from fleet_cost.quality import QualityGate


def frame(n=100, uf="AL", preco=6.79):
    return pd.DataFrame({"uf": [uf] * n, "preco_medio": [preco] * n,
                         "ano_mes": ["2026-07"] * n})


def test_snapshot_vazio_aborta():
    """A source that is down and answers 200 with an empty body is a Tuesday."""
    with pytest.raises(QualityGate, match="empty"):
        quality.validate(pd.DataFrame(), frame(), "x")


def test_queda_de_volume_aborta():
    with pytest.raises(QualityGate, match="row count fell"):
        quality.validate(frame(30), frame(100), "x")


def test_queda_dentro_do_limite_passa():
    quality.validate(frame(60), frame(100), "x")


def test_coluna_chave_ausente_aborta():
    novo = frame().drop(columns=["uf"])
    with pytest.raises(QualityGate, match="schema drift"):
        quality.validate(novo, frame(), "x", key_column="uf")


def test_chave_vazia_acima_do_limite_aborta():
    novo = frame(100)
    novo.loc[:20, "uf"] = ""
    with pytest.raises(QualityGate, match="empty"):
        quality.validate(novo, frame(), "x", key_column="uf")


def test_preco_fora_de_faixa_aborta():
    """679 instead of 6.79 — the decimal-separator failure, caught at the door."""
    novo = frame(100, preco=679.0)
    with pytest.raises(QualityGate, match="outside"):
        quality.validate(novo, frame(), "x", price_column="preco_medio")


def test_um_outlier_isolado_nao_aborta():
    """One weird row in a thousand is data, not a broken parser."""
    novo = frame(1000)
    novo.loc[0, "preco_medio"] = 999.0
    quality.validate(novo, frame(1000), "x", price_column="preco_medio")


def test_mes_faltando_na_janela_aborta():
    df = pd.DataFrame({"ano_mes": ["2026-01", "2026-02", "2026-05"]})
    with pytest.raises(QualityGate, match="missing period"):
        quality.gap_check(df, "ano_mes", "x")


def test_janela_continua_passa():
    df = pd.DataFrame({"ano_mes": ["2026-01", "2026-02", "2026-03"]})
    quality.gap_check(df, "ano_mes", "x")


def test_primeira_publicacao_nao_compara_volume():
    """First run has no previous snapshot; only the empty gate applies."""
    quality.validate(frame(5), pd.DataFrame(), "x", key_column="uf")
