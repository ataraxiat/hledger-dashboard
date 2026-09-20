---
type: object
universe: live
status: verified
verified: 2026-09-20
branch: chore/accounting-dir
cluster: callbacks
source: app.py
---

# Refresh — `refresh()`

The one callback that rebuilds the whole dashboard from the journal. Eleven
outputs, five states, eleven hledger invocations.

## Why this shape

One callback rather than one per graph, because every figure is scoped by the
same period and depth and splitting them would mean eleven callbacks each
re-deriving the same `period_args` — and, on a large journal, eleven
independent chances to show two charts from two different periods.

It is `prevent_initial_call=True` on purpose: the page must render instantly
with empty-state figures, and querying a journal is not instant. Nothing runs
until the user presses Refresh.

The first thing it does is refuse `--end` without `--begin`. hledger will
happily answer that query with cumulative balances from ledger start, folding
opening balances into the Sankey and producing a chart that is wrong without
looking wrong. Returning `no_update` for every figure and an explanatory string
in the status log is the safer answer.

## Shape

| Field / element | Constraint | Cite |
|---|---|---|
| trigger | `refresh-btn.n_clicks`, `prevent_initial_call=True` | `app.py#refresh` |
| states | period, depth, begin, end, measured width | `app.py#refresh` |
| outputs | 5 figures, 1 style, 3 stores, the status log and its style | `app.py#refresh` |
| the guardrail | `end` without `begin` → all `no_update` plus an error message | `app.py#refresh` |
| queries per run | 4 balance, 4 monthly, 1 weekly, 1 register, plus `print` for `"from"` | `app.py#run_hledger` |

## Connected to

- **owns** — a complete redraw.
- **owned by** — [periods](../queries/periods.md) for scoping, and every card
  in `queries/` and `figures/` for the work itself.
- **looks like but is not** — [import-run](../import-pipeline/import-run.md).
  `_stream_import` performs the *same* redraw and does **not** call this
  function. See below.

## If you change this

**Hits**
- `_stream_import`, always. It holds a second, hand-maintained copy of this
  function's entire query-and-build sequence, and a change made here and not
  there means the post-import charts disagree with the post-refresh ones — `app.py#_stream_import`
- The three data stores it writes, and therefore every callback that reads
  them — `app.py#update_strip_plot`, `app.py#handle_tx_popup`
- `poll_import`, whose output list mirrors this one so the two can write the
  same components — `app.py#poll_import`

**Does not hit**
- `CFG` or `config.json`. Refresh reads the account names and never writes
  them — `app.py#save_settings`
- The journal. Every command it issues is a read; nothing here can modify the
  ledger — `app.py#hledger_cmd`

## Surfaces

| Who | Reads | Writes |
|---|---|---|
| humans | press Refresh | — |
| hledger | the journal, read-only | — |
| the browser | 5 figures, 3 stores, the log | — |
| tests | none | — |

## See

- `app.py` — the callback registration at line 2698 and the function below it.
