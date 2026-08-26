# fleet-cost-intel

**What it costs to run a truck per kilometre in Brazil, by state and by month —
and how that moves against the regulated minimum freight floor.**

A scheduled data pipeline over Brazilian open data. It runs on a cron, alone,
and opens an issue when it breaks.

---

## Why this exists

Most of my production data work is private and cannot be shown. This is the
same engineering, on data that can: two public sources that mutate in different
ways, which is what forces a real idempotency story instead of a
re-run-everything script.

## What it is not

It is not a notebook. The difference is specific, not a matter of
sophistication:

| A course notebook | This |
|---|---|
| runs when someone runs it | runs on a schedule and reports its own failures |
| assumes the source answers | handles outages, schema drift and 404s |
| reprocesses everything, or nothing | a retroactive window sized per source |
| overwrites its output | validates first and **aborts**, preserving the last good file |
| a cell that worked once | tests with a coverage gate in CI |
| `pip install` instructions | architecture decisions with their trade-offs |
| clean data | dirty data handled explicitly, with discards counted |

---

## Run it

```bash
git clone https://github.com/gbrwalker/fleet-cost-intel
cd fleet-cost-intel
pip install -r requirements.txt

python -m fleet_cost --dry-run   # every stage except the write
python -m fleet_cost             # full run
```

No credentials. No database. No container.

`--dry-run` is not a convenience flag — it is mandatory before any new load
reaches production. The expensive part of a pipeline is never the processing,
it is the side effect.

---

## Sources

| Source | Grain | Format | How it mutates |
|---|---|---|---|
| [ANP — fuel price survey](https://www.gov.br/anp/pt-br/centrais-de-conteudo/dados-abertos/serie-historica-de-precos-de-combustiveis) | per station, weekly | CSV, `;`, UTF-8 **with BOM**, comma decimals | the **current semester's file is rewritten** every week |
| [ANP — sales of derivatives](https://www.gov.br/anp/pt-br/centrais-de-conteudo/dados-abertos/vendas-de-derivados-de-petroleo-e-biocombustiveis) | per state, monthly | CSV | month M **closes at the end of M+1** |
| ANTT — minimum freight floor | per axle count | ⚠️ **not open data** | by resolution; see below |

Schema for the price series was verified on 2026-08-26 by downloading the real
3.8 MB file and reading it — not assumed from documentation. Three things in it
break naive parsers, and all three have a test: the BOM, the `;` separator, and
the comma decimal that silently turns `6,79` into `679`.

**The ANTT floor is not published as open data.** Its portal has 106 datasets
and none is the floor; it lives in ANNEX II of resolutions, as PDF. It is kept
here as a hand-maintained reference table. The reasoning, and why scraping the
PDFs was rejected, is in [`docs/DECISIONS.md`](docs/DECISIONS.md).

---

## Architecture

```
ANP Prices (weekly,          ANP Sales (monthly,        reference/
current semester rewritten)  closes a month late)       piso_antt.csv
        │                            │                        │
        └──────────────┬─────────────┘                        │
                       ▼                                      │
   ingest/    download only; SHA-256 vs last run, skip if same │
                       ▼                                      │
   normalize/ explicit column contract; discards COUNTED       │
                       ▼                                      │
   transform/ aggregate to (uf, month, product); cost per km ◄─┘
                       ▼
   publish/   QUALITY GATES → abort and preserve, or write atomically
```

Validation happens at the publication boundary, not earlier. Validating early
protects the processing; validating at the boundary protects **the consumer** —
and only the second one matters when something goes wrong.

### Idempotency, in three layers

1. **Hash at ingestion.** Same SHA-256 as the last run, no reprocessing.
2. **Natural key at transform.** `(uf, ano_mes, produto)` — reprocessing a
   window overwrites exactly those rows and never appends duplicates.
3. **Atomic write at publish.** Write `.tmp`, then rename. An interrupted run
   never leaves a truncated Parquet where a good one was.

Proved in `tests/test_idempotencia.py`, not asserted here.

### Quality gates

Each compares the candidate against the last good publication, and each aborts:

| Gate | Threshold | The failure it catches |
|---|---|---|
| empty snapshot | any | source down, answering 200 with an empty body |
| volume drop | < 50% of previous | partial extraction |
| missing key column | any | upstream schema drift |
| empty keys | > 5% of rows | parsing broken silently |
| price out of range | R$ 0.50–20.00/L | decimal separator read as thousands |
| period gap | any month missing | partial download |

---

## Three decisions, with what each cost

Full record in [`docs/DECISIONS.md`](docs/DECISIONS.md). In short:

1. **State in the repo, not a database** — so anyone can clone and run. Cost: it
   does not scale, and this project is sized so it never needs to.
2. **A retroactive window per source** — because ANP prices and ANP sales mutate
   differently. Cost: more configuration, paid for with a test per source.
3. **Gates abort instead of warning** — because bad data published is worse than
   stale data. Cost: a false positive freezes the data until a human looks.

---

## What is deliberately absent

No Airflow (cron handles two pipelines; an orchestrator here would be résumé,
not architecture). No Docker (adds nothing to an ephemeral runner). No machine
learning (there is no prediction problem here, and adding a model to look
sophisticated is precisely the notebook smell). No hosted dashboard (a service
that goes down makes a portfolio worse than no service).

**Knowing what not to build is part of what this demonstrates.**

---

## Status

Early. Honest list of what is not done yet is at the bottom of
[`docs/DECISIONS.md`](docs/DECISIONS.md) — including that the ANTT reference
table still holds placeholder values, and that no production incident has been
recorded because it has not run long enough to have one.

## Data licence

ANP data is Brazilian federal open data. The pages do not state explicit terms;
source and extraction date are cited in the README and carried in every derived
file.
