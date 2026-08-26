"""Normalization, exercised against the three things that actually break here.

The fixtures are deliberately dirty. A test suite that only feeds clean CSV
proves the parser works on data that was never the problem.
"""
from __future__ import annotations

import pytest

from fleet_cost import normalize
from fleet_cost.sources import anp_precos

CABECALHO = ("Regiao - Sigla;Estado - Sigla;Municipio;Revenda;CNPJ da Revenda;"
             "Nome da Rua;Numero Rua;Complemento;Bairro;Cep;Produto;"
             "Data da Coleta;Valor de Venda;Valor de Compra;Unidade de Medida;"
             "Bandeira")


def linha(uf="AL", municipio="RIO LARGO", produto="DIESEL S10",
          data="01/07/2026", venda="6,79"):
    return (f"NE;{uf};{municipio};CDA LTDA;12.486.809/0004-05;RUA X;SN;;"
            f"CENTRO;57100-000;{produto};{data};{venda};;R$ / litro;VIBRA")


def csv_bytes(*linhas, bom=True):
    corpo = "\n".join([CABECALHO, *linhas]) + "\n"
    return ("﻿" + corpo).encode("utf-8") if bom else corpo.encode("utf-8")


def test_bom_nao_esconde_a_primeira_coluna():
    """UTF-8 BOM glues a zero-width mark to the first column name.

    Without `utf-8-sig`, the lookup for 'Regiao - Sigla' misses and the column
    silently disappears — the parser reports success and the data is wrong.
    """
    r = normalize.normalizar(csv_bytes(linha(), bom=True), anp_precos)
    assert "regiao" in r.df.columns
    assert r.df.loc[0, "regiao"] == "NE"


def test_virgula_decimal_nao_vira_centena():
    """'6,79' must be 6.79, never 679.

    A hundredfold error that stays plausible in other columns and is therefore
    the easiest one to ship.
    """
    r = normalize.normalizar(csv_bytes(linha(venda="6,79")), anp_precos)
    assert r.df.loc[0, "preco_venda"] == pytest.approx(6.79)


def test_separador_de_milhar_antes_da_virgula():
    r = normalize.normalizar(csv_bytes(linha(venda="1.234,56")), anp_precos)
    assert r.df.loc[0, "preco_venda"] == pytest.approx(1234.56)


def test_colunas_identificaveis_sao_descartadas():
    """CNPJ and street address must never survive into the frame.

    This is a privacy gate, not a tidiness preference: the raw file identifies
    every filling station, and this repository is public.
    """
    r = normalize.normalizar(csv_bytes(linha()), anp_precos)
    for proibida in ("CNPJ da Revenda", "Revenda", "Nome da Rua", "Cep"):
        assert proibida not in r.df.columns
    texto = r.df.to_csv(index=False)
    assert "12.486.809" not in texto


def test_descarte_e_contado_por_motivo():
    """Discards are reported, never silent."""
    r = normalize.normalizar(csv_bytes(
        linha(),
        linha(venda="nao-e-numero"),
        linha(data="32/13/2026"),
        linha(uf=""),
    ), anp_precos)
    assert r.lidas == 4
    assert sum(r.descartadas.values()) == 3
    assert set(r.descartadas) == {"preco_ilegivel", "data_invalida", "uf_vazia"}
    assert "discarded" in r.relatorio()


def test_coluna_renomeada_na_origem_aborta():
    """Upstream schema drift must raise, not degrade quietly."""
    quebrado = csv_bytes(linha()).replace(b"Valor de Venda", b"Preco Venda")
    with pytest.raises(KeyError, match="schema drift"):
        normalize.normalizar(quebrado, anp_precos)


def test_csv_truncado_no_meio_da_linha():
    corpo = csv_bytes(linha(), linha())[:-25]
    r = normalize.normalizar(corpo, anp_precos)
    assert len(r.df) <= 2


def test_ano_mes_derivado_da_data():
    r = normalize.normalizar(csv_bytes(linha(data="15/03/2025")), anp_precos)
    assert r.df.loc[0, "ano_mes"] == "2025-03"
