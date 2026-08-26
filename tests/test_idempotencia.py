"""Idempotency, proved rather than asserted in the README.

The spec's definition of done says two consecutive runs must produce identical
output. These tests hold each of the three layers to that.
"""
from __future__ import annotations

import hashlib

import pandas as pd
import pytest

from fleet_cost import publish, transform
from fleet_cost.quality import QualityGate


@pytest.fixture(autouse=True)
def _isola(tmp_path, monkeypatch):
    monkeypatch.setattr(publish, "PUBLICADO", tmp_path / "published")
    monkeypatch.chdir(tmp_path)


def observacoes(n=50, uf="AL", preco=6.79, mes="2026-07"):
    return pd.DataFrame({
        "uf": [uf] * n,
        "ano_mes": [mes] * n,
        "produto": ["DIESEL S10"] * n,
        "municipio": [f"CIDADE {i % 7}" for i in range(n)],
        "preco_venda": [preco + (i % 5) * 0.01 for i in range(n)],
    })


def test_agregacao_e_deterministica():
    a = transform.precos_por_uf(observacoes())
    b = transform.precos_por_uf(observacoes())
    pd.testing.assert_frame_equal(a, b)


def test_reprocessar_a_janela_nao_duplica():
    """The natural key is (uf, ano_mes, produto): one row per combination."""
    dobrado = pd.concat([observacoes(), observacoes()], ignore_index=True)
    out = transform.precos_por_uf(dobrado)
    assert len(out) == 1
    assert out.loc[0, "n_observacoes"] == 100


def test_duas_execucoes_produzem_o_mesmo_arquivo():
    df = transform.precos_por_uf(observacoes())
    p1 = publish.publicar(df, "t", key_column="uf")
    h1 = hashlib.sha256(p1.read_bytes()).hexdigest()
    p2 = publish.publicar(df, "t", key_column="uf")
    h2 = hashlib.sha256(p2.read_bytes()).hexdigest()
    assert h1 == h2


def test_portao_reprovado_preserva_a_publicacao_anterior():
    """The whole point of aborting instead of warning."""
    bom = transform.precos_por_uf(observacoes(n=200))
    destino = publish.publicar(bom, "t", key_column="uf")
    antes = destino.read_bytes()

    with pytest.raises(QualityGate):
        publish.publicar(pd.DataFrame(), "t", key_column="uf")

    assert destino.read_bytes() == antes


def test_escrita_atomica_nao_deixa_tmp():
    df = transform.precos_por_uf(observacoes())
    destino = publish.publicar(df, "t", key_column="uf")
    assert not list(destino.parent.glob("*.tmp"))


def test_custo_por_km_cobre_as_tres_pontas():
    precos = transform.precos_por_uf(observacoes())
    consumo = {"consumo_medio": {"pesado": {
        "km_por_litro": 2.5, "faixa": {"min": 2.0, "max": 3.2}}}}
    out = transform.custo_por_km(precos, consumo)
    assert set(out["cenario"]) == {"central", "otimista", "pessimista"}
    central = out[out["cenario"] == "central"].iloc[0]
    assert central["custo_por_km"] == pytest.approx(
        central["preco_medio"] / 2.5, rel=1e-3)


# ── piso ANTT ─────────────────────────────────────────────────────────────
def test_piso_amortiza_o_custo_fixo_com_a_distancia():
    """O piso NÃO é taxa por km, e a diferença é de fator dois.

    `(distância × CCD) + CC`, com CC cobrado uma vez por viagem. Para 2 eixos
    da Resolução 6.084/2026 — CCD 3,9826 e CC 451,84 — o piso por km é 8,501
    a 100 km e 4,434 a 1000. Publicar um número só, sem a distância, erraria por
    esse fator.
    """
    piso = pd.DataFrame({"eixos": [2], "ccd_por_km": [3.9826],
                         "cc_fixo": [451.84], "veiculo": ["Toco"]})
    custo = pd.DataFrame({"uf": ["AL"], "ano_mes": ["2026-07"],
                          "produto": ["DIESEL S10"], "custo_por_km": [2.5],
                          "preco_medio": [6.25]})
    out = transform.contra_piso(custo, piso, distancias_km=(100, 1000))
    por_dist = dict(zip(out["distancia_km"], out["piso_por_km"], strict=True))
    assert por_dist[100] == pytest.approx(8.5010, abs=1e-3)
    assert por_dist[1000] == pytest.approx(4.4344, abs=1e-3)
    assert por_dist[100] / por_dist[1000] > 1.9


def test_toda_linha_declara_a_distancia_de_referencia():
    """Piso por km sem a distância ao lado é número sem significado."""
    piso = transform.carregar_piso()
    custo = pd.DataFrame({"uf": ["AL"], "ano_mes": ["2026-07"],
                          "produto": ["DIESEL S10"], "custo_por_km": [2.5],
                          "preco_medio": [6.25]})
    out = transform.contra_piso(custo, piso)
    assert "distancia_km" in out.columns
    assert out["distancia_km"].notna().all()


def test_piso_com_placeholder_aborta():
    """O arquivo veio com zeros até 2026-08-26. Zero vira margem negativa
    silenciosa, do tamanho exato do custo do combustível."""
    import fleet_cost.transform as tr
    original = (tr.REFERENCIA / "piso_antt.csv").read_text(encoding="utf-8")
    try:
        (tr.REFERENCIA / "piso_antt.csv").write_text(
            "resolucao,publicada_em,tabela,tipo_carga,eixos,veiculo,"
            "ccd_por_km,cc_fixo\nX,2026-01-01,A,carga_geral,2,Toco,0.0,0.0\n",
            encoding="utf-8")
        with pytest.raises(ValueError, match="non-positive CCD"):
            tr.carregar_piso()
    finally:
        (tr.REFERENCIA / "piso_antt.csv").write_text(original, encoding="utf-8")
