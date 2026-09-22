---
type: object
universe: live
status: verified
verified: 2026-09-20
branch: chore/accounting-dir
cluster: callbacks
source: app.py
---

# The transaction drill-down — `handle_tx_popup()`, `render_tx_table()`

Click a week on any of the three weekly graphs and get that week's
transactions for that category, in a modal, without a new query.

## Why this shape

The register rows are already in the browser. `refresh` fetches *every*
register row for the period into `register-data-store`, so a click resolves to
a 7-day Python filter rather than a subprocess — which is what makes the popup
feel instant and what makes clicking around a heatmap bearable.

It could not work from display labels. A heatmap cell knows it is `25-W14`;
turning that back into a date range is lossy. So each figure writes the
original `YYYY-MM-DD` into the trace (`customdata` on bars, `customtext` on the
heatmap) and this callback reads it back. The two halves of that contract are
in different clusters and nothing enforces their agreement.

One callback serves all three graphs plus the close button and the backdrop,
because Dash cannot have two callbacks writing the same output and all five
inputs write the same modal.

## Shape

| Field / element | Constraint | Cite |
|---|---|---|
| inputs | `clickData` on `sm-graph`, `hm-graph`, `strip-graph`, plus close and backdrop | `app.py#handle_tx_popup` |
| states | `strip-data-store`, `register-data-store` | `app.py#handle_tx_popup` |
| the filter | account prefix match + `[week_start, week_start+7d)` | `app.py#filter_register_data` |
| the renderer | a styled `html.Div` table; handles the empty case | `app.py#render_tx_table` |
| outputs | modal style, title, the command string, the table | `app.py#handle_tx_popup` |

## Connected to

- **owns** — `tx-modal` and its contents.
- **owned by** — [stores](../layout/stores.md) for its data, and
  [weekly-figures](../figures/weekly-figures.md) for the click payload.
- **looks like but is not** — [shell-console](shell-console.md). That runs a
  real hledger command on demand; this one only shows the command string
  `refresh` already recorded, and queries nothing.

## If you change this

**Hits**
- `filter_register_data`, its only filtering helper — `app.py#filter_register_data`
- The `customdata` / `customtext` contract in all three weekly builders — `app.py#build_small_multiples_figure`, `app.py#build_heatmap_figure`, `app.py#build_strip_figure`
- `register-data-store`'s `{txns, cmd}` shape — `app.py:2054`

**Does not hit**
- hledger. No command is run here; the string shown in the modal came from the
  register query `refresh` already made — `app.py#run_hledger_register_full`
- The figures themselves. Opening or closing the modal writes no figure
  output, so the underlying charts do not redraw — `app.py#refresh`

## Surfaces

| Who | Reads | Writes |
|---|---|---|
| humans | click a week | — |
| the browser | the two data stores | the modal |
| hledger | nothing | — |
| tests | none | — |

## See

- `app.py` — the callback at line 3043; the table renderer at 563.
