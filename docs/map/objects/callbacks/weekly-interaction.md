---
type: object
universe: live
status: verified
verified: 2026-09-20
branch: chore/accounting-dir
cluster: callbacks
source: app.py
---

# Weekly interaction — orientation, scale, legend filter, resize

Four callbacks that redraw the weekly tab from data already in the browser.
None of them runs an hledger command.

## Why this shape

`refresh` has already paid for the query and parked the result in
`strip-data-store`. These callbacks are pure re-renders of that dict, which is
why toggling the axis or cycling the scale is instant on a journal where a
refresh takes seconds. Keeping that property is the design constraint: a
"small" change that adds a query to one of these turns a toggle into a wait.

`update_strip_filter` is the subtle one. Plotly reports a legend single-click
as a restyle over one trace index and a double-click as a batch restyle over
*all* traces, so the callback has to distinguish them by shape rather than by
event type — and a second double-click on an isolated parent must restore
everything. That logic has no other home.

`cycle_scale` advances through a fixed three-element list rather than a
dropdown so the button can be a single control that also displays the current
mode.

## Shape

| Field / element | Constraint | Cite |
|---|---|---|
| `toggle_orientation` | flips `strip-orientation` between `"v"` and `"h"` | `app.py#toggle_orientation` |
| `cycle_scale` | `linear → transform → log → linear`, relabelling the button | `app.py#cycle_scale` |
| `update_strip_plot` | rebuilds the violin from the store, the flags and the filter | `app.py#update_strip_plot` |
| `update_strip_filter` | single-click toggles, double-click isolates or restores | `app.py#update_strip_filter` |
| `update_sm_on_resize` | rebuilds small multiples when the measured width changes | `app.py#update_sm_on_resize` |
| `SCALE_LABELS` | the button captions | `app.py#SCALE_LABELS` |

## Connected to

- **owns** — the redrawn `strip-graph` and `sm-graph`.
- **owned by** — [stores](../layout/stores.md); everything they read is a
  store value.
- **looks like but is not** — [refresh](refresh.md). Refresh re-queries the
  journal; these never do.

## If you change this

**Hits**
- `build_strip_figure` and `build_small_multiples_figure`, the only functions
  they call — `app.py#build_strip_figure`, `app.py#build_small_multiples_figure`
- The five stores they read and write — `app.py:2004-2010`
- The violin hover JS, which re-binds whenever the strip figure or scale
  changes — `app.py:2547-2653`

**Does not hit**
- hledger. Adding a query here would be the change that breaks the tab's
  responsiveness — `app.py#run_hledger_weekly`
- The heatmap. It is built only by `refresh` and `_stream_import` and has no
  interaction callback of its own — `app.py#build_heatmap_figure`

## Surfaces

| Who | Reads | Writes |
|---|---|---|
| humans | the toggle buttons and the legend | — |
| the browser | the stores | `strip-graph`, `sm-graph` |
| hledger | nothing | — |
| tests | none | — |

## See

- `app.py` — lines 2675 to 3010 hold all four, plus `handle_date_buttons`.
