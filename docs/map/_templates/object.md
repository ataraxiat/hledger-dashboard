---
type: object
universe: live
status: stub
verified:
branch:
cluster:
source:
---

# <Spoken name> — `<CodeName>`

<One sentence. If the product word and the code/file word differ, both appear
here — that collision is the single most expensive thing a newcomer gets
wrong.>

## Why this shape

<The load-bearing reason. What breaks if it were the obvious other shape.
Not a field tour — the fields are below, and the file itself is authoritative
about them.>

## Shape

| Field / element | Constraint | Cite |
|---|---|---|
|  |  | `path:line` |

<Cite the file that owns each fact. A `path#symbol` anchor cannot go stale
when code above it moves; prefer it for anything you expect to shift.>

## Connected to

- **owns** — <cards this one is the parent of>
- **owned by** — <the card that contains this one>
- **looks like but is not** — <the card someone will confuse this with, and
  the one-line reason they are different>

## If you change this

**Hits**
- <first-order consequence> — `path:line`

**Does not hit**
- <the obvious next noun that is the WRONG one, and why it is untouched>

<First-order only. A waterfall that tries to be transitive is one nobody
trusts. "Does not hit" is not filler: it names the guess a competent editor
would otherwise make.>

## Surfaces

| Who | Reads | Writes |
|---|---|---|
| <app / service> |  |  |
| <agent> |  |  |
| <human> |  |  |
| tests | `tests/test_<x>` |  |

## See

- `<the source file this card cites>`
- <at most ONE as-built document. More than one and the card has become a
  second spec.>
