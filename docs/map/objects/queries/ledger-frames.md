---
type: object
universe: live
status: verified
verified: 2026-09-20
branch: chore/accounting-dir
cluster: queries
source: app.py
---

# The ledger frames — the shapes hledger CSV is normalised into

Six pure functions that turn hledger's CSV into the three shapes the rest of
the app actually consumes: an `account`/`amount` frame, a weekly dict, and a
list of transaction dicts.

## Why this shape

hledger reports balances with the sign convention of double-entry bookkeeping,
where income is negative. Charts want income positive. Rather than sprinkling
sign flips through the figure builders, `normalise(df, flip_sign=True)` does it
once at the boundary, and every builder downstream can assume a positive
number means "more of this thing".

`week_col_to_date` is bidirectional for a related reason: hledger emits weekly
columns as `YYYY-Www`, the axis wants `YY-Www`, and the drill-down needs
`YYYY-MM-DD` to build a register query. One function with a flag keeps the two
conversions from drifting apart, which is exactly what a click-through that
lands on the wrong week would look like.

## Shape

| Field / element | Constraint | Cite |
|---|---|---|
| `parse_amount(raw)` | currency string → float; returns 0.0 on anything unparseable | `app.py#parse_amount` |
| `normalise(df, flip_sign)` | → columns `account`, `amount`; `flip_sign=True` for income | `app.py#normalise` |
| `week_col_to_date(col, to_iso)` | `YYYY-Www` ⇄ `YYYY-MM-DD` ⇄ `YY-Www`; ISO week Monday | `app.py#week_col_to_date` |
| `parse_weekly_data(df)` | → `{account: {weeks, week_dates, amounts, average}}` | `app.py#parse_weekly_data` |
| `filter_register_data(txns, account, week_date)` | prefix match on account, `[week_start, +7d)` | `app.py#filter_register_data` |
| `pivot_monthly(df, flip)` | monthly `bal` frame → a `pd.Series` indexed by month | `app.py#pivot_monthly` |

`weeks` is for display and `week_dates` is for querying. They are parallel
lists of the same length and must stay that way.

## Connected to

- **owns** — the weekly dict, which is what `strip-data-store` holds and what
  three separate figures read
- **owned by** — [hledger-runners](hledger-runners.md), which produce the raw
  frames these consume
- **looks like but is not** — [periods](periods.md). Periods decide *which*
  rows hledger returns; these decide what those rows become.

## If you change this

**Hits**
- All three weekly figures, which read the weekly dict directly — `app.py#build_small_multiples_figure`, `app.py#build_heatmap_figure`, `app.py#build_strip_figure`
- The transaction drill-down, which matches a clicked point's `week_dates`
  entry against the register store — `app.py#handle_tx_popup`
- The Sankey and the monthly bar, both of which consume `normalise` output — `app.py#build_sankey`, `app.py#pivot_monthly`
- `strip-data-store` and `register-data-store`, whose contents are these
  shapes serialised to the browser — `app.py:2006-2007`

**Does not hit**
- `hledger_cmd`. Changing a shape does not change what is asked for; the argv
  is decided before any of this runs — `app.py#hledger_cmd`
- The import pipeline's txcat step, which produces CSV for hledger to ingest
  and never meets these functions — `app.py#_stream_import`

## Surfaces

| Who | Reads | Writes |
|---|---|---|
| every figure builder | these shapes | — |
| the browser | the weekly dict and register list, via `dcc.Store` | — |
| humans | never directly | — |
| tests | none | — |

## See

- `app.py` — lines 169 to 560 hold five of the six. `pivot_monthly` is the
  outlier, at 816 to 820, next to the chart that consumes it.
