# Node types

Closed set. Adding a type is a change to this file first, and needs a
reason that is not "this one did not fit."

| `type:` | Is | Lives in | Required sections |
|---|---|---|---|
| `object` | a durable noun — a data shape, a module boundary, a filesystem tree, an account set | `objects/<cluster>/` | 1–7 below |
| `process` | a movement that actually runs or is actually followed | `processes/` | Input → Movement → Output, Hits / Does not hit |

Two types. There is no `pattern`, no `decision`, no `note`. <Say where
decisions, measurements, and incident write-ups live in this repo or
vault instead — the map points at those, and does not absorb them.>

## Frontmatter

```yaml
type:      object | process
universe:  live | leftover | ghost
status:    verified | stub | stale
verified:  YYYY-MM-DD             # omit rather than guess
branch:    <branch or revision verified was checked against>
cluster:   <cluster-a> | <cluster-b> | <cluster-c>      # objects only
source:    <path to the ONE file that owns the fact>
```

`source:` is singular by design. If two files both own a fact, one of
them is wrong, or the noun is really two nouns.

## Object card sections

1. **One sentence** — including the code name if it differs from the spoken name
2. **Why this shape** — the load-bearing reason, not a field tour
3. **Shape** — keys, constraints, owning files, with `path:line`
4. **Connected to** — owns / owned by / looks like but is not
5. **If you change this** — **Hits** / **Does not hit**, first-order only
6. **Surfaces** — who reads and writes it (apps, agents, humans, none)
7. **See** — the source file, and at most one as-built document

Section 5's *Does not hit* is not filler. It names the obvious next noun
that is the **wrong** one — the guess a competent editor would otherwise
make.

## Cluster boundaries

| Cluster | Holds | Does not hold |
|---|---|---|
| `<cluster-a>` | <what belongs here> | <the neighboring cluster it is not> |
| `<cluster-b>` | <what belongs here> | <the neighboring cluster it is not> |

## Ghost rule

A `universe: ghost` card cites a spec line, never `path:line`, and must
carry a **Blocked on** section naming what has to exist first. A ghost
card with a `path:line` citation is either mislabelled or the code landed
and nobody re-verified it.
