---
type: object
universe: live
status: verified
verified: 2026-09-20
branch: chore/accounting-dir
cluster: callbacks
source: app.py
---

# The shell console — `run_shell()`

A text box that runs an arbitrary hledger subcommand against this app's journal
and prints the raw output.

## Why this shape

It exists so a number on a chart can be checked without leaving the page, and
it is safe to expose precisely because it cannot escape hledger. The input is
split with `shlex.split` (no shell, so no pipes, redirects or `;`), a leading
`hledger` is stripped so the user may type it either way, and the remaining
words are passed to `hledger_cmd` — which means the console inherits `-n` and
`-f <JOURNAL>` like everything else. A user cannot point it at a different
journal, and cannot run a non-hledger program.

The 30-second timeout is the one guard this path has that the query runners do
not: a user-typed query over a large journal can hang far longer than anything
the app issues itself.

## Shape

| Field / element | Constraint | Cite |
|---|---|---|
| `run_shell(btn, enter, cmd_str)` | fires on button click or Enter in the box | `app.py#run_shell` |
| parsing | `shlex.split`; a parse error is returned as text, not raised | `app.py#run_shell` |
| the `hledger` strip | drops a leading `hledger` or `$HLEDGER_BIN` | `app.py#HLEDGER_BIN` |
| the argv | built by `hledger_cmd`, so `-n -f JOURNAL` always apply | `app.py#hledger_cmd` |
| timeout | 30 seconds | `app.py#run_shell` |
| output | the echoed command, then stdout, then stderr on failure | `app.py#run_shell` |

## Connected to

- **owns** — `shell-output`.
- **owned by** — [hledger-command](../queries/hledger-command.md). Its safety
  property *is* that function's guarantee.
- **looks like but is not** — [hledger-runners](../queries/hledger-runners.md).
  Those parse CSV into frames; this returns raw text and has its own
  `subprocess.run` with a timeout.

## If you change this

**Hits**
- Nothing else in the app. It writes one output and reads no store — `app.py:1599-2513`

**Does not hit**
- Any figure or store. Running a command here changes no chart — `app.py#refresh`
- The journal. hledger subcommands reachable this way are reads; the one
  hledger command that writes, `import`, is issued only by the import
  pipeline — `app.py#_stream_import`

## Surfaces

| Who | Reads | Writes |
|---|---|---|
| humans | type a command | — |
| hledger | the journal, read-only | — |
| the browser | `shell-output` | — |
| tests | none | — |

## See

- `app.py` — the callback at line 3011.
