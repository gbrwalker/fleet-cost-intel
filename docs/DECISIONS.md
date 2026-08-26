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
failing. Mitigated by carrying the resolution number and date in the data, so a
consumer can see how old the floor is, and by a guard in `carregar_piso()` that
refuses a non-positive CCD — the file shipped with placeholder zeros, and a
zero floor silently turns every margin into the fuel cost with its sign
flipped.

**Filled in on 2026-08-26** from Resolução ANTT nº 6.084/2026 (published
2026-07-17), Table A, general full-load cargo, seven axle configurations.
Transcribed from the official text at anttlegis.antt.gov.br. A widely-cited
blog publishes the same table with four wrong CCD values and a flat CC of
782.50 for every axle count, when the official CC ranges from 451.84 to 903.32
— round numbers sitting beside four-decimal ones was the tell.

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

## 2026-08-26 — ANP's monthly series has real holes, and the gate had to learn the difference

Running the full 200-day window against the live server surfaced something the
documentation does not mention: **2026-04 and 2026-06 are not published**,
while 03, 05 and 07 are. I tried six naming variants for the missing months;
all 404. The files that do exist each cover exactly one month, so this is not a
bimonthly layout — the series is simply incomplete.

**Why this mattered immediately.** The period-gap gate would have aborted every
single run over a hole nobody can fix — the textbook false positive that
freezes data for no reason, which is the cost this project accepted when it
chose aborting over warning. Accepting that cost is only honest if the gate can
tell the two cases apart.

**Decision.** `ingest.baixar` now returns the URLs the source did not publish
alongside what it downloaded, and those months are passed to `gap_check` as
`conhecidos_ausentes`. A gap the SOURCE has is tolerated and printed; a gap a
partial DOWNLOAD created still aborts.

**Also fixed here:** the dry run was only exercising `validate`, not
`gap_check`. A rehearsal that skips half the gates is not a rehearsal — it
would have let this exact gap surprise the first real run.

---

## 2026-08-26 — The floor is not a per-km rate, and modelling it as one was wrong

The first version of `contra_piso()` treated the ANTT floor as a rate per
kilometre. It is not. The regulated formula is:

    floor (R$ per trip) = distance_km * ccd_per_km + cc_fixed

`cc_fixed` covers loading and unloading and is charged **once per trip**, so it
amortises over distance. For a 2-axle vehicle the floor is R$ 8.50/km at 100 km
and R$ 4.43/km at 1000 km — **a factor of two.**

**Decision.** The output carries `distancia_km` on every row, computed at three
reference distances (100, 500, 1000 km). No row states a per-km floor without
saying which distance produced it.

**Cost.** Three times the rows in `custo_por_km` (13,230 instead of 4,410).
Worth it: a single per-km figure with no distance attached would be wrong by up
to a factor of two, in whichever direction the reader happens to assume — and
it would look perfectly reasonable while being wrong.

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
