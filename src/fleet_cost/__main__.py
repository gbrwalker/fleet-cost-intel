"""Pipeline entry point.

    python -m fleet_cost                 # full run
    python -m fleet_cost --dry-run       # everything except the write
    python -m fleet_cost --source anp_precos

`--dry-run` is not a convenience flag. In the production system this project
models, a dry run is mandatory before any new load reaches production, because
the expensive part of a pipeline is never the processing — it is the side
effect. Reverting a published file that sixteen dashboards read is manual work,
and visible to everyone who depends on it.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date

from fleet_cost import ingest, normalize, publish, transform, windows
from fleet_cost.quality import QualityGate
from fleet_cost.sources import anp_precos


def rodar_precos(hoje: date, seco: bool) -> int:
    janela = windows.ANP_PRECOS
    inicio = max(janela.start(hoje), date(2023, 1, 1))
    print(f"[anp_precos] window {inicio} .. {hoje} ({janela.days}d)")
    print(f"             reason: {janela.reason}")

    baixados = ingest.baixar(anp_precos.urls(inicio, hoje))
    if not baixados:
        print("             nothing downloaded; nothing to do")
        return 0

    partes = []
    total_lidas = 0
    descartes: dict[str, int] = {}
    for b in baixados:
        r = normalize.normalizar(ingest.ler(b.caminho), anp_precos)
        print(r.relatorio())
        total_lidas += r.lidas
        for k, v in r.descartadas.items():
            descartes[k] = descartes.get(k, 0) + v
        partes.append(r.df)

    import pandas as pd
    bruto = pd.concat(partes, ignore_index=True)
    frota = bruto[bruto["produto"].isin(anp_precos.PRODUTOS_FROTA)]
    print(f"    {len(frota)} fleet-fuel rows of {len(bruto)} total")

    precos = transform.precos_por_uf(frota)
    consumo = transform.carregar_consumo()
    custo = transform.custo_por_km(precos, consumo)
    final = transform.contra_piso(custo, transform.carregar_piso())

    taxa = sum(descartes.values()) / max(total_lidas, 1)
    print(f"    discard rate {taxa:.2%} — {descartes or 'none'}")

    if seco:
        print("    [DRY RUN] gates would run; nothing written")
        publish.quality.validate(precos, publish.anterior("precos_por_uf"),
                                 "precos_por_uf", key_column="uf",
                                 price_column="preco_medio")
        print("    [DRY RUN] gates passed")
        return 0

    publish.publicar(precos, "precos_por_uf", key_column="uf",
                     price_column="preco_medio", period_column="ano_mes")
    publish.publicar(final, "custo_por_km", key_column="uf")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="fleet_cost")
    ap.add_argument("--dry-run", action="store_true",
                    help="run everything except the write")
    ap.add_argument("--source", default="anp_precos",
                    choices=["anp_precos"],
                    help="anp_vendas is specced but its URL is unverified")
    ap.add_argument("--today", default=None, help="YYYY-MM-DD, for tests")
    a = ap.parse_args(argv)

    hoje = date.fromisoformat(a.today) if a.today else date.today()
    try:
        return rodar_precos(hoje, a.dry_run)
    except QualityGate as e:
        print(f"\nQUALITY GATE: {e}", file=sys.stderr)
        print("Nothing was written. The previous publication is intact.",
              file=sys.stderr)
        return 2
    except KeyError as e:
        print(f"\nSCHEMA DRIFT: {e}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
