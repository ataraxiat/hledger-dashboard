# hledger Dashboard

An interactive web dashboard for [hledger](https://hledger.org) plain-text accounting journals. Visualises income, expenses, and savings as a live Sankey flow diagram and a monthly trend bar chart. Data is fetched on demand from the `hledger` CLI. This project was written in it's entirety by an LLM.

---

## Features

**Sankey diagram** — models the full flow of money through your accounts for a chosen period: income sources → checking account → savings and expense categories. Sub-accounts are shown up to four levels deep, controlled by the Depth dropdown.

**Monthly trend chart** — grouped bar chart of total income vs. total expenses for every month in the selected period.

**Flexible period selection** — a preset dropdown covers the most common ranges (this year, last quarter, last 12 months, etc.). Custom date ranges can be entered via date pickers, each with a one-click *Today* shortcut. The From and To fields can be used independently or together; setting *only* a To date is blocked with an explanation (see [Guardrails](#guardrails)).

**Debit account reconciliation** — the net period change in your checking/debit account is factored into the Sankey so that inflows always equal outflows, even when prior-period balances fund spending in the current period.

**Configurable account names** — all four account prefixes are stored in `config.json` and set interactively by the installer. No code editing required.

**Dark theme** — colour-coded by account type (income: blue, savings: mint, expenses: coral, debit adjustment: amber). The plot area maintains a 3:2 aspect ratio and fills the available viewport height.

---

## Requirements

| Dependency | Version | Notes |
|---|---|---|
| [hledger](https://hledger.org/install.html) | any recent | Must be on `$PATH` (or set `HLEDGER_BIN`) |
| Python | ≥ 3.10 | |
| dash | ≥ 2.17 | Installed automatically |
| plotly | ≥ 5.22 | Installed automatically |
| pandas | ≥ 2.0 | Installed automatically |

---

## Installation

```bash
git clone https://github.com/your-username/hledger-dashboard.git
cd hledger-dashboard
chmod +x install.sh
./install.sh
```

The installer will:

1. Check for Python 3.10+ and warn if `hledger` is not on `$PATH`
2. Prompt for your account names (press Enter to accept the default):

   | Setting | Default |
   |---|---|
   | Income account | `income` |
   | Expenses account | `expenses` |
   | Savings account | `assets:bank:savings` |
   | Debit/checking account | `assets:bank:debit` |

3. Write `config.json` with your choices
4. Create a Python virtual environment in `./venv`
5. Install Python dependencies (`dash`, `plotly`, `pandas`)
6. Create `assets/dashboard.css`

To launch the server immediately after installation:

```bash
./install.sh --run
```

---

## Usage

```bash
source venv/bin/activate
python app.py
```

Open **http://127.0.0.1:8050** in your browser. The dashboard makes no hledger calls on startup — select a period and depth, then press **↻ Refresh**.

### Command-line options

| Flag | Default | Description |
|---|---|---|
| `--host` | `127.0.0.1` | Interface to bind. Use `0.0.0.0` to expose on your local network |
| `--port` | `8050` | Port to listen on |
| `--debug` | off | Enable Dash hot-reload (useful during development) |

### Environment variables

```bash
HLEDGER_BIN=/path/to/hledger python app.py
```

The dashboard uses whichever journal hledger loads by default — typically the `LEDGER_FILE` environment variable or `~/.hledger.journal`.

---

## Changing account names

Re-run the account setup at any time without reinstalling:

```bash
./install.sh --reconfigure
```

This re-prompts for all four account names with the current values as defaults and rewrites `config.json`. Restart `app.py` to pick up the changes.

You can also edit `config.json` directly:

```json
{
  "income_account":   "income",
  "expenses_account": "expenses",
  "savings_account":  "assets:bank:savings",
  "debit_account":    "assets:bank:debit"
}
```

---

## Project structure

```
hledger-dashboard/
├── app.py               # Dash application (single file)
├── config.json          # Account names — created by install.sh
├── requirements.txt     # Python dependencies
├── install.sh           # Setup and configuration script
└── assets/
    └── dashboard.css    # Responsive plot sizing — created by install.sh
```

`config.json` and `assets/dashboard.css` are generated files. If you are pushing to a public repository, add `config.json` to `.gitignore` to avoid committing personal account names.

---

## How the Sankey works

hledger uses double-entry accounting, where income is recorded as a negative balance. The dashboard flips income signs before plotting.

The flow modelled is:

```
income:source-a  ──┐
income:source-b  ──┼──► income (total) ──► assets:bank:savings
income:source-c  ──┘         │
                              ├──► expenses:food ──► expenses:food:groceries
                              ├──► expenses:food ──► expenses:food:dining
                              └──► expenses:transport
```

### Debit account reconciliation

A plain `hledger balance income` query covers only what was *received* in the period. If you spent more than you earned — drawing on a prior-period checking balance — or saved more than the income total would suggest, the Sankey's left and right sides would not match.

The dashboard makes a separate call for your debit account using `hledger balance <debit_account> --period <period> --no-total`, and applies the net change as a balancing node:

| Net change | Meaning | Sankey adjustment |
|---|---|---|
| Account shrank | Prior balance was consumed | `debit (prior balance)` → `income (total)` |
| Account grew | Income was retained in checking | `income (total)` → `debit (retained)` |
| No change | Fully accounted for by income | No extra node |

<!-- ### Guardrails

Setting a *To* date without a *From* date is blocked with a warning. `hledger balance --end DATE` returns cumulative totals from the very beginning of the ledger — including opening balances from prior years — rather than the activity within a period. The correct alternatives are to use both a From and To date, or to use the Period dropdown. -->

---

## Notes and limitations

**Single currency** — the amount parser strips currency symbols and commas, then parses the remaining numeric value. Journals with multiple currencies will produce incorrect totals.

**No authentication** — the server is intended for local or trusted-network use only. Do not expose it to the public internet.

**No persistence** — the dashboard holds no state between page loads. Every Refresh is a fresh set of `hledger` subprocess calls.

**Depth and the debit account** — the account depth setting applies to income, expenses, and savings queries. The debit account query intentionally omits the depth flag so it always targets the single named account rather than being rolled up to a parent.

---

## Built with

- [hledger](https://hledger.org) — plain-text accounting
- [Plotly Dash](https://dash.plotly.com) — Python web framework for data apps
- [pandas](https://pandas.pydata.org) — CSV parsing and aggregation
