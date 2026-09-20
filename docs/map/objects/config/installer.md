---
type: object
universe: live
status: verified
verified: 2026-09-20
branch: chore/accounting-dir
cluster: config
source: install.sh
---

# The installer — `install.sh`

A 223-line shell script that checks for `uv` and `hledger`, syncs
dependencies, seeds `config.json` if it is missing, and optionally launches the
app.

## Why this shape

It is a uv installer, not a virtualenv installer. There is no `venv/` to
activate and no `requirements.txt` to pin against — `pyproject.toml` plus
`uv.lock` are the dependency truth, and `uv sync` is the whole install step.
Anything describing this repo as having a `venv/` or a `requirements.txt` is
describing a state that no longer exists.

It seeds rather than overwrites the config, because the live config lives in a
private shelf the installer has no business clobbering on a re-run.

## Shape

| Field / element | Constraint | Cite |
|---|---|---|
| dependency install | `uv sync`, hard-failing if `uv` is absent | `install.sh:188-194` |
| run modes | `uv run python app.py`, with `--port` / `--debug` / `--host` | `install.sh:202-215` |
| `--run` | syncs, then launches in the foreground | `install.sh:222` |
| config seeding | writes the config only when it does not already exist | `install.sh` |
| declared deps | `dash`, `plotly`, `pandas`; `pytest` in the dev group | `pyproject.toml` |

## Connected to

- **owns** — the first `config.json` on a fresh machine
- **owned by** — [accounting-paths](accounting-paths.md); it seeds into
  `CONFIG_PATH`, so it moves when the accounting root moves
- **looks like but is not** — [config-file](config-file.md). The installer
  writes the file once; the settings modal owns it forever after.

## If you change this

**Hits**
- The run instructions in `README.md`, which repeat the `uv run` invocations
- Anyone following the root routing table's "Run it" row — `CLAUDE.md`

**Does not hit**
- `app.py`. Nothing in the app reads or re-executes the installer; a change to
  the install path cannot change runtime behaviour — `app.py`
- The import pipeline. `txcat` and `hledger` are located on `$PATH` at call
  time, not installed by this script — `app.py#_stream_import`

## Surfaces

| Who | Reads | Writes |
|---|---|---|
| humans | `./install.sh --run` | — |
| the installer | `pyproject.toml`, `uv.lock` | `.venv/` via uv, `config.json` |
| the app | — | — |
| tests | none | — |

## See

- `install.sh` — the script owns every fact on this card.
