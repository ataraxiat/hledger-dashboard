---
type: object
universe: live
status: verified
verified: 2026-09-20
branch: chore/accounting-dir
cluster: queries
source: app.py
---

# The hledger command — `hledger_cmd()`

The single function that builds an hledger argv in this repo. It returns
`[HLEDGER_BIN, "-n", "-f", str(JOURNAL), *args]`, and nothing else anywhere
constructs an hledger command list.

## Why this shape

Two flags, both load-bearing, both easy to forget by hand:

- **`-f <JOURNAL>`** names the journal explicitly. `$LEDGER_FILE` is routinely
  unset — the app is launched from Finder, from a desktop shortcut, from a
  bare shell — and an hledger call without `-f` then reads whatever default it
  finds. That failure is silent: you get numbers, just from the wrong file.
- **`-n`** is `--no-conf` on hledger 1.52.1. There is deliberately no
  `hledger.conf` in this setup, and `-n` guarantees one appearing later cannot
  change what the dashboard reports.

Funnelling every call through one builder is what makes those two guarantees
checkable. `tests/test_paths.py#test_every_hledger_command_names_the_journal_and_ignores_config_files`
asserts the argv prefix, and it only means anything because there is no second
builder for it to miss.

## Shape

| Field / element | Constraint | Cite |
|---|---|---|
| `hledger_cmd(*args)` | returns `[bin, "-n", "-f", JOURNAL, *args]` | `app.py#hledger_cmd` |
| `HLEDGER_BIN` | `$HLEDGER_BIN`, else the bare name `hledger` on `$PATH` | `app.py#HLEDGER_BIN` |
| the argv prefix | asserted at positions 1–3 | `tests/test_paths.py#test_every_hledger_command_names_the_journal_and_ignores_config_files` |

It builds an argv. It does **not** run anything — every caller does its own
`subprocess.run` or `Popen`.

## Connected to

- **owns** — nothing; it is a leaf builder.
- **owned by** — [accounting-paths](../config/accounting-paths.md), which owns
  the `JOURNAL` constant it bakes in.
- **looks like but is not** — [hledger-runners](hledger-runners.md). Those
  spawn the process and parse the output; this only assembles the list.

## If you change this

**Hits**
- All four query runners, which each prepend it — `app.py#run_hledger`,
  `app.py#run_hledger_weekly`, `app.py#run_hledger_register_full`,
  `app.py#get_ledger_start_date`
- The `hledger import` step of the import pipeline, which is also built here — `app.py#_stream_import`
- The shell console, which strips a leading `hledger` and rebuilds through it — `app.py#run_shell`
- The argv-prefix test — `tests/test_paths.py`

**Does not hit**
- The `txcat auto` step. It is the other half of the import pipeline and is
  **not** an hledger command — it is built inline and never passes through
  here, so a change to the flags this function adds leaves txcat untouched — `app.py#_stream_import`
- `CFG` and the account names. Accounts arrive as `*args` from the caller;
  this function has no opinion about them — `app.py#CFG`

## Surfaces

| Who | Reads | Writes |
|---|---|---|
| every query in the app | calls it | — |
| the import pipeline | calls it for the `import` step | — |
| the shell console | calls it with user-typed args | — |
| humans | never directly | — |
| tests | `tests/test_paths.py` | — |

## See

- `app.py` — `hledger_cmd`'s own docstring states the two flags and why.
