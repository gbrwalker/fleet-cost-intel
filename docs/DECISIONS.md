# Decisions

Dated, with the trade-off each one cost. A decision without its downside is
marketing, not a record.

---

## 2026-08-26 — State lives in the repository, not in a database

Published output is versioned as Parquet under `data/published/`, and Git
history is the data's history.

**Why.** Someone can clone and run this. No Postgres to provision, no
credentials, no `docker compose up` that fails on their machine. And the Git
diff is an audit log for free — you can see exactly which run changed which
number.

**Cost.** It does not scale. Past a few million rows the repo bloats and
cloning gets slow. This project never gets there: the universe is 27 states ×
~72 months × 3 products. If it did scale, output would move to object storage
and the repo would keep only the manifest. **The decision is right for this
size**, and saying so beats pretending it is universal.

---

## 2026-08-26 — Retroactive window per source, never global

`anp_precos` looks back 200 days; `anp_vendas` looks back 70.

**Why.** The sources lie in different ways. ANP rewrites the file for the
current semester on every weekly publication, so a week already ingested can
change — anything less than a full semester silently misses revisions. ANP
sales, by contrast, closes month M by the end of M+1; re-reading beyond that is
wasted bandwidth on data that is final.

**Cost.** More configuration, more surface to get wrong. Paid for with a test
per source pinning the window arithmetic (`test_ingest_windows.py`). What does
NOT get paid for is the alternative: one global window is waste on one source
and data loss on another, and that combination is hard to diagnose because the
symptom appears far from the cause.

---

## 2026-08-26 — Quality gates abort; there is no "publish with a warning" mode

When a gate fails, the process raises and writes nothing. The previous file
survives.

**Why.** Bad data published is worse than stale data. Whoever consumes the
output does not see the warning — they see the number. A source that is down
and answers `200` with an empty body is a Tuesday, not a hypothesis.

**Cost.** A false positive freezes the data until a human looks. That is the
right side to err on: **stale data is visibly stale; wrong data looks right.**

---

## 2026-08-26 — Station-level detail is dropped and never republished

The raw ANP file identifies every filling station by CNPJ, street address,
number, neighbourhood and postcode. `normalize` keeps only region, state,
municipality, product, date and price.

**Why.** This repository is public. Aggregating to state level is a modelling
choice that happens to also be the privacy-safe one, and the two reinforce each
other — the question being answered is about state-level cost, so nothing of
value is lost.

**Cost.** Municipality-level analysis is off the table without changing this
decision deliberately. `test_normalize.py::test_colunas_identificaveis_sao_descartadas`
asserts a CNPJ from the real file never appears in the output frame, so this
cannot regress quietly.

---

## 2026-08-26 — The ANTT freight floor is a hand-maintained table

Checked on 2026-08-26: ANTT's open data portal carries 106 datasets — RNTRC,
CIOT, multimodal operator — and **none** is the minimum freight floor. It lives
in ANNEX II of resolutions, as PDF, plus an official web calculator.

**Decision.** `reference/piso_antt.csv`, updated by hand when a resolution is
published, carrying the resolution number and date in the file itself.

**Rejected: scraping the resolution PDFs.** It would be the most fragile part
of the project, exercised two or three times a year, and fragile for the wrong
reason — it teaches PDF parsing, not pipelines.

**Cost.** A manual step, and a table that can go stale without anything
failing. Mitigated by carrying the resolution date in the data, so a consumer
can see how old the floor is. **Currently the values are `PLACEHOLDER`** and
must be transcribed from the current resolution before the comparison means
anything.

---

## 2026-08-26 — Fuel consumption is a declared parameter, not a measurement

No reliable public source gives average km/l by vehicle class in Brazil, so
`config/consumo.yaml` holds the value, its stated origin and a sensitivity
range. Output carries the central value **and both ends**.

**Why.** The honest answer when a parameter is an assumption is "cost per km
between X and Y for consumption between A and B" — not a single number that
implies precision nobody has.

**Cost.** Three rows of output per profile instead of one. Worth it: a single
number here would be the weakest claim in the project and the first thing a
reviewer would poke.

---

## 2026-08-26 — Coverage gate starts at 60%, not 35%

**Why.** The private system this project models uses 35 because it carries code
written before its tests existed. Here there is no legacy, and a showcase repo
with a gate looser than the respectable minimum sends the wrong message.

**Rule.** The number goes up as real coverage grows and **never down** without
an entry in this file explaining why.

---

## Open

- `anp_vendas` URL pattern is **unverified** against the live server, unlike
  `anp_precos` whose schema was confirmed by downloading the real 3.8 MB file.
  Implementation task #1, and the fix lands in one place.
- `reference/piso_antt.csv` holds placeholder values.
- The pipeline cron day is a guess with one day of slack; confirm ANP's real
  publication day in the first week and adjust.
- No incident has been recorded yet, which means this has not run long enough
  to prove what it claims. That is a statement about the project's age, not
  its design.
