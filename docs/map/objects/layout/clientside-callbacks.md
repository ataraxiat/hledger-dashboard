---
type: object
universe: live
status: verified
verified: 2026-09-20
branch: chore/accounting-dir
cluster: layout
source: app.py
---

# The clientside callbacks — three JavaScript functions embedded in `app.py`

Three `app.clientside_callback` registrations: a tab-change resize nudge, a
width measurer, and the violin hover handler.

## Why this shape

Each one needs something only the browser has, and a round trip to the server
would be either impossible or visibly slow.

- **The resize nudge** fires a synthetic `window.resize` 60 ms after a tab
  change. Plotly sizes a graph when it is drawn, and a graph inside a hidden
  tab is drawn at zero width; without this it stays collapsed until something
  else resizes the window.
- **The width measurer** reads `sm-graph`'s bounding rect and pushes it into
  `sm-width-store` via `dash_clientside.set_props`. The small-multiples figure
  needs a pixel width to lay out its panels, and the server has no idea how
  wide the viewport is.
- **The violin hover handler** is the price of the transformed axes. On
  `transform` and `log` scales, Plotly's native box-stats tooltip would print
  the transformed numbers; this JS hides it, back-converts through `inv()`, and
  shows a custom div in dollars — while restoring the native tooltip for point
  hovers, where the `hovertemplate` already says the right thing.

## Shape

| Field / element | Constraint | Cite |
|---|---|---|
| tab resize nudge | `Input("tabs","value")` → `_resize-dummy`; 60 ms `setTimeout` | `app.py:2518-2528` |
| width measurer | `Input("sm-graph","id")` → `sm-width-store`; also adds a resize listener | `app.py:2529-2546` |
| violin hover | `Input` on the strip figure and the scale mode | `app.py:2547-2653` |
| `POWER` | `0.3` — duplicated here and in `build_strip_figure` | `app.py#build_strip_figure` |

The power constant exists in **both** the Python builder and this JavaScript.
They are not shared and nothing checks they agree; if one changes and the other
does not, the tooltip reports numbers that do not match the plot.

## Connected to

- **owns** — `sm-width-store`'s value.
- **owned by** — [page-layout](page-layout.md), which declares every id these
  address.
- **looks like but is not** — the server callbacks. These are JavaScript
  strings, never execute in Python, and cannot be unit-tested from pytest.

## If you change this

**Hits**
- `update_sm_on_resize`, which fires whenever `sm-width-store` changes — `app.py#update_sm_on_resize`
- `build_small_multiples_figure`, which takes that width as `plot_w` — `app.py#build_small_multiples_figure`
- The violin tooltip div's style dict — `app.py#STYLE_VIOLIN_TOOLTIP`

**Does not hit**
- Any hledger query. Nothing here reaches the server beyond setting a store — `app.py#hledger_cmd`
- `build_strip_figure`'s own tick labelling. The JS only changes the *hover*;
  the axis ticks are computed in Python — `app.py#build_strip_figure`

## Surfaces

| Who | Reads | Writes |
|---|---|---|
| the browser | runs all three | `sm-width-store`, DOM |
| `update_sm_on_resize` | the width they set | — |
| humans | the hover tooltip | — |
| tests | none — these are JS strings | — |

## See

- `app.py` — lines 2518 to 2653 hold all three registrations.
