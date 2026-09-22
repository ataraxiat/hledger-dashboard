# Objects — the nouns

23 cards over one 3,477-line module plus three support files. Clustered by
**how an editor asks**, not by where the code sits in the file: `periods`
holds a constant from line 104, a helper from line 3155 and a callback from
line 2656, because someone adding a period option needs all three and does not
care that they are 3,000 lines apart.

**Start at `docs/map/objects/_index.md`, open one card.** Never read this
folder whole.

## Clusters

| Cluster | The question it answers | Universe |
|---|---|---|
| `config` | where does this path or setting come from | live |
| `queries` | how does the app ask hledger a question, and what comes back | live |
| `figures` | how does a DataFrame become a Plotly figure | live |
| `layout` | what is on the page, and what component id does it carry | live |
| `callbacks` | what happens when the user clicks something | live |
| `import-pipeline` | how do new transactions get into the journal | live |

## Adding a card

Copy `docs/map/_templates/object.md`. Do not start from a sibling — siblings
carry their own emphasis and you will inherit it.

Three rules that are not negotiable:

1. **Cite `path#symbol`, do not paraphrase behaviour.** The file owns the
   fact. Use a line range only where no symbol encloses what you mean
   (`app.layout` is an attribute assignment, so it has no anchor) — and expect
   that range to rot.
2. **`status: verified` needs a date, a branch, and a citation.**
3. **Fill *Does not hit*.** It is the section that earns the card.

## The two duplications that catch everyone

Both are invisible from either side alone, and both are the most likely way to
break this app.

1. **`_stream_import` does not call `refresh`.** It contains a second copy of
   the same figure-building sequence, so every card whose *Hits* mentions
   `refresh` mentions `_stream_import` too.
2. **`refresh` does not call `_build_period_args`.** That helper is defined at
   3155, below `refresh` at 2698, so `refresh` writes the same four period
   branches out inline. `handle_import_modal` is the helper's only caller.
