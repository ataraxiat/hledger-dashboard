---
type: object
universe: live
status: verified
verified: 2026-09-20
branch: chore/accounting-dir
cluster: queries
source: app.py
---

# The query runners — `run_hledger()` and its three siblings

The four functions that actually spawn hledger, read its stdout and hand back
`(data, command_string)`. Every one of them builds its argv with `hledger_cmd`.

## Why this shape

They all return the command string alongside the data, and that is the
interesting choice: the string is what the status log shows the user, so a
wrong number is diagnosable without attaching a debugger. It also means
failure is a *return value*, not an exception — a non-zero exit yields an empty
frame plus an error string, and the caller renders an empty figure rather than
a stack trace. A dashboard that dies on a malformed journal is worse than one
that says so in the log.

Three separate runners rather than one parameterised one because their output
shapes genuinely differ: a balance table, a weekly table with an average
column, and a flat register list are not the same thing, and collapsing them
would mean a caller-side switch on the shape anyway.

## Shape

| Field / element | Constraint | Cite |
|---|---|---|
| `run_hledger(args, period_args, depth, monthly)` | `bal`-style CSV → DataFrame; `depth=None` omits the `-N` flag | `app.py#run_hledger` |
| `run_hledger_weekly(account, period_args, depth)` | adds `--weekly --average`; depth defaults to 3 | `app.py#run_hledger_weekly` |
| `run_hledger_register_full(account, period_args)` | `register`, **no** depth flag — full transaction detail | `app.py#run_hledger_register_full` |
| `get_ledger_start_date()` | `print`, then the **second** date seen — the first sets opening balances | `app.py#get_ledger_start_date` |
| failure mode | empty frame/list plus an error string; never raises | `app.py#run_hledger` |

## Connected to

- **owns** — nothing.
- **owned by** — [hledger-command](hledger-command.md). Change the argv prefix
  and all four change with it.
- **looks like but is not** — [ledger-frames](ledger-frames.md). The runners
  return raw hledger CSV as a DataFrame; normalising it into the app's own
  shapes is a separate step every caller performs.

## If you change this

**Hits**
- `refresh`, which calls `run_hledger` six times and the other three once each — `app.py#refresh`
- `_stream_import`'s post-import redraw, which repeats that same sequence — `app.py#_stream_import`
- `_build_period_args`, whose `"from"` branch calls `get_ledger_start_date` — `app.py#_build_period_args`

**Does not hit**
- The figure builders. They take DataFrames and dicts and never learn where
  they came from — `app.py#build_sankey`
- The shell console. It spawns its own `subprocess.run` with a 30-second
  timeout and does not go through any of these — `app.py#run_shell`

## Surfaces

| Who | Reads | Writes |
|---|---|---|
| `refresh` | all four | — |
| `_stream_import` | `run_hledger`, `run_hledger_weekly`, `run_hledger_register_full` | — |
| hledger (subprocess) | the journal, read-only | — |
| humans | the returned command string, in the status log | — |
| tests | none directly | — |

## See

- `app.py` — lines 193 to 531 hold all four.
