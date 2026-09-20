---
type: object
universe: live
status: verified
verified: 2026-09-20
branch: chore/accounting-dir
cluster: queries
source: app.py
---

# The period vocabulary — `PERIOD_LABELS`, `_build_period_args()`

How a dropdown value and two date pickers become hledger period flags, plus
the human label that gets stamped on every figure title.

This card deliberately straddles the file: the label table is at line 103, the
translator at 3155, and the date-picker callback at 3168. Someone adding a
period option needs all three.

## Why this shape

Explicit dates beat the named period. `_build_period_args` checks `begin`/`end`
**before** it looks at the dropdown, so setting a date picker silently
overrides the dropdown rather than conflicting with it — there is one answer,
and it is the more specific one.

The `"from"` option is the odd one out: it is not an hledger period name at
all. It runs `hledger print` and takes the *second* transaction date, because
the first entry in this journal sets opening balances and starting there would
double-count them into every chart.

`refresh` refuses `--end` without `--begin` outright rather than passing it
through, because hledger would then return cumulative balances from ledger
start and the Sankey would be quietly wrong.

## Shape

| Field / element | Constraint | Cite |
|---|---|---|
| `PERIOD_LABELS` | 8 dropdown values → human labels | `app.py#PERIOD_LABELS` |
| `_build_period_args(period, begin, end)` | → `(argv_fragment, label)`; dates win over the dropdown | `app.py#_build_period_args` |
| `"from"` | resolves via `get_ledger_start_date()`; falls back to `[], "all time"` | `app.py#get_ledger_start_date` |
| `handle_date_buttons` | clears both pickers, or sets one to today | `app.py#handle_date_buttons` |
| the end-without-begin guard | lives in `refresh`, not here | `app.py#refresh` |

## Connected to

- **owns** — the `period_args` list, threaded into every query in a run
- **owned by** — nothing; the dropdown value comes from the layout.
- **looks like but is not** — the depth selector. Depth is a separate `-N`
  flag chosen by its own widget and is not part of the period.

## If you change this

**Hits**
- `refresh`, which calls it once and passes the result to every query — `app.py#refresh`
- `handle_import_modal`, which calls it to scope the post-import redraw — `app.py#handle_import_modal`
- Every figure title, which interpolates the returned label — `app.py#dark_layout`
- The period dropdown's option list in the layout, which must match the keys — `app.py:1599-2513`

**Does not hit**
- `JOURNAL`. A period narrows what is read out of the journal; it never
  changes which file is read — `app.py#JOURNAL`
- The register drill-down's week filter. That re-filters an already-fetched
  list by a 7-day window in Python, independently of these flags — `app.py#filter_register_data`

## Surfaces

| Who | Reads | Writes |
|---|---|---|
| `refresh`, `handle_import_modal` | the argv fragment and label | — |
| the browser | the dropdown and the two date pickers | — |
| hledger | `--period` / `--begin` / `--end` | — |
| humans | the label, in every chart title | — |
| tests | none | — |

## See

- `app.py` — `_build_period_args` is the one function that owns the precedence.
