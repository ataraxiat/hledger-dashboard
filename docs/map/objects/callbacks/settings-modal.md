---
type: object
universe: live
status: verified
verified: 2026-09-20
branch: chore/accounting-dir
cluster: callbacks
source: app.py
---

# The settings modal — `handle_settings_modal()`, `save_settings()`

The only writer of `config.json` in this repo, and the only thing that mutates
`CFG` after import.

## Why this shape

`save_settings` does `CFG.update(updates)` before writing to disk, so the
change takes effect in the running process immediately rather than at the next
restart. That is deliberate and has a consequence worth stating plainly: `CFG`
is one module-level dict shared by every browser session, so a save in one tab
silently changes what every other open tab computes on its next callback.

Each field falls back to its current `CFG` value when the widget is empty
(`income or CFG["income_account"]`), so clearing a box cannot blank a setting —
only typing a new value can change one.

The disk write is filtered through `_SETTINGS_DISK_KEYS` rather than dumping
`CFG` whole. That list is a separate literal from `CONFIG_DEFAULTS` and does
not track it: a key added to the defaults and not to this list will work in
memory and vanish on restart.

The three-state buttons (depth 2/3/4, skip-txcat no/yes) keep their selection
in a store and restyle themselves, because Dash has no native segmented
control.

## Shape

| Field / element | Constraint | Cite |
|---|---|---|
| `handle_settings_modal` | opens the modal, populating 18 outputs from `CFG` | `app.py#handle_settings_modal` |
| `save_settings` | `CFG.update`, then writes `_SETTINGS_DISK_KEYS` as JSON | `app.py#save_settings` |
| the mkdir | `CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)` before writing | `app.py#save_settings` |
| `_SETTINGS_DISK_KEYS` | the persisted subset — currently all ten | `app.py#_SETTINGS_DISK_KEYS` |
| `select_depth_btn`, `select_skip_txcat` | segmented-control state | `app.py#select_depth_btn`, `app.py#select_skip_txcat` |
| the button styles | rebuilt per selection | `app.py#_depth_btn_styles`, `app.py#_bool_btn_styles` |

## Connected to

- **owns** — `config.json`, and `CFG` after startup.
- **owned by** — [config-file](../config/config-file.md) for the key set, and
  [accounting-paths](../config/accounting-paths.md) for where the file lands.
- **looks like but is not** — `load_config`. That runs once, at import, and is
  never called again; this is the only path by which the file changes
  thereafter — `app.py#load_config`

## If you change this

**Hits**
- `CONFIG_DEFAULTS` and `_SETTINGS_DISK_KEYS`, which must both gain any new
  key — `app.py#CONFIG_DEFAULTS`, `app.py#_SETTINGS_DISK_KEYS`
- `config.example.json` and the subset test that guards it — `tests/test_paths.py`
- The layout's settings modal, which needs one widget per key — `app.py:1599-2513`
- Its four direct outputs: the depth dropdown, the bank link, and the two
  import button captions — `app.py#save_settings`

**Does not hit**
- `CONFIG_PATH` or `JOURNAL`. Both were computed from the environment at
  import; saving settings cannot move either, and changing `$ACCOUNTING_DIR`
  needs a restart — `app.py#CONFIG_PATH`
- A running import. `_stream_import` reads `CFG` when its thread starts, so a
  save mid-import does not retarget work already in flight — `app.py#_stream_import`

## Surfaces

| Who | Reads | Writes |
|---|---|---|
| humans | the modal | the saved settings |
| the app | `CFG` everywhere | `CFG` and `config.json` |
| other browser tabs | see the mutated `CFG` | — |
| tests | `tests/test_paths.py` asserts the key set | — |

## See

- `app.py` — lines 3261 to 3460 hold the modal, the buttons and the writer.
