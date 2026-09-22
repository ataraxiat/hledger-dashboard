# hledger-dashboard system map

What each noun in `app.py` is, and what else moves if you change one.
**The code is the source of truth**; these cards cite it by `path#symbol`.
When a card and the code disagree, the code wins and the card is stale.

`app.py` is one 3,477-line module. This map is how you find the 40 lines you
need without reading the other 3,437. Do not read this folder end to end —
open the index, then one card.

## Universes

- **live** — in force, shipped. Implement and cite against these.
- **leftover** — present, no longer the main path. Touch only if it is in scope.
- **ghost** — filed, **not wired**. Nothing runs; do not implement against it.

## Name collisions, stated once

| You will hear | It means |
|---|---|
| "the journal" | the single file `JOURNAL`, `$ACCOUNTING_DIR/ledger/journal/main.journal` — **not** the `ledger/` shelf, which also holds `import/` rules |
| "the config" | three different things. `config.example.json` is the checked-in template; `CONFIG_PATH` is the live file in a private shelf **this repo must never read**; `CFG` is the in-process dict, hot-mutated by the settings modal |
| "import" | the txcat → `hledger import` pipeline, never a Python import |
| "refresh" | the `refresh` callback, which redraws every figure. The import pipeline's own chart redraw is a *different* code path inside `_stream_import` |
| "the rules" | hledger CSV rules files (`bank.debit.csv.rules`) — **not** txcat's categorisation rules, which live in txcat's own shelf and are invisible here |
| "the lock" | `_import_lock`, a `threading.Lock` scoped to one process. It is not a file lock and guards nothing against a second process |

## Most questions land on one of these eight cards

Open the card directly. Go to `objects/_index.md` only when none of these fits.

| If you are asking | Open |
|---|---|
| what hledger command runs, or why every call carries `-n -f` | `objects/queries/hledger-command.md` |
| where a path or a setting comes from | `objects/config/accounting-paths.md` |
| a setting's default, or what `CFG` holds | `objects/config/config-file.md` |
| what redraws the charts | `objects/callbacks/refresh.md` |
| what is on the page, or what a component id belongs to | `objects/layout/page-layout.md` |
| how state moves between callbacks | `objects/layout/stores.md` |
| how new transactions get into the journal | `objects/import-pipeline/import-run.md` |
| the income → savings/expenses flow chart | `objects/figures/sankey.md` |

## Shelves — everything else

| Go here | For |
|---|---|
| `CONTEXT.md` | how to walk this map; what counts as evidence here |
| `objects/_index.md` | all 23 cards, one line each |
| `objects/config/` | where a path or a setting comes from |
| `objects/queries/` | how the app asks hledger a question and what comes back |
| `objects/figures/` | how a DataFrame becomes a Plotly figure |
| `objects/layout/` | what is on the page and what component id it carries |
| `objects/callbacks/` | what happens when the user clicks something |
| `objects/import-pipeline/` | how new transactions get into the journal |
| `_meta/schema.md` | the closed set of node types and the cluster boundaries |

`processes/` and `effects/` do not exist yet — this map stops at the noun
layer. See "Where the map does not reach" in `docs/map/CONTEXT.md`.

## Two things a newcomer gets wrong

1. **`CFG` is hot; `CONFIG_PATH` and `JOURNAL` are frozen at import.**
   `save_settings` does `CFG.update(...)` and every tab in every browser sees
   it, because `CFG` is one module-level dict. But the two `Path` constants
   were computed from the environment when the module first loaded, so a
   change to `$ACCOUNTING_DIR` or `$LEDGER_FILE` needs a restart, not a save.
2. **No hledger command is built anywhere but `hledger_cmd`.** It supplies
   `-n` (`--no-conf`) and `-f <JOURNAL>` on every call. Writing
   `["hledger", ...]` by hand looks fine in a terminal and silently reads a
   *different* journal when the app is launched from Finder with
   `$LEDGER_FILE` unset. That is the invariant this whole cluster exists for.

*`AGENTS.md` and `routing.md` are generated copies of this file
(`docs/map/_meta/generate-twins.sh`). Never hand-edit them.*
