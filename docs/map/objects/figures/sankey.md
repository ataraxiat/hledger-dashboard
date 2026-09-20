---
type: object
universe: live
status: verified
verified: 2026-09-20
branch: chore/accounting-dir
cluster: figures
source: app.py
---

# The Sankey — `SankeyBuilder`, `build_sankey()`

An income → savings-and-expenses flow diagram, accumulated node-by-node by a
small builder class and emitted as a Plotly Sankey trace dict.

## Why this shape

Plotly's Sankey wants parallel integer-indexed arrays — `source`, `target`,
`value` — which is a miserable thing to assemble by hand and an easy thing to
get subtly out of alignment. `SankeyBuilder` lets callers speak in account
*names* and interns them to indices behind a dict, so a link can be added
without knowing whether either endpoint already exists.

Two label lists exist on purpose. `node_labels` shows only the last `:`
segment, because a Sankey with `expenses:home:utilities` on every node is
unreadable; `node_full_labels` keeps the full account path and is handed to
Plotly as `customdata` so the hover tooltip still tells the truth.

`link()` drops any value `<= 0` rather than drawing it. A zero-width Sankey
link renders as a visual artifact, and a negative one is a sign error upstream
that should not be silently mirrored.

The debit account is reconciled as a flow, not subtracted: a positive change
becomes "retained in checking" leaving the income total, a negative one becomes
"prior balance" entering it. That is what makes income and outflow balance
when spending exceeded income for the period.

## Shape

| Field / element | Constraint | Cite |
|---|---|---|
| `SankeyBuilder.node(label)` | interns a label, returns its index | `app.py#SankeyBuilder.node` |
| `SankeyBuilder.link(src, tgt, value, color)` | silently drops `value <= 0`; rounds to 2dp | `app.py#SankeyBuilder.link` |
| `node_labels` | last `:` segment only — display | `app.py#SankeyBuilder.node_labels` |
| `node_full_labels` | full account path — hover `customdata` | `app.py#SankeyBuilder.node_full_labels` |
| `to_plotly(node_colors)` | → the `dict(node=..., link=...)` Plotly wants | `app.py#SankeyBuilder.to_plotly` |
| `build_sankey(...)` | takes three normalised frames plus the debit change | `app.py#build_sankey` |

## Connected to

- **owns** — the `sankey-graph` figure.
- **owned by** — [ledger-frames](../queries/ledger-frames.md); it consumes
  `normalise` output and nothing else.
- **looks like but is not** — [figure-chrome](figure-chrome.md). `build_sankey`
  returns a *builder*, not a figure: the caller wraps it in `go.Figure` with
  `dark_layout` itself.

## If you change this

**Hits**
- `refresh`, which wraps the builder and sets the title — `app.py#refresh`
- `_stream_import`'s post-import redraw, which contains a **second copy** of
  that same wrapping — `app.py#_stream_import`
- The empty-state path, chosen when both income and expense frames are empty — `app.py#empty_sankey_figure`

**Does not hit**
- The weekly figures. They read the weekly dict, share no code with this, and
  a Sankey change cannot move them — `app.py#build_small_multiples_figure`
- The transaction drill-down. The Sankey has no `clickData` handler; only the
  three weekly graphs are clickable — `app.py#handle_tx_popup`

## Surfaces

| Who | Reads | Writes |
|---|---|---|
| `refresh`, `_stream_import` | call it | `sankey-graph.figure` |
| the browser | renders the trace, hovers `customdata` | — |
| humans | the diagram | — |
| tests | none | — |

## See

- `app.py` — lines 636 to 772 hold the class and the builder.
