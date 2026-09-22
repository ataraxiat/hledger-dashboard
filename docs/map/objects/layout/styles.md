---
type: object
universe: live
status: verified
verified: 2026-09-20
branch: chore/accounting-dir
cluster: layout
source: app.py
---

# The styles — the `STYLE_*` dicts and `assets/dashboard.css`

Inline style dictionaries composed by spread (`{**STYLE_BTN_WARN, ...}`), plus
one stylesheet Dash loads automatically from `assets/`.

## Why this shape

Dash has two styling surfaces and this app uses both, for different reasons.
Inline dicts are what a callback can *return* — `save_settings` and the depth
buttons swap styles to show selection, and that is only possible for a style
that is a value rather than a class. The stylesheet covers what inline styles
cannot reach: pseudo-selectors, scrollbars, and the internals of Dash's own
components.

The variants compose rather than repeat: `STYLE_BTN_SMALL_WARN` is
`{**STYLE_BTN_WARN, ...}` with two overrides, `STYLE_ERROR` is `STYLE_STATUS`
with a red border. Editing a base dict moves every variant built from it, which
is the point and also the trap.

## Shape

| Field / element | Constraint | Cite |
|---|---|---|
| `STYLE_PAGE`, `STYLE_CARD` | page and panel backgrounds | `app.py#STYLE_PAGE`, `app.py#STYLE_CARD` |
| button family | `STYLE_BTN_PRIMARY`, `_WARN`, `_SMALL_WARN`, `_NEUTRAL` | `app.py#STYLE_BTN_PRIMARY`, `app.py#STYLE_BTN_WARN`, `app.py#STYLE_BTN_SMALL_WARN`, `app.py#STYLE_BTN_NEUTRAL` |
| `STYLE_STATUS` / `STYLE_ERROR` | the log panel; error is the same dict with a red border | `app.py#STYLE_STATUS`, `app.py#STYLE_ERROR` |
| `STYLE_VIOLIN_TOOLTIP` | the custom hover div the clientside JS positions | `app.py#STYLE_VIOLIN_TOOLTIP` |
| tab styles | returned by two helper functions, not constants | `app.py#_tab_style`, `app.py#_tab_selected_style` |
| dynamic styles | depth and bool buttons, rebuilt per selection | `app.py#_depth_btn_styles`, `app.py#_bool_btn_styles` |
| the stylesheet | auto-loaded by Dash from `assets/` | `assets/dashboard.css` |

## Connected to

- **owns** — nothing.
- **owned by** — [figure-chrome](../figures/figure-chrome.md) in spirit only:
  both read `FONT_COLOR`, `BG`, `CARD_BG` and `BORDER`, which is the only place
  the two palettes actually meet.
- **looks like but is not** — [figure-chrome](../figures/figure-chrome.md).
  These style HTML components; that styles Plotly figures. Neither can restyle
  the other's surface.

## If you change this

**Hits**
- Every variant spread from the dict you edited — `app.py#STYLE_BTN_SMALL_WARN`
- The layout, which applies them at construction — `app.py:1646-2560`
- `save_settings` and the button-state helpers, which return styles as callback
  outputs — `app.py#save_settings`, `app.py#_depth_btn_styles`
- The violin tooltip's JS, which positions a div this dict styles — `app.py:2594-2700`

**Does not hit**
- Any figure. Plotly draws to SVG/canvas and reads none of these — `app.py#dark_layout`
- Any query, store or callback wiring. Style is returned as a value and changes
  nothing about what runs — `app.py#refresh`

## Surfaces

| Who | Reads | Writes |
|---|---|---|
| the layout | all of them | — |
| the browser | `assets/dashboard.css` | — |
| a handful of callbacks | — | style props |
| humans | the visual result | — |
| tests | none | — |

## See

- `app.py` — lines 1490 to 1596 hold the constants and the tab helpers.
