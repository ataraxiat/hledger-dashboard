# hledger-dashboard

A Dash app over an hledger journal: refresh, charts, and a txcat → `hledger import` pipeline.
Config, journal and rules all resolve through `$ACCOUNTING_DIR` (`~/Accounting/_meta/schema.md`
§ Path rules).

| Task | Go to |
|---|---|
| What anything in `app.py` is, and what changing it hits | `docs/map/CLAUDE.md` |
| Run it | `./install.sh --run`, or `uv run python app.py` |
| Configure it | `config.example.json`; the live file is `$ACCOUNTING_DIR/_config/hledger-dashboard/config.json` |
| What it reads and writes in the data folder | `~/Accounting/ledger/CONTEXT.md`, `~/Accounting/01_inbox/CONTEXT.md` |
| Why there is a map and not a notes file | `git log --oneline -- CLAUDE.md`: the hand-written line table had drifted by ~500 lines |
