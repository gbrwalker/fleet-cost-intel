"""Retroactive windows, declared per source.

Each source lies in its own way, so each gets its own window. A single global
window is either waste or data loss — and usually both, on different sources,
which makes it hard to diagnose.

This mirrors the production system this project is modeled on, where the
default lookback is 45 days and one dataset uses 15, each with the reason
written next to it.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Window:
    """A retroactive window, with the reason it is that size."""

    source: str
    days: int
    reason: str

    def start(self, today: date) -> date:
        from datetime import timedelta

        return today - timedelta(days=self.days)


# ANP rewrites the file for the CURRENT semester on every weekly publication.
# Re-reading the whole semester is the only way to pick up a revision to a week
# already collected. 200 days covers a full semester plus slack.
ANP_PRECOS = Window(
    source="anp_precos",
    days=200,
    reason=(
        "ANP rewrites the current semester's file on every weekly publication, "
        "so a week already ingested can change. 200 days covers a full semester "
        "plus slack for a late revision crossing the boundary."
    ),
)

# ANP closes sales data for month M by the end of month M+1. Anything older
# than ~70 days is final and re-reading it is wasted bandwidth.
ANP_VENDAS = Window(
    source="anp_vendas",
    days=70,
    reason=(
        "ANP closes month M by the end of M+1. 70 days covers the open month "
        "and the one closing behind it; older data is final."
    ),
)

TODAS = {w.source: w for w in (ANP_PRECOS, ANP_VENDAS)}
