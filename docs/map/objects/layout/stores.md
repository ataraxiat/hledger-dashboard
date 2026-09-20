---
type: object
universe: live
status: verified
verified: 2026-09-20
branch: chore/accounting-dir
cluster: layout
source: app.py
---

# The stores — nine `dcc.Store` components

Browser-side state that outlives a single callback: the fetched weekly and
register data, and seven small UI flags.

## Why this shape

The server process holds no per-session state. Every `dcc.Store` lives in the
user's browser, which is what makes the expensive queries pay off exactly once:
`refresh` fetches the weekly dict and the full register list, drops them into
`strip-data-store` and `register-data-store`, and every later interaction —
toggling orientation, cycling the scale, filtering the legend, clicking a week
for its transactions — is served from those without touching hledger again.

`register-data-store` in particular is the reason the drill-down is instant: it
holds *all* register rows for the period, and `filter_register_data` narrows
them to a 7-day window in Python rather than running a new query per click.

## Shape

| Field / element | Constraint | Cite |
|---|---|---|
| `strip-data-store` | the weekly dict; read by three figures and the popup | `app.py:2006` |
| `register-data-store` | `{txns, cmd}` — every register row for the period | `app.py:2007` |
| `strip-orientation` | `"v"` or `"h"` | `app.py:2004` |
| `violin-scale` | `"linear"`, `"log"` or `"transform"` | `app.py:2005` |
| `strip-legend-meta`, `strip-parent-filter` | legend state and hidden categories | `app.py:2008-2009` |
| `sm-width-store`, `sm-period-label-store` | measured pixel width and the period label | `app.py:2010-2011` |
| `clear-signal` | a counter used to reset the date pickers | `app.py:2003` |

All nine are declared in one block. The two data stores are written only by
`refresh` and `poll_import`; the seven flags are written by their own toggles.

## Connected to

- **owns** — nothing.
- **owned by** — [page-layout](page-layout.md), which declares them.
- **looks like but is not** — `CFG`. `CFG` is *server* state shared by every
  browser session; these are *per-browser* and never reach the server except as
  callback arguments — `app.py#CFG`

## If you change this

**Hits**
- `refresh` and `poll_import`, the only two writers of the data stores — `app.py#refresh`, `app.py#poll_import`
- All four weekly-interaction callbacks, which read them — `app.py#update_strip_plot`
- `handle_tx_popup`, which takes both data stores as `State` — `app.py#handle_tx_popup`
- The width-measuring clientside callback, which sets `sm-width-store` from JS — `app.py:2529-2546`

**Does not hit**
- The journal. Nothing in a store is persisted anywhere; a page reload empties
  all nine — `app.py#JOURNAL`
- `config.json`. UI flags here are per-session and are not the same thing as
  the saved defaults — `app.py#_SETTINGS_DISK_KEYS`

## Surfaces

| Who | Reads | Writes |
|---|---|---|
| the browser | holds all nine | — |
| `refresh`, `poll_import` | — | the two data stores |
| the toggles | — | the seven flags |
| humans | never directly | — |
| tests | none | — |

## See

- `app.py` — the `dcc.Store` block at lines 2003 to 2011.
