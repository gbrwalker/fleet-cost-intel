"""ANP monthly sales of oil derivatives and biofuels, by UF.

Different mutation pattern from prices, and that is exactly why this
source exists: ANP closes month M by the end of M+1, so a freshly
published month is provisional and flips to final later. Prices, by
contrast, rewrite the whole current semester every week.

Two sources that change in different ways are what force this project to
have a real idempotency story instead of a re-run-everything script.
"""
from __future__ import annotations

from datetime import date

NOME = "anp_vendas"
BASE = ("https://www.gov.br/anp/pt-br/centrais-de-conteudo/"
        "dados-abertos/arquivos/vdpb")

COLUNAS = {
    "ANO": "ano",
    "MES": "mes",
    "UNIDADE DA FEDERACAO": "uf",
    "PRODUTO": "produto",
    "VENDAS": "volume_m3",
}
CHAVE = "uf"
PRECO = None


def urls(inicio: date, fim: date) -> list[str]:
    """Yearly files covering the window.

    NOT VERIFIED against the live server, unlike `anp_precos`. Confirming
    this path is implementation task #1, and the fix lands here, in one
    place. Marked so nobody mistakes an assumption for a checked fact.
    """
    return [f"{BASE}/vendas-derivados-{ano}.csv"
            for ano in range(inicio.year, fim.year + 1)]
