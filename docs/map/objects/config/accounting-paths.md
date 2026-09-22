---
type: object
universe: live
status: verified
verified: 2026-09-20
branch: chore/accounting-dir
cluster: config
source: app.py
---

# The accounting paths — `accounting_dir()`, `from_config()`, `CONFIG_PATH`, `JOURNAL`

Every filesystem path this app touches is derived from one environment
variable, `$ACCOUNTING_DIR`, by two functions and two module constants at the
top of `app.py`.

## Why this shape

The app used to carry independent absolute paths for its config, its journal
and its CSV rules, which meant three places to edit when the data folder moved
and three ways to end up pointed at two different journals at once. Folding
them onto one root makes a relocation a single environment change, and makes
"which journal is this reading" answerable without reading the config file.

`accounting_dir()` falls back to `~/Accounting` rather than raising, because
the app is routinely launched from Finder with an empty environment. The
fallback is the documented default, not a guess.

`from_config()` exists so a config value may be written either way: an
absolute path is honoured, a relative one is taken from `$ACCOUNTING_DIR`.
That is what lets `config.example.json` ship `ledger/import/bank.debit.csv.rules`
as a portable default instead of somebody's home directory.

## Shape

| Field / element | Constraint | Cite |
|---|---|---|
| `accounting_dir()` | `$ACCOUNTING_DIR`, else `~/Accounting`; always `expanduser`'d | `app.py#accounting_dir` |
| `from_config(value)` | absolute wins; relative resolves under `accounting_dir()` | `app.py#from_config` |
| `CONFIG_PATH` | `<root>/_config/hledger-dashboard/config.json` | `app.py#CONFIG_PATH` |
| `JOURNAL` | `$LEDGER_FILE` if set, else `<root>/ledger/journal/main.journal` | `app.py#JOURNAL` |
| all four | evaluated **once, at module import** | `app.py#CONFIG_PATH` |

`CONFIG_PATH` points into a private shelf. The live file is read by the
running app and must not be read by an agent working on this repo;
`config.example.json` is the copy that exists to be looked at.

## Connected to

- **owns** — nothing. This is the root of the path graph.
- **owned by** — nothing in this repo. `$ACCOUNTING_DIR`'s own layout is
  governed by the data folder's schema, § Path rules, which is named here and
  deliberately not cited: it is outside this repo and the citation checker
  resolves against this root only.
- **looks like but is not** — [config-file](config-file.md). That card owns
  the *values*; this one owns *where the file is*. `CONFIG_PATH` moving and a
  config key changing are unrelated edits.

## If you change this

**Hits**
- Every hledger invocation, via the `-f` argument — `app.py#hledger_cmd`
- The import pipeline's rules path resolution — `app.py#_stream_import`
- The settings writer, which `mkdir -p`s `CONFIG_PATH.parent` — `app.py#save_settings`
- All seven path tests, which reload the module under a `tmp_path` root — `tests/test_paths.py`

**Does not hit**
- `CFG`. The obvious guess is that moving the root re-reads the config; it
  does not. `CFG` is populated at import from whatever `CONFIG_PATH` was then,
  and `save_settings` mutates the dict in place thereafter — `app.py#CFG`
- `HLEDGER_BIN`. The hledger *binary* is located by `$PATH` or its own env
  var, and has nothing to do with the accounting root — `app.py#HLEDGER_BIN`

## Surfaces

| Who | Reads | Writes |
|---|---|---|
| the Dash app | all four, at import | — |
| `install.sh` | seeds `CONFIG_PATH` if absent | `config.json` |
| `txcat` (subprocess) | `$ACCOUNTING_DIR` from the inherited environment | — |
| humans | `$ACCOUNTING_DIR`, `$LEDGER_FILE` | — |
| tests | `tests/test_paths.py` | — |

## See

- `app.py` — lines 56 to 70 own all four facts.
