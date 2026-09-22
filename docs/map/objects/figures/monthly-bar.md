---
type: object
universe: live
status: verified
verified: 2026-09-20
branch: chore/accounting-dir
cluster: figures
source: app.py
---

# The monthly trend — `build_monthly_bar_figure()`

A grouped bar chart of income against expenses by month, with the medical
sub-accounts broken out as their own series.

## Why this shape

It takes four `pd.Series` rather than DataFrames because the only thing it
needs is a month-indexed number per series, and `pivot_monthly` already
produces exactly that. Medical is split out because it is the one category
large and lumpy enough to make a month look anomalous when it is not.

The medical series are optional in practice: the caller substitutes a
zero-filled Series indexed like its parent when the medical query comes back
empty, so the chart keeps its four-series shape rather than changing layout
depending on the journal's contents.

## Shape

| Field / element | Constraint | Cite |
|---|---|---|
| `build_monthly_bar_figure(inc, inc_med, exp, exp_med, label)` | four month-indexed Series plus the period label | `app.py#build_monthly_bar_figure` |
| `pivot_monthly(df, flip)` | the only producer of those Series | `app.py#pivot_monthly` |
| the zero-fill | done by the caller, not here | `app.py#refresh` |
| empty state | `empty_bar_figure`, when either parent query is empty | `app.py#empty_bar_figure` |
| errors | caught by the caller and turned into `empty_bar_figure(str(exc))` | `app.py#refresh` |

## Connected to

- **owns** — the `bar-graph` figure.
- **owned by** — [ledger-frames](../queries/ledger-frames.md), via `pivot_monthly`.
- **looks like but is not** — [weekly-figures](weekly-figures.md). Those read
  the weekly dict from a `--weekly --average` query; this reads a `--monthly`
  balance. Different query, different shape, no shared code.

## If you change this

**Hits**
- `refresh`, which runs four monthly queries to feed it — `app.py#refresh`
- `_stream_import`, which repeats those four queries and this call — `app.py#_stream_import`
- The medical account-name convention: both callers derive the sub-account by
  appending `:medical` to the configured parent — `app.py#_stream_import`

**Does not hit**
- The Sankey. It uses the same `bal` runner but a different period granularity
  and its own builder — `app.py#build_sankey`
- Any store. The bar chart is stateless; nothing about it is kept in a
  `dcc.Store` for a later callback — `app.py:2050-2058`

## Surfaces

| Who | Reads | Writes |
|---|---|---|
| `refresh`, `_stream_import` | call it | `bar-graph.figure` |
| the browser | renders it | — |
| humans | the chart | — |
| tests | none | — |

## See

- `app.py` — lines 816 to 890 hold the pivot and the builder.
