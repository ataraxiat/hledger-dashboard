# hledger-dashboard — Claude Code Notes

## Running the app

```bash
source venv/bin/activate
python app.py [--debug] [--host 127.0.0.1] [--port 8050]
```

The venv is at `./venv/` (not `~/Accounting/cvenv/` — that's txcat's venv). The app makes no hledger calls on startup; the user presses ↻ Refresh to load data.

## Architecture

**Single-file Plotly Dash app** — everything lives in `app.py` (~2970 lines). There is no React, no separate frontend build step, no TypeScript. Dash generates the HTML/JS automatically. The file is organised as:

1. Config + constants (lines 43–127)
2. Data helpers — `run_hledger()`, `parse_weekly_data()`, etc. (lines 129–575)
3. Sankey builder class `SankeyBuilder` (lines 580–712)
4. Plotly figure builders — `build_sankey()`, `build_small_multiples_figure()`, etc. (lines 714–1335)
5. Dash app + layout (lines 1338–2184)
6. Callbacks (lines 2186–2965)
7. Entry point (lines 2966+)

## Config

`config.json` is loaded at startup into the module-level `CFG` dict. Defaults live in `CONFIG_DEFAULTS`. The settings modal (⚙ button) writes directly to `config.json` and mutates `CFG` in place — no restart needed for most settings.

Keys in `config.json`:

| Key | Purpose |
|---|---|
| `income_account` | Top-level income account prefix |
| `expenses_account` | Top-level expenses account prefix |
| `savings_account` | Savings account (used in Sankey) |
| `debit_account` | Checking/debit account (used in Sankey reconciliation) |
| `bank_url` | URL opened by the "no new transactions" overlay |
| `hledger_rules_debit` | Path to `.csv.rules` for hledger import — debit account |
| `hledger_rules_savings` | Path to `.csv.rules` for hledger import — savings account |
| `txcat_dir` | Directory containing `txcat.py` |
| `txcat_python` | Python interpreter for txcat (its own venv) |
| `default_depth` | Default value for the account depth dropdown (2, 3, or 4) |

Backwards compat: if `config.json` has the old key `"hledger_rules"`, `load_config()` renames it to `"hledger_rules_debit"` automatically.

## Import pipeline

The ⟳ Import button opens an account selection modal (debit or savings). Clicking an account runs `_stream_import()` in a background thread. That function:

1. Runs `txcat.py auto --source <debit|savings>` then `hledger import <rules_file>`
2. Reads stdout/stderr line by line via `subprocess.Popen` and pushes each line to the `status-log` component using `dash.set_props()` (requires Dash ≥ 2.9; pinned to ≥ 2.17 in `requirements.txt`)
3. Detects "no new transactions" by scanning output for known marker strings
4. After both subprocesses finish, runs all hledger data queries and pushes updated figures to all graph components via `set_props()`
5. If no new transactions and `bank_url` is set, shows `bank-nav-modal`

`_import_lock` (a `threading.Lock`) prevents concurrent imports. The lock is acquired by `start_import()` before spawning the thread and released inside the thread after the subprocess steps complete.

## Modals

Three overlay modals follow the same structural pattern (backdrop div + centered panel div):

| ID | Trigger | Purpose |
|---|---|---|
| `import-source-modal` | ⟳ Import button | Choose debit vs. savings account before import |
| `bank-nav-modal` | Set by `_stream_import` via `set_props` | "No new transactions — visit bank?" |
| `settings-modal` | ⚙ button | Edit all config values |
| `tx-modal` | Click on weekly chart data points | Transaction drill-down |

## Callback conventions

- Callbacks that share an Output with another callback use `allow_duplicate=True`
- The main `refresh()` callback takes only `refresh-btn` as Input (import now goes through its own `start_import()` callback)
- `_build_period_args(period, begin, end)` extracts the period-arg building logic shared between `refresh()` and `start_import()`

## Known gotchas

**`_label()` uses `" "`** — the layout helper `_label(text)` is called with `" "` (a Python unicode escape for non-breaking space) as a spacer in several places. The Edit tool cannot match this because the JSON parameter encoding treats ` ` as the actual Unicode character, which doesn't match the 6-byte ASCII escape in the source file. Use a Python `str.replace()` script (via Bash) when editing those lines.

**`set_props` is a background-thread push** — it works because Dash 2.9+ implements server-side queuing that the client polls. It can update any component property, including complex Plotly figures. Don't use it from within a callback's synchronous return path — use normal Output declarations there.

**`CFG` mutation is not thread-safe** — `save_settings()` and `_stream_import()` can theoretically race on `CFG`. In practice this is fine for a single-user local tool, but don't add concurrency that assumes `CFG` is stable mid-import.

**Account depth in `_stream_import`** — the depth value passed to the background thread is captured at the moment the user clicks the account button. If the user changes the depth dropdown mid-import, the graphs will be built with the old depth. This is intentional.
