# How to walk this map

**Read order:** `docs/map/CLAUDE.md` (catalog) → `docs/map/objects/_index.md`
(find the noun) → **one** card. That is three small files, not a folder.

Never load `objects/` wholesale. The catalog exists so you do not have to.

## What a card owes you

An object card answers *what is this*, *why is it this shape*, and *what else
moves if I touch it*. It does **not** restate behaviour — that lives in the
file it cites. A card that duplicates code is a card that will be wrong within
a month.

Every card carries frontmatter:

```yaml
type: object
universe: live | leftover | ghost
status: verified | stub | stale
verified: <YYYY-MM-DD>            # omit rather than guess
branch: <branch or revision verified was checked against>
cluster: config | queries | figures | layout | callbacks | import-pipeline
source: <path to the file that owns the fact>
```

`status: verified` requires a date, a branch (or revision), and at least one
citation. A confident wrong date is worse than no date.

## Evidence, in this repo specifically

Citations are `path#symbol`, not `path:line`, and that is deliberate. The
notes file this map replaced was a hand-written line table; by the time it was
archived it claimed `app.py` was ~2,970 lines with `SankeyBuilder` at 580–712,
against a real 3,477 lines and a class starting at 636. `git log --oneline --
CLAUDE.md` holds the old text. A `#symbol` anchor cannot drift that way, so
prefer it for anything inside `app.py`; use a line range only where no symbol
encloses the fact.

Citations resolve **against this repo root only**. No card cites a path under
`$ACCOUNTING_DIR` — the data side is named in prose and never cited, because
the checker cannot reach it and because the live config is private. If you
want to know what the app reads and writes over there, the shelf contracts are
`~/Accounting/ledger/CONTEXT.md` and `~/Accounting/01_inbox/CONTEXT.md`.

`tests/test_paths.py` is the executable half of the `config` cluster: every
claim in those cards about where a path resolves has a test beside it. If a
card and that file disagree, run pytest before you believe the card.

## The universes, applied

Drawn 2026-09-20 on branch `chore/accounting-dir`, against the commit that
moved config, journal and rules resolution onto `$ACCOUNTING_DIR`.

| Universe | Where it applies today |
|---|---|
| **live** | every card in this map except the two below |
| **leftover** | the singular `hledger_rules` config key. It is not in `CONFIG_DEFAULTS` and not writable from the settings modal; it survives only as a back-compat rename inside `load_config` for configs written before the debit/savings split |
| **ghost** | the shared journal file lock. P1 of the ledger-agent umbrella spec (§7) gives the journal a lock shared with that project's `promote`. Nothing implements it yet — `_import_lock` is a `threading.Lock` and serialises imports **within one process only** |

## The walk test this map is held to

Fixed on 2026-09-20, while the cards were being written, so the map could not
be tuned to fit a question chosen afterwards:

> What builds every hledger command this app runs, and what else moves if I
> change it?

A correct answer names `hledger_cmd`, says it is the **only** builder and that
it passes `-n -f $JOURNAL`, and gives a first-order waterfall. The route is
`docs/map/CLAUDE.md` — where "Two things a newcomer gets wrong" states the
invariant outright — then one hop to
`docs/map/objects/queries/hledger-command.md` for the waterfall. Catalog plus
one card. If a future edit breaks that route, the map has regressed.

## Where the map does not reach

- **`processes/` and `effects/`.** This map was built by `/icm-map:map-init`,
  which ends at the noun layer by design. Slice 3 (the movements: refresh,
  import, settings save), slice 4 (the change-impact index, plus the backwards
  pass for what points *into* this repo from outside) and slice 5 (re-verify
  the waterfalls) are not yet done. Each card's *If you change this* carries a
  first-order waterfall in the meantime.
- **`README.md`.** Human orientation for someone installing the app, not a
  noun. It is not held to this map's citation standard.
- **`uv.lock`, `assets/` bundling, `logs/`.** Generated or runtime output.
- **The data side.** Everything under `$ACCOUNTING_DIR` is named, never cited.
