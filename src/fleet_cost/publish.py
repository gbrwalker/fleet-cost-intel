"""The publication boundary. Validate here, not earlier.

Validating early protects the processing. Validating at the boundary protects
**the consumer**. Only the second one matters when something goes wrong,
because the consumer does not see a warning — they see a number.

Idempotency layer 3 of 3: write to `.tmp` and rename. A run interrupted midway
never leaves a truncated Parquet where a good one used to be.
"""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

from fleet_cost import quality

PUBLICADO = Path("data/published")


def anterior(nome: str) -> pd.DataFrame:
    """Last good publication, or an empty frame on first run."""
    p = PUBLICADO / f"{nome}.parquet"
    if not p.exists():
        return pd.DataFrame()
    try:
        return pd.read_parquet(p)
    except Exception:
        # A previous file that cannot be read is not a reason to skip the
        # gates — it is a reason to treat this as a first run and let the
        # empty-snapshot gate still fire if the new one is bad.
        return pd.DataFrame()


def escrever_atomico(df: pd.DataFrame, destino: Path) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_suffix(destino.suffix + ".tmp")
    df.to_parquet(tmp, index=False)
    os.replace(tmp, destino)


def publicar(df: pd.DataFrame, nome: str, *, key_column: str | None = None,
             price_column: str | None = None,
             period_column: str | None = None) -> Path:
    """Run every gate, then write atomically. Raises QualityGate and writes
    nothing if any gate fails."""
    velho = anterior(nome)
    quality.validate(df, velho, nome,
                     key_column=key_column, price_column=price_column)
    if period_column:
        quality.gap_check(df, period_column, nome)

    destino = PUBLICADO / f"{nome}.parquet"
    escrever_atomico(df, destino)

    delta = len(df) - len(velho) if not velho.empty else len(df)
    print(f"    published {nome}: {len(df)} rows ({delta:+d})")
    return destino
