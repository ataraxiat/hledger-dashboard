---
type: object
universe: live
status: verified
verified: 2026-09-20
branch: chore/accounting-dir
cluster: config
source: app.py
---

# The config file — `CONFIG_DEFAULTS`, `load_config()`, `CFG`

Ten settings — four account names, two rules paths, a bank URL, two txcat
bypasses and a default depth — merged over built-in defaults into one
process-wide dict called `CFG`.

## Why this shape

Defaults live in code, not in the JSON file, so a config written a year ago
still boots after a new key is added: `load_config` returns
`{**CONFIG_DEFAULTS, **on_disk}` and the missing key simply takes its default.
That is why `config.example.json` is a *sample*, not a schema — the schema is
`CONFIG_DEFAULTS`, and `tests/test_paths.py` asserts the sample is a subset of
it rather than equal to it.

`CFG` is a module-level dict rather than a reload-per-request read because
Dash serves every browser session from one process. One dict means the
settings modal changes what every open tab sees on the next callback. It also
means the config file is read exactly once per process lifetime.

## Shape

| Field / element | Constraint | Cite |
|---|---|---|
| `CONFIG_DEFAULTS` | the real schema: 10 keys, typed `str \| int` | `app.py#CONFIG_DEFAULTS` |
| `load_config()` | defaults ⊕ on-disk; returns defaults untouched if the file is absent | `app.py#load_config` |
| `CFG` | the live dict, built at import, mutated in place by the settings modal | `app.py#CFG` |
| `_SETTINGS_DISK_KEYS` | the subset actually written back to disk — currently all ten | `app.py#_SETTINGS_DISK_KEYS` |
| `config.example.json` | a sample, asserted to be a subset of `CONFIG_DEFAULTS` | `config.example.json` |
| the subset assertion | `tests/test_paths.py#test_the_example_config_uses_only_known_keys` | `tests/test_paths.py` |

`hledger_rules` (singular) is **leftover**: it is not in `CONFIG_DEFAULTS` and
cannot be written, but `load_config` renames it to `hledger_rules_debit` for
configs predating the debit/savings split.

## Connected to

- **owns** — the two `hledger_rules_*` values, which
  [import-run](../import-pipeline/import-run.md) resolves through `from_config`
- **owned by** — [accounting-paths](accounting-paths.md), which decides *where*
  `config.json` is
- **looks like but is not** — [settings-modal](../callbacks/settings-modal.md).
  That card owns the write path and the widgets; this one owns the key set.

## If you change this

**Hits**
- The settings modal, which has one hard-coded widget per key and must gain
  one — `app.py#save_settings`
- The disk-write list, which is a separate literal from `CONFIG_DEFAULTS` and
  does not update itself — `app.py#_SETTINGS_DISK_KEYS`
- `config.example.json`, and the subset test that guards it — `tests/test_paths.py`
- `install.sh`, which seeds the file on a fresh machine — `install.sh`

**Does not hit**
- `JOURNAL`. The journal is not a config key and never has been; it comes from
  `$LEDGER_FILE` or the accounting root — `app.py#JOURNAL`
- Any running import. `_stream_import` reads `CFG` when the thread starts, so a
  settings save mid-import changes nothing already in flight — `app.py#_stream_import`

## Surfaces

| Who | Reads | Writes |
|---|---|---|
| the Dash app | `CFG` everywhere | — |
| the settings modal | `CFG` | `CFG` and `config.json` |
| `install.sh` | — | `config.json` on first run |
| humans | `config.example.json` | the live `config.json` |
| tests | `tests/test_paths.py` | — |

## See

- `app.py` — lines 72 to 101 own the defaults, the merge and `CFG`.
