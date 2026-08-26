"""Retroactive windows, URL construction and the download layer."""
from __future__ import annotations

import gzip
import hashlib
import urllib.error
from datetime import date

import pytest

from fleet_cost import ingest, windows
from fleet_cost.sources import anp_precos, anp_vendas


# ── janelas ───────────────────────────────────────────────────────────────
def test_cada_fonte_tem_janela_propria():
    """A single global window is either waste or data loss, usually both."""
    assert windows.ANP_PRECOS.days != windows.ANP_VENDAS.days


def test_toda_janela_declara_o_motivo():
    """A number without a reason is a number nobody dares change later."""
    for w in windows.TODAS.values():
        assert len(w.reason) > 40, f"{w.source} has no real reason"


def test_janela_de_precos_cobre_um_semestre():
    """ANP rewrites the current semester, so the window must span one."""
    assert windows.ANP_PRECOS.days >= 183


def test_start_recua_o_numero_de_dias():
    assert windows.ANP_PRECOS.start(date(2026, 8, 26)) == date(2026, 2, 7)


# ── construção de URL ─────────────────────────────────────────────────────
def test_urls_cobrem_todos_os_meses_da_janela():
    u = anp_precos.urls(date(2026, 5, 1), date(2026, 7, 31))
    assert len(u) == 3 * len(anp_precos.GRUPOS)
    assert any("/2026/05-" in x for x in u)
    assert any("/2026/07-" in x for x in u)


def test_urls_viram_o_ano():
    u = anp_precos.urls(date(2025, 11, 1), date(2026, 1, 31))
    assert any("/2025/11-" in x for x in u)
    assert any("/2026/01-" in x for x in u)


def test_url_bate_com_o_padrao_verificado_em_2026_08_26():
    """Pinned against the file actually downloaded when the schema was checked.

    If ANP moves the path, this test fails here instead of the pipeline
    failing at 06:00 on a Wednesday.
    """
    u = anp_precos.urls(date(2026, 7, 1), date(2026, 7, 1))
    assert ("https://www.gov.br/anp/pt-br/centrais-de-conteudo/dados-abertos/"
            "arquivos/shpc/dsan/2026/07-dados-abertos-precos-diesel-gnv.csv") in u


def test_glp_nunca_e_baixado():
    """Cooking gas is not a fleet cost."""
    u = anp_precos.urls(date(2026, 1, 1), date(2026, 12, 31))
    assert not any("glp" in x for x in u)


def test_vendas_gera_uma_url_por_ano():
    assert len(anp_vendas.urls(date(2024, 6, 1), date(2026, 2, 1))) == 3


# ── ingestão ──────────────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def _isola(tmp_path, monkeypatch):
    monkeypatch.setattr(ingest, "RAW", tmp_path / "raw")
    monkeypatch.setattr(ingest, "MANIFESTO", tmp_path / "raw" / "manifest.json")


def test_conteudo_identico_nao_reprocessa(monkeypatch):
    """Layer 1 of idempotency: same hash, no work."""
    monkeypatch.setattr(ingest, "buscar", lambda url, **k: b"col-a;col-b\n1;2\n")
    url = "https://exemplo/2026/07-x.csv"
    primeira, _ = ingest.baixar([url])
    assert primeira[0].mudou is True
    segunda, _ = ingest.baixar([url])
    assert segunda[0].mudou is False
    assert primeira[0].sha256 == segunda[0].sha256


def test_conteudo_diferente_regrava(monkeypatch):
    url = "https://exemplo/2026/07-x.csv"
    monkeypatch.setattr(ingest, "buscar", lambda u, **k: b"antigo")
    ingest.baixar([url])
    monkeypatch.setattr(ingest, "buscar", lambda u, **k: b"novo")
    novos, _ = ingest.baixar([url])
    assert novos[0].mudou is True


def test_404_e_tolerado_e_nao_derruba(monkeypatch):
    """A month not yet published is expected, not a failure."""
    def erro(url, **k):
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
    monkeypatch.setattr(ingest, "buscar", erro)
    baixados, ausentes = ingest.baixar(["https://exemplo/2026/12-x.csv"])
    assert baixados == []
    assert ausentes == ["https://exemplo/2026/12-x.csv"]


def test_bruto_e_gravado_comprimido_e_le_de_volta(monkeypatch):
    corpo = b"col;val\nAL;6,79\n" * 50
    monkeypatch.setattr(ingest, "buscar", lambda u, **k: corpo)
    baixados, _ = ingest.baixar(["https://exemplo/2026/07-x.csv"])
    b = baixados[0]
    assert b.caminho.suffix == ".gz"
    assert gzip.decompress(b.caminho.read_bytes()) == corpo
    assert ingest.ler(b.caminho) == corpo
    assert b.sha256 == hashlib.sha256(corpo).hexdigest()


def test_404_nao_e_repetido(monkeypatch):
    """Hammering a government server for a file that does not exist is how an
    IP gets blocked."""
    chamadas = {"n": 0}

    def erro(url, timeout=0):
        chamadas["n"] += 1
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)

    monkeypatch.setattr(urllib.request, "urlopen", erro)
    with pytest.raises(urllib.error.HTTPError):
        ingest.buscar("https://exemplo/x.csv", tentativas=4)
    assert chamadas["n"] == 1


def test_mes_ausente_e_extraido_da_url():
    """The gap gate needs to know WHICH months the source skipped."""
    assert ingest.meses_ausentes([
        "https://x/anp/2026/04-dados-abertos-precos-diesel-gnv.csv",
        "https://x/anp/2026/04-dados-abertos-precos-gasolina-etanol.csv",
        "https://x/anp/2026/06-dados-abertos-precos-diesel-gnv.csv",
    ]) == {"2026-04", "2026-06"}


def test_lacuna_da_origem_nao_derruba_o_portao():
    """ANP's monthly series really is missing 2026-04 and 2026-06 (checked
    2026-08-26). A gate that cannot tell a source gap from a download gap
    would abort forever over something nobody can fix."""
    import pandas as pd

    from fleet_cost import quality

    df = pd.DataFrame({"ano_mes": ["2026-03", "2026-05", "2026-07"]})
    with pytest.raises(quality.QualityGate):
        quality.gap_check(df, "ano_mes", "x")
    quality.gap_check(df, "ano_mes", "x",
                      conhecidos_ausentes={"2026-04", "2026-06"})
