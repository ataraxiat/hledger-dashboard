---
type: object
universe: live
status: verified
verified: 2026-09-20
branch: chore/accounting-dir
cluster: figures
source: app.py
---

# The figure chrome — `dark_layout()`, the palette, the empty-state family

The shared Plotly layout every figure is built on, the colour constants the
traces draw from, and the six placeholder figures shown when there is no data.

## Why this shape

`dark_layout` is the single place background, font and margins are decided, so
a figure that skips it is visibly a different app. It takes `**kwargs` and
passes them straight to `go.Layout`, which is why a caller can add axes or a
legend without a wrapper per chart type.

The empty-state figures are real `go.Figure` objects carrying a centred
annotation, not `None` and not an exception. Every failure path in this app —
hledger missing, journal empty, a builder raising — resolves to one of these,
so the page always renders something with a message on it. That is a deliberate
trade: a dashboard that silently shows a blank panel is worse than one that
says why.

Colours are split into node colours (`COLOR_*`, opacity 0.95) and link colours
(`LINK_*`, opacity 0.35) because a Sankey needs the ribbons to read as
translucent against the nodes they join. `PARENT_CATEGORY_COLORS` is a separate
cycling list used to colour weekly categories.

## Shape

| Field / element | Constraint | Cite |
|---|---|---|
| `dark_layout(title, height, autosize, **kwargs)` | background `BG`, font `FONT_COLOR`, fixed margins | `app.py#dark_layout` |
| `BG`, `CARD_BG`, `BORDER`, `FONT_COLOR` | the dark theme's four base values | `app.py#BG` |
| `COLOR_*` / `LINK_*` | node colours at 0.95 alpha, link colours at 0.35 | `app.py#COLOR_INCOME` |
| `PARENT_CATEGORY_COLORS` | cycled per weekly category | `app.py#PARENT_CATEGORY_COLORS` |
| empty states | six of them, one per graph | `app.py#empty_sankey_figure`, `app.py#empty_bar_figure`, `app.py#empty_sm_figure`, `app.py#empty_hm_figure`, `app.py#empty_strip_figure`, `app.py#_weekly_empty` |
| weekly font sizes | four constants, used only by the weekly builders | `app.py#WEEKLY_TITLE_FONT` |

## Connected to

- **owns** — nothing; it is consumed by every figure builder.
- **owned by** — nothing.
- **looks like but is not** — [styles](../layout/styles.md). Those are CSS
  dicts for Dash HTML components; these are Plotly figure properties. Changing
  `BG` here does not restyle a button, and changing `STYLE_CARD` does not
  restyle a chart — the two palettes are kept in sync by hand.

## If you change this

**Hits**
- Every figure builder, all six of which call `dark_layout` directly or via an
  empty state — `app.py#build_sankey`, `app.py#build_monthly_bar_figure`, `app.py#build_strip_figure`
- The initial page render, which seeds every graph with an empty figure before
  any refresh happens — `app.py:1646-2560`

**Does not hit**
- `assets/dashboard.css`. Plotly figures are canvas/SVG and are not styled by
  the stylesheet; the two are separate surfaces — `assets/dashboard.css`
- Any query or store. Chrome is presentation only — `app.py#run_hledger`

## Surfaces

| Who | Reads | Writes |
|---|---|---|
| every figure builder | `dark_layout`, the palette | — |
| the layout | the empty-state figures, at first render | — |
| humans | the visual result | — |
| tests | none | — |

## See

- `app.py` — lines 116 to 163 hold the palette; `dark_layout` is at 773 to 785
  and the empty-state family is spread over 788 to 916, with the monthly-bar
  builders interleaved between them.
