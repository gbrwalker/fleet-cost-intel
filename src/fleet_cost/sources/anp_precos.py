"""ANP weekly fuel price survey.

Schema verified against the real file on 2026-08-26 by downloading
`.../shpc/dsan/2026/07-dados-abertos-precos-diesel-gnv.csv` (3.8 MB) and
reading it. Not assumed from documentation.

Three things about this file break naive parsers, and all three are handled in
`normalize`:
  1. UTF-8 **with BOM** — the first column name arrives as a BOM-prefixed
     'Regiao - Sigla'.
  2. Separator is ';', not ','.
  3. Decimal separator is ',', so 6,79 becomes 679 if you let it.
"""
from __future__ import annotations

from datetime import date

NOME = "anp_precos"
BASE = ("https://www.gov.br/anp/pt-br/centrais-de-conteudo/"
        "dados-abertos/arquivos/shpc/dsan")

# The monthly files split fuels into two documents. GLP is cooking gas and is
# irrelevant to fleet cost, so it is never downloaded.
GRUPOS = ("diesel-gnv", "gasolina-etanol")

# Column contract. A key missing here is upstream schema drift: abort, not warn.
COLUNAS = {
    "Regiao - Sigla": "regiao",
    "Estado - Sigla": "uf",
    "Municipio": "municipio",
    "Produto": "produto",
    "Data da Coleta": "coletado_em",
    "Valor de Venda": "preco_venda",
    "Unidade de Medida": "unidade",
}
CHAVE = "uf"
PRECO = "preco_venda"

# Columns deliberately DROPPED and never republished — see docs/DECISIONS.md.
# The raw file identifies every filling station by CNPJ and street address.
DESCARTAR = ("Revenda", "CNPJ da Revenda", "Nome da Rua", "Numero Rua",
             "Complemento", "Bairro", "Cep", "Bandeira", "Valor de Compra")

PRODUTOS_FROTA = ("DIESEL", "DIESEL S10", "GNV")


def urls(inicio: date, fim: date) -> list[str]:
    """Monthly file URLs covering [inicio, fim].

    The monthly layout exists from 2023 on. Earlier data lives in semester
    files under a different naming scheme; this project starts at 2023 and the
    README says so, rather than silently returning less than was asked for.
    """
    out: list[str] = []
    ano, mes = inicio.year, inicio.month
    while (ano, mes) <= (fim.year, fim.month):
        out.extend(f"{BASE}/{ano}/{mes:02d}-dados-abertos-precos-{grupo}.csv"
                   for grupo in GRUPOS)
        mes += 1
        if mes > 12:
            ano, mes = ano + 1, 1
    return out
