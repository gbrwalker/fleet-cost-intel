"""Quality gates. Every one of them ABORTS — none of them warns.

Bad data published is worse than stale data. Whoever consumes the output does
not see a warning, they see a number. A gate that lets the write through with a
log line has already failed at its job.

Thresholds are the ones carried over from the production system this project
models, plus two specific to fuel prices.
"""
from __future__ import annotations

import math

import pandas as pd


class QualityGate(Exception):
    """Raised when a snapshot must not be published. Nothing is written."""


def validate(
    novo: pd.DataFrame,
    anterior: pd.DataFrame,
    nome: str,
    *,
    key_column: str | None = None,
    min_ratio: float = 0.5,
    max_empty_key: float = 0.05,
    price_column: str | None = None,
    price_range: tuple[float, float] = (0.50, 20.00),
) -> None:
    """Compare a candidate snapshot against the last good one. Raise or return.

    Order matters: cheapest checks first, so a totally broken snapshot fails on
    the first gate instead of after a full column scan.
    """
    if novo.empty:
        raise QualityGate(
            f"[{nome}] snapshot is empty; previous file preserved. "
            "A source that is down and answers 200 with an empty body is a "
            "Tuesday, not a hypothesis."
        )

    if not 0 < min_ratio <= 1:
        raise ValueError("min_ratio must be in (0, 1]")

    if not anterior.empty:
        floor = math.ceil(len(anterior) * min_ratio)
        if len(novo) < floor:
            raise QualityGate(
                f"[{nome}] row count fell from {len(anterior)} to {len(novo)} "
                f"(safe floor {floor}); previous file preserved."
            )

    if key_column:
        if key_column not in novo.columns:
            raise QualityGate(
                f"[{nome}] required column {key_column!r} is missing. "
                "This is upstream schema drift, not a bad row."
            )
        empty = novo[key_column].isna() | (
            novo[key_column].astype(str).str.strip() == ""
        )
        share = float(empty.mean())
        if share > max_empty_key:
            raise QualityGate(
                f"[{nome}] {share:.1%} of {key_column!r} is empty "
                f"(limit {max_empty_key:.1%}); parsing is probably broken."
            )

    if price_column and price_column in novo.columns:
        lo, hi = price_range
        precos = pd.to_numeric(novo[price_column], errors="coerce").dropna()
        fora = precos[(precos < lo) | (precos > hi)]
        if len(fora) and len(fora) / max(len(precos), 1) > 0.01:
            raise QualityGate(
                f"[{nome}] {len(fora)} price(s) outside R$ {lo:.2f}–{hi:.2f}; "
                f"min {precos.min():.2f}, max {precos.max():.2f}. "
                "The usual cause is a decimal separator read as a thousands "
                "separator, which turns 6,79 into 679."
            )


def gap_check(df: pd.DataFrame, period_column: str, nome: str) -> None:
    """No month may be missing between the first and last period present."""
    if df.empty or period_column not in df.columns:
        return
    periodos = sorted(set(df[period_column].dropna().astype(str)))
    if len(periodos) < 2:
        return
    esperados = pd.period_range(periodos[0], periodos[-1], freq="M").astype(str)
    faltando = sorted(set(esperados) - set(periodos))
    if faltando:
        raise QualityGate(
            f"[{nome}] missing period(s) inside the window: {faltando}. "
            "A partial download looks exactly like this."
        )
