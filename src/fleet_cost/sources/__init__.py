"""One module per source. Each declares its own contract."""
from fleet_cost.sources import anp_precos, anp_vendas  # noqa: F401

TODAS = {m.NOME: m for m in (anp_precos, anp_vendas)}
