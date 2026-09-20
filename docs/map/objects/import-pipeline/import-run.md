---
type: object
universe: live
status: verified
verified: 2026-09-20
branch: chore/accounting-dir
cluster: import-pipeline
source: app.py
---

# The import run — `_stream_import()`

The background thread that runs `txcat auto --source <name>`, then
`hledger import <rules>`, streaming both processes' output into the status log,
and then rebuilds every figure.

## Why this shape

Two steps, in that order, because they are two tools. `txcat` categorises the
bank CSV; `hledger import` reads the result through a `.rules` file and appends
to the journal. Either can be the one that fails, and streaming their combined
stdout line by line into `_import_log` is what lets the user see which.

**`txcat` is launched with no `cwd`** — `(["txcat", "auto", "--source", source], None)`.
It finds its own configuration through the inherited `$ACCOUNTING_DIR`, so the
dashboard has no business choosing a working directory for it. This is the
shape the `$ACCOUNTING_DIR` migration produced, and a reintroduced `cwd` would
be a regression, not a fix.

The `hledger import` step is built through `hledger_cmd`, so it writes to the
same journal every read in the app targets. There is no second path by which
this app can modify a ledger.

`skip_txcat_<source>` drops the first step entirely, for an account whose CSV
arrives already categorised.

Success is not assumed. `_NO_NEW_TX_MARKERS` matches three strings either tool
prints when there was nothing to do; seeing one sets `_import_no_new_tx`, skips
the redraw, and lets `poll_import` offer the bank URL instead.

## Shape

| Field / element | Constraint | Cite |
|---|---|---|
| `_stream_import(source, period_args, depth, period_label)` | runs on a daemon thread, not in a callback | `app.py#_stream_import` |
| step 1 | `txcat auto --source <source>`, **cwd `None`**, skippable | `app.py#_stream_import` |
| step 2 | `hledger_cmd("import", rules)` | `app.py#hledger_cmd` |
| the rules path | `from_config(CFG[f"hledger_rules_{source}"])` | `app.py#from_config` |
| child environment | inherited, plus `PYTHONUNBUFFERED=1` | `app.py#_stream_import` |
| no-new-transaction detection | three literal markers | `app.py#_NO_NEW_TX_MARKERS` |
| the redraw | a **second copy** of `refresh`'s entire build sequence | `app.py#refresh` |

## Connected to

- **owns** — the only write to the journal this app performs.
- **owned by** — [import-state](import-state.md), whose module globals it is
  the sole writer of, and
  [accounting-paths](../config/accounting-paths.md) for the rules path.
- **looks like but is not** — [refresh](../callbacks/refresh.md). It performs
  the same redraw and never calls it.

## If you change this

**Hits**
- Every one of `refresh`'s figure builders, because the second half of this
  function repeats them — `app.py#build_sankey`, `app.py#build_monthly_bar_figure`, `app.py#build_small_multiples_figure`, `app.py#build_heatmap_figure`
- `_import_result`, whose `"component.prop"` keys must match `poll_import`'s
  output order — `app.py#poll_import`
- The two `hledger_rules_*` config keys and the settings widgets that edit
  them — `app.py#_SETTINGS_DISK_KEYS`

**Does not hit**
- Any other process. `_import_lock` is a `threading.Lock`: it serialises
  imports inside **this** process and does nothing about a second dashboard, a
  terminal, or ledger-agent writing the same journal concurrently. A shared
  journal file lock is planned for P1 (umbrella spec §7) and does not exist
  today — `app.py#_import_lock`
- txcat's own rules. This repo passes a source name and nothing else; how
  txcat categorises is entirely outside it — `app.py#CFG`

## Surfaces

| Who | Reads | Writes |
|---|---|---|
| `handle_import_modal` | starts the thread | — |
| `txcat` (subprocess) | the inbox, via `$ACCOUNTING_DIR` | categorised CSV |
| `hledger import` | the CSV and the rules file | **the journal** |
| `poll_import` | `_import_log`, `_import_result` | the page |
| tests | none | — |

## See

- `app.py` — lines 257 to 412 hold the whole run.
