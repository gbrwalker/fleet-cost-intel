"""Turn raw bytes into a typed frame with an explicit schema contract.

Discards are COUNTED, never silent. A project that does not say what it threw
away is hiding what it did not understand.

Two things here are specific to Brazilian public data and are the usual cause
of a parser that "works" while producing garbage:

  * **UTF-8 with BOM.** The first column name arrives with a zero-width
    byte-order mark glued to it, so a lookup for 'Regiao - Sigla' misses and
    the column silently goes missing. Verified in the real file on 2026-08-26.
  * **Comma as decimal separator.** '6,79' read with the default parser
    becomes 679 — a hundredfold error that stays inside a plausible-looking
    range for other columns and is therefore easy to miss.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field

import pandas as pd


@dataclass
class Resultado:
    df: pd.DataFrame
    lidas: int
    descartadas: dict[str, int] = field(default_factory=dict)

    @property
    def taxa_descarte(self) -> float:
        return 0.0 if not self.lidas else sum(self.descartadas.values()) / self.lidas

    def relatorio(self) -> str:
        if not self.descartadas:
            return f"    {self.lidas} rows read, none discarded"
        detalhe = ", ".join(f"{k}={v}" for k, v in sorted(self.descartadas.items()))
        return (f"    {self.lidas} rows read, "
                f"{sum(self.descartadas.values())} discarded "
                f"({self.taxa_descarte:.2%}) — {detalhe}")


def _sem_bom(nome: str) -> str:
    return nome.lstrip("﻿").strip()


def para_numero(s: pd.Series) -> pd.Series:
    """Brazilian decimal notation to float.

    '1.234,56' -> 1234.56. Order matters: strip the thousands dot BEFORE
    swapping the decimal comma, or '1.234,56' becomes 1.23456.
    """
    return pd.to_numeric(
        s.astype(str)
        .str.strip()
        .str.replace(".", "", regex=False)
        .str.replace(",", ".", regex=False)
        .replace({"": None, "nan": None}),
        errors="coerce",
    )


def normalizar(bruto: bytes, fonte) -> Resultado:
    """Apply the source's column contract. Missing key column is schema drift."""
    texto = bruto.decode("utf-8-sig", errors="replace")
    df = pd.read_csv(io.StringIO(texto), sep=";", dtype=str, low_memory=False)
    df.columns = [_sem_bom(c) for c in df.columns]
    lidas = len(df)

    faltando = [c for c in fonte.COLUNAS if c not in df.columns]
    if faltando:
        raise KeyError(
            f"[{fonte.NOME}] schema drift: missing {faltando}. "
            f"Present: {list(df.columns)[:12]}"
        )

    df = df[list(fonte.COLUNAS)].rename(columns=fonte.COLUNAS)
    descartadas: dict[str, int] = {}

    def cortar(mask: pd.Series, motivo: str) -> None:
        nonlocal df
        n = int(mask.sum())
        if n:
            descartadas[motivo] = descartadas.get(motivo, 0) + n
            df = df[~mask]

    if "uf" in df.columns:
        cortar(df["uf"].isna() | (df["uf"].astype(str).str.strip() == ""), "uf_vazia")

    if "coletado_em" in df.columns:
        df["coletado_em"] = pd.to_datetime(
            df["coletado_em"], format="%d/%m/%Y", errors="coerce"
        )
        cortar(df["coletado_em"].isna(), "data_invalida")
        df["ano_mes"] = df["coletado_em"].dt.strftime("%Y-%m")

    if getattr(fonte, "PRECO", None) and fonte.PRECO in df.columns:
        df[fonte.PRECO] = para_numero(df[fonte.PRECO])
        cortar(df[fonte.PRECO].isna(), "preco_ilegivel")

    if "produto" in df.columns:
        df["produto"] = df["produto"].astype(str).str.strip().str.upper()

    return Resultado(df.reset_index(drop=True), lidas, descartadas)
