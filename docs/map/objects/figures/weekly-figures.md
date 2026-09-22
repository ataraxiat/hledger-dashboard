---
type: object
universe: live
status: verified
verified: 2026-09-20
branch: chore/accounting-dir
cluster: figures
source: app.py
---

# The weekly figures — small multiples, heatmap, violin strip

Three separate views of the **same** weekly dict: one panel per expense
sub-category, the same categories as heatmap rows, and the same categories as
violin traces. `build_strip_figure` alone is 324 lines.

## Why this shape

One query feeds all three. `refresh` runs `run_hledger_weekly` once, parses it
once, and stores the result in `strip-data-store`; the three builders are pure
functions of that dict. That is what lets the orientation toggle, the scale
cycle and the legend filter redraw the violin plot without touching hledger at
all.

Every one of them writes the original `YYYY-MM-DD` week date into the trace —
`customdata` on the bars, `customtext` on the heatmap. That is the whole
mechanism behind the click-through: a clicked point has to carry enough to
rebuild a register query, and a display label like `25-W14` does not.

The violin's three scale modes exist because weekly category spend spans
orders of magnitude. `transform` (a symmetric power transform, POWER=0.3) and
`log` both suppress the box-stats hover on purpose — the native Plotly tooltip
would report *transformed* numbers, which are meaningless to a reader. That
suppression is the reason a clientside callback exists at all.

## Shape

| Field / element | Constraint | Cite |
|---|---|---|
| `build_small_multiples_figure(weekly_data, label, plot_w)` | one panel per category; dashed period-average line; returns `(fig, style)` | `app.py#build_small_multiples_figure` |
| `build_heatmap_figure(weekly_data, label)` | categories as rows, sorted by average descending | `app.py#build_heatmap_figure` |
| `build_strip_figure(weekly_data, label, orientation, scale_mode, hidden_parents)` | violin + box + mean line + points | `app.py#build_strip_figure` |
| scale modes | `"transform"` (POWER 0.3), `"log"`, `"linear"` | `app.py#build_strip_figure` |
| the click payload | original week date, as `customdata` / `customtext` | `app.py#build_small_multiples_figure` |
| empty states | one per figure | `app.py#empty_sm_figure`, `app.py#empty_hm_figure`, `app.py#empty_strip_figure` |

## Connected to

- **owns** — `sm-graph`, `hm-graph` and `strip-graph`.
- **owned by** — [ledger-frames](../queries/ledger-frames.md); the weekly dict
  is `parse_weekly_data`'s output and nothing else.
- **looks like but is not** — [monthly-bar](monthly-bar.md). Monthly comes from
  a `--monthly` balance query and shares no code with these.

## If you change this

**Hits**
- `refresh`, which builds all three — `app.py#refresh`
- `_stream_import`, which builds all three again in its own copy — `app.py#_stream_import`
- `update_sm_on_resize` and `update_strip_plot`, which rebuild from the store
  without re-querying — `app.py#update_sm_on_resize`, `app.py#update_strip_plot`
- `handle_tx_popup`, which reads the clicked point's `customdata` to resolve a
  week — `app.py#handle_tx_popup`
- The violin hover JS, which re-attaches handlers whenever the strip figure or
  scale mode changes — `app.py:2547-2653`

**Does not hit**
- `hledger_cmd` or the runners. All three are pure functions of an
  already-fetched dict; redrawing never touches the journal — `app.py#run_hledger_weekly`
- The Sankey and the monthly bar, which live on a different tab and read
  different data — `app.py#build_sankey`

## Surfaces

| Who | Reads | Writes |
|---|---|---|
| `refresh`, `_stream_import` | build all three | three figures + `strip-data-store` |
| the weekly-interaction callbacks | rebuild the strip and small multiples | — |
| the browser | `clickData` on all three | — |
| humans | the weekly tab | — |
| tests | none | — |

## See

- `app.py` — lines 922 to 1478 hold all three builders.
