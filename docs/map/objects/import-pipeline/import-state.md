---
type: object
universe: live
status: verified
verified: 2026-09-20
branch: chore/accounting-dir
cluster: import-pipeline
source: app.py
---

# The import state — `_import_lock` and the four module globals

The lock that admits one import at a time, and the log, two flags and result
dict a background thread writes while a polling callback reads them.

## Why this shape

A Dash callback cannot block — it would hold a worker for the length of the
import — so the work goes on a daemon thread and the progress has to live
somewhere both the thread and the callback can reach. Module globals are that
somewhere. The comment in the source is explicit about why it is safe without
further synchronisation: CPython's GIL makes `list.append` and a bool
assignment atomic enough for a single writer and a single reader.

`_import_lock` is acquired **non-blocking** in the callback rather than in the
thread. That is the load-bearing detail: a second import attempt gets an
immediate "already running" message instead of a queued job the user cannot
see. The thread releases it in a `finally`.

`_import_result` is keyed by `"component.prop"` strings so `poll_import` can
`.get(..., no_update)` each output independently — a redraw that partially
failed still delivers whatever it did build.

## Shape

| Field / element | Constraint | Cite |
|---|---|---|
| `_import_lock` | `threading.Lock`; **this process only** | `app.py#_import_lock` |
| `_import_log` | `list[str]`, appended by the thread, joined by the poller | `app.py#_import_log` |
| `_import_done` | flips true exactly once per run | `app.py#_import_done` |
| `_import_no_new_tx` | set when a marker matched; suppresses the redraw | `app.py#_import_no_new_tx` |
| `_import_result` | `{"component.prop": value}` | `app.py#_import_result` |
| the reset | performed by the starting callback, before the thread launches | `app.py#handle_import_modal` |

**Ghost, not present:** a journal file lock shared with `ledger-agent`'s
promote is planned for P1 (umbrella spec §7). Nothing implements it. Do not
read `_import_lock` as though it provided it.

## Connected to

- **owns** — the import's observable progress.
- **owned by** — [import-run](import-run.md), its only writer after the reset.
- **looks like but is not** — [stores](../layout/stores.md). Those are
  per-browser; these are per-process and shared by every session, so two users
  hitting one dashboard see the same import log.

## If you change this

**Hits**
- `_stream_import`, which declares three of them `global` — `app.py#_stream_import`
- `poll_import`, whose eleven outputs are driven by `_import_done` and the
  keys of `_import_result` — `app.py#poll_import`
- `handle_import_modal`, which resets all four and takes the lock — `app.py#handle_import_modal`

**Does not hit**
- `CFG`. Import state is transient and never persisted to `config.json` — `app.py#_SETTINGS_DISK_KEYS`
- Any concurrent writer outside this process. Adding fields here cannot make
  the journal safe against one — `app.py#JOURNAL`

## Surfaces

| Who | Reads | Writes |
|---|---|---|
| the import thread | all five | log, flags, result |
| `poll_import` | log, flags, result | — |
| `handle_import_modal` | the lock | the reset |
| humans | the status log | — |
| tests | none | — |

## See

- `app.py` — lines 241 to 255 declare all five.
