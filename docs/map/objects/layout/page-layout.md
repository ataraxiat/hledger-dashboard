---
type: object
universe: live
status: verified
verified: 2026-09-20
branch: chore/accounting-dir
cluster: layout
source: app.py
---

# The page — `app.layout`

One `html.Div` spanning roughly 900 lines and holding every component id in
the app: the control bar, three tabs of graphs, four modals, the status log
and the nine stores.

## Why this shape

Dash resolves callbacks by component id against a single layout tree, so every
id a callback names must exist here or the app raises at startup. A tabbed
single layout — rather than a multi-page app with a router — means all three
tabs' graphs are always present in the tree, which is what lets one `refresh`
callback write all five figures in one pass.

Every graph is seeded with an empty-state figure at construction rather than
left `None`, so the page renders and explains itself before anything has been
clicked.

## Shape

| Field / element | Constraint | Cite |
|---|---|---|
| `app.layout` | a single `html.Div`; ~55 ids | `app.py:1646-2560` |
| graphs | `sankey-graph`, `bar-graph`, `sm-graph`, `hm-graph`, `strip-graph` | `app.py:1646-2560` |
| modals | `tx-modal`, `import-source-modal`, `bank-nav-modal`, `settings-modal` | `app.py:1646-2560` |
| controls | `period-dd`, `depth-dd`, `begin-dp`, `end-dp`, `refresh-btn`, `import-btn` | `app.py:1646-2560` |
| stores | nine of them | `app.py:2050-2058` |
| the poll timer | `import-poll`, an interval component, disabled until an import starts | `app.py:2059` |

This card carries a **line range, not a symbol**. `app.layout` is an attribute
assignment and has no anchor a checker can resolve, so this range will drift as
code above it moves. Treat it as approximate and re-verify it with
`/icm-map:map-verify` rather than trusting the numbers.

## Connected to

- **owns** — [stores](stores.md) and every component id.
- **owned by** — [styles](styles.md), which supplies the `STYLE_*` dicts it
  applies, and [figure-chrome](../figures/figure-chrome.md), which supplies the
  empty figures it seeds.
- **looks like but is not** — the callbacks. An id existing here does not mean
  anything listens to it; the callback decorators below are the wiring.

## If you change this

**Hits**
- Any callback naming a renamed or removed id — Dash raises at import, not at
  click time — `app.py#refresh`
- The three clientside callbacks, which look up `sm-graph` by id in the DOM — `app.py:2565-2593`
- `assets/dashboard.css`, which targets classes and ids set here — `assets/dashboard.css`

**Does not hit**
- Any query or figure builder. They take arguments and return figures; none of
  them knows a component id — `app.py#build_sankey`
- `CFG`. The layout reads config values for its *initial* widget values only,
  and does not write any — `app.py#CFG`

## Surfaces

| Who | Reads | Writes |
|---|---|---|
| Dash | the whole tree, at import | the served page |
| every callback | ids from here | component props |
| the browser | the rendered DOM | `clickData`, input values |
| humans | the page | — |
| tests | none | — |

## See

- `app.py` — the assignment beginning at line 1599.
