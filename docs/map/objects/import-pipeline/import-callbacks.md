---
type: object
universe: live
status: verified
verified: 2026-09-20
branch: chore/accounting-dir
cluster: import-pipeline
source: app.py
---

# The import callbacks — `handle_import_modal()`, `poll_import()`, `close_bank_modal()`

The modal that picks a source and starts the thread, the 400 ms interval that
streams its progress, and the little "no new transactions" prompt.

## Why this shape

`handle_import_modal` carries four inputs — open, cancel, debit, savings — on
one callback, because all four write the same modal style and Dash allows only
one writer per output. It takes `_import_lock` **before** resetting anything,
so a second click while an import runs returns a message and leaves the first
run's state untouched.

`poll_import` is a `dcc.Interval` that starts disabled and is enabled by the
starting callback, then disables itself once `_import_done`. Polling only while
an import is in flight is what keeps an idle dashboard from waking the server
every 400 ms.

Its eleven outputs deliberately mirror `refresh`'s, all with
`allow_duplicate=True`, so the post-import redraw can write the same components
the Refresh button writes. That mirroring is manual: the order of the outputs
here must match the `"component.prop"` keys `_stream_import` populates.

The bank prompt is the payoff of the no-new-transactions detection — rather
than reporting "nothing happened", the app offers the bank URL so the user can
go and download a statement.

## Shape

| Field / element | Constraint | Cite |
|---|---|---|
| `handle_import_modal` | open / cancel / debit / savings on one callback | `app.py#handle_import_modal` |
| the lock attempt | `_import_lock.acquire(blocking=False)`; failure is a message | `app.py#_import_lock` |
| the thread | `threading.Thread(..., daemon=True).start()` | `app.py#_stream_import` |
| `poll_import` | 11 outputs, all `allow_duplicate=True`; self-disabling | `app.py#poll_import` |
| the bank prompt | shown when `_import_no_new_tx` and `CFG["bank_url"]` is set | `app.py#close_bank_modal` |
| the period | scoped by `_build_period_args`, same as a refresh | `app.py#_build_period_args` |

## Connected to

- **owns** — `import-source-modal`, `import-poll`, `bank-nav-modal`.
- **owned by** — [import-state](import-state.md), which it resets and reads.
- **looks like but is not** — [refresh](../callbacks/refresh.md). Same eleven
  components, different trigger, and the figures it writes were built on a
  background thread rather than in the callback.

## If you change this

**Hits**
- `_stream_import`'s `_import_result` keys, which must stay aligned with this
  output order — `app.py#_stream_import`
- `refresh`, whose output list this one shadows; a component added there needs
  an `allow_duplicate` twin here or the post-import redraw will not update it — `app.py#refresh`
- The `bank_url` setting and its settings widget — `app.py#_SETTINGS_DISK_KEYS`

**Does not hit**
- The journal or txcat. These callbacks start and observe; all subprocess work
  is on the thread — `app.py#hledger_cmd`
- `strip-parent-filter`'s meaning. It is reset to `[]` after an import because
  the categories may have changed, not because filtering changed — `app.py#update_strip_filter`

## Surfaces

| Who | Reads | Writes |
|---|---|---|
| humans | press Import, pick a source | — |
| the browser | polls every 400 ms while running | the log and 9 components |
| the import thread | — | what the poller reads |
| tests | none | — |

## See

- `app.py` — lines 3168 to 3258 hold all three callbacks.
