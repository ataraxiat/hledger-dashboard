# Object index

23 cards. `verified` means checked against branch `chore/accounting-dir` on
2026-09-20, with at least one `path#symbol` citation into the tree as it
stands at that commit.

## config/ — where does this path or setting come from ⟨live⟩

| Card | One line | Status |
|---|---|---|
| [accounting-paths](config/accounting-paths.md) | `$ACCOUNTING_DIR` and the two Path constants every other path is derived from | verified |
| [config-file](config/config-file.md) | the ten settings, their defaults, and the process-wide `CFG` dict | verified |
| [installer](config/installer.md) | `install.sh`: a uv installer that also seeds the config file | verified |

## queries/ — how does the app ask hledger a question ⟨live⟩

| Card | One line | Status |
|---|---|---|
| [hledger-command](queries/hledger-command.md) | `hledger_cmd`, the only builder of an hledger argv in this repo | verified |
| [hledger-runners](queries/hledger-runners.md) | the four functions that actually spawn hledger and read its CSV | verified |
| [ledger-frames](queries/ledger-frames.md) | the DataFrame and dict shapes hledger CSV is normalised into | verified |
| [periods](queries/periods.md) | the period vocabulary and how a dropdown value becomes `--begin`/`--end` | verified |

## figures/ — how does a DataFrame become a Plotly figure ⟨live⟩

| Card | One line | Status |
|---|---|---|
| [sankey](figures/sankey.md) | `SankeyBuilder` and the income → savings/expenses graph it accumulates | verified |
| [monthly-bar](figures/monthly-bar.md) | the grouped monthly income-vs-expense bar chart | verified |
| [weekly-figures](figures/weekly-figures.md) | small multiples, heatmap and violin strip — the three views of one weekly dict | verified |
| [figure-chrome](figures/figure-chrome.md) | the dark layout, the palette, and the empty-state figure family | verified |

## layout/ — what is on the page, and what id does it carry ⟨live⟩

| Card | One line | Status |
|---|---|---|
| [page-layout](layout/page-layout.md) | `app.layout`: one 900-line `html.Div` holding every component id | verified |
| [stores](layout/stores.md) | the nine `dcc.Store` components that carry state between callbacks | verified |
| [styles](layout/styles.md) | the `STYLE_*` dicts and `assets/dashboard.css` | verified |
| [clientside-callbacks](layout/clientside-callbacks.md) | the three JavaScript callbacks that measure width and fix hover | verified |

## callbacks/ — what happens when the user clicks ⟨live⟩

| Card | One line | Status |
|---|---|---|
| [refresh](callbacks/refresh.md) | the one callback that rebuilds every figure from the journal | verified |
| [weekly-interaction](callbacks/weekly-interaction.md) | orientation, scale, legend filtering and resize for the weekly tab | verified |
| [tx-drilldown](callbacks/tx-drilldown.md) | click a week, get its transactions — served from a pre-fetched store | verified |
| [settings-modal](callbacks/settings-modal.md) | the only writer of `config.json`, and the only mutator of `CFG` | verified |
| [shell-console](callbacks/shell-console.md) | a box that runs arbitrary hledger subcommands against the journal | verified |

## import-pipeline/ — how do new transactions get into the journal ⟨live⟩

| Card | One line | Status |
|---|---|---|
| [import-run](import-pipeline/import-run.md) | `_stream_import`: txcat → `hledger import` → rebuild every figure | verified |
| [import-state](import-pipeline/import-state.md) | the module-level lock, log and result dict the background thread writes | verified |
| [import-callbacks](import-pipeline/import-callbacks.md) | the modal that starts an import and the interval that polls it | verified |

## Not carded, on purpose

- `README.md` — install-and-run orientation for a human, not a noun.
- `tests/test_paths.py` — the executable half of the `config` cluster. It is
  cited by those cards rather than carded itself.
- `uv.lock`, `logs/`, `.venv/` — generated or runtime output.
- Everything under `$ACCOUNTING_DIR` — named in prose, never cited. The data
  side has its own shelf contracts.
