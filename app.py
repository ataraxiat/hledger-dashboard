"""
hledger Interactive Dashboard
======================================
Run:  python app.py   →  open http://127.0.0.1:8050

Features
--------
• Sankey — income → savings & expenses (period-aware, debit-account reconciled)
• Monthly trend — grouped bar chart of income vs expenses
• Weekly — small multiples with average reference line
• Weekly — spend heatmap
• Weekly — violin distribution plot (with box, mean line, click-through transactions)
  - Three axis scales: compressed (power), log, linear
  - Click any data-point across all three weekly views for a transaction drill-down
• "From Ledger Start" period that auto-discovers your earliest journal date

Requirements
------------
• hledger on $PATH (or HLEDGER_BIN env var)
• Python packages: dash, plotly, pandas, numpy
• Account names: config.json (created by install.sh)
"""

from __future__ import annotations

import io
import json
import math
import os
import re
import shlex
import subprocess
import threading
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import (
    Dash,
    Input,
    Output,
    State,
    callback_context,
    dcc,
    html,
    no_update,
    set_props,
)
from plotly.subplots import make_subplots

# ── Config


def accounting_dir() -> Path:
    """$ACCOUNTING_DIR, or ~/Accounting when it is unset (schema § Path rules 2)."""
    return Path(os.environ.get("ACCOUNTING_DIR") or Path.home() / "Accounting").expanduser()


def from_config(value: str) -> Path:
    """A path read from config.json: ~ expanded, anything relative taken from $ACCOUNTING_DIR."""
    path = Path(value).expanduser()
    return path if path.is_absolute() else accounting_dir() / path


CONFIG_PATH = accounting_dir() / "_config" / "hledger-dashboard" / "config.json"
JOURNAL = Path(
    os.environ.get("LEDGER_FILE") or accounting_dir() / "ledger" / "journal" / "main.journal"
).expanduser()

CONFIG_DEFAULTS: dict[str, str | int] = {
    "income_account": "income",
    "expenses_account": "expenses",
    "savings_account": "assets:bank:savings",
    "debit_account": "assets:bank:debit",
    # Import pipeline (txcat → hledger import). Relative to $ACCOUNTING_DIR.
    "hledger_rules_debit": "ledger/import/bank.debit.csv.rules",
    "hledger_rules_savings": "ledger/import/bank.savings.csv.rules",
    # Bank website for the "no new transactions" prompt
    "bank_url": "",
    # Per-account txcat bypass
    "skip_txcat_debit": False,
    "skip_txcat_savings": False,
    # UI defaults
    "default_depth": 2,
}


def load_config() -> dict[str, str | int]:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            on_disk = json.load(f)
        # Backwards compat: old key name
        if "hledger_rules" in on_disk and "hledger_rules_debit" not in on_disk:
            on_disk["hledger_rules_debit"] = on_disk.pop("hledger_rules")
        return {**CONFIG_DEFAULTS, **on_disk}
    return dict(CONFIG_DEFAULTS)


CFG = load_config()

# Lookup table for period-dropdown value → human label
PERIOD_LABELS: dict[str, str] = {
    "from": "From Ledger Start",
    "thisyear": "This year",
    "lastyear": "Last year",
    "thisquarter": "This quarter",
    "lastquarter": "Last quarter",
    "thismonth": "This month",
    "lastmonth": "Last month",
    "last12months": "Last 12 months",
}

# ── Colour palette (dark theme) ────────────────────────────────────────────────
COLOR_INCOME = "rgba(112, 148, 255, 0.95)"
COLOR_SAVINGS = "rgba( 50, 230, 170, 0.95)"
COLOR_EXPENSE = "rgba(255, 106,  61, 0.95)"
COLOR_DEBIT = "rgba(200, 160,  80, 0.95)"
COLOR_INCOME_MEDICAL = "rgba(100, 220, 160, 0.95)"
COLOR_EXPENSE_MEDICAL = "rgba(240,  80, 130, 0.95)"
LINK_INCOME = "rgba(110, 160, 255, 0.35)"
LINK_SAVINGS = "rgba( 50, 230, 170, 0.35)"
LINK_EXPENSE = "rgba(255, 110,  90, 0.35)"
LINK_DEBIT = "rgba(200, 160,  80, 0.35)"
FONT_COLOR = "#d8d8d8"
BG = "#151313"
CARD_BG = "#1e1b1b"
BORDER = "#2e2b2b"

# Rotating palette for parent expense categories (violin plot colour-coding).
# All entries use alpha 0.95 so .replace("0.95", "<alpha>") works uniformly.
PARENT_CATEGORY_COLORS = [
    "rgba(100, 160, 255, 0.95)",  # sky blue
    "rgba( 80, 220, 160, 0.95)",  # teal
    "rgba(255, 200,  60, 0.95)",  # amber
    "rgba(200,  90, 255, 0.95)",  # violet
    "rgba( 60, 210, 240, 0.95)",  # cyan
    "rgba(255, 130,  50, 0.95)",  # orange
    "rgba(240,  80, 130, 0.95)",  # rose
    "rgba(120, 240,  90, 0.95)",  # lime
    "rgba(255, 220, 120, 0.95)",  # light gold
    "rgba(150, 130, 255, 0.95)",  # lavender
    "rgba( 90, 200, 200, 0.95)",  # sea-green
    "rgba(255, 160, 180, 0.95)",  # salmon
]

HLEDGER_BIN = os.environ.get("HLEDGER_BIN", "hledger")


def hledger_cmd(*args: str) -> list[str]:
    """Every hledger call names its journal and ignores config files.

    schema § Path rules 5: there is no hledger.conf, and $LEDGER_FILE may be unset when the app is
    launched from Finder or a bare environment. -n is --no-conf on hledger 1.52.1.
    """
    return [HLEDGER_BIN, "-n", "-f", str(JOURNAL), *args]

# ── Weekly plot formatting ─────────────────────────────────────────────────────
WEEKLY_TITLE_FONT = dict(size=16, color=FONT_COLOR, weight="bold")
WEEKLY_AX_TITLE_FONT = dict(size=15, color=FONT_COLOR)
WEEKLY_TICK_FONT = dict(size=14, color=FONT_COLOR)
WEEKLY_SMALL_TICK_FONT = dict(size=12, color=FONT_COLOR)


# ── Data helpers ───────────────────────────────────────────────────────────────


def parse_amount(raw: str) -> float:
    """Convert hledger balance strings like '£1,234.56' or '-USD 42' to float."""
    cleaned = re.sub(r"[^\d.\-]", "", str(raw).strip())
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def normalise(df: pd.DataFrame, flip_sign: bool = False) -> pd.DataFrame:
    """Return a tidy (account, amount) frame with non-zero rows only."""
    if df.empty:
        return pd.DataFrame(columns=["account", "amount"])
    col_map = {c.lower(): c for c in df.columns}
    acct_col = col_map.get("account", df.columns[0])
    bal_col = col_map.get("balance", df.columns[-1])
    out = df[[acct_col, bal_col]].copy()
    out.columns = ["account", "amount"]
    out["amount"] = out["amount"].apply(parse_amount)
    if flip_sign:
        out["amount"] = -out["amount"]
    return out[out["amount"] != 0].reset_index(drop=True)


def run_hledger(
    args: list[str],
    period_args: list[str],
    depth: int | None = None,
    monthly: bool = False,
) -> tuple[pd.DataFrame, str]:
    """
    Run hledger and return (DataFrame, command_string).
    depth=None omits the -N depth flag (single named-account queries).
    """
    depth_flag = [f"-{depth}"] if depth is not None else []
    extra = ["--monthly"] if monthly else []
    cmd = (
        hledger_cmd(*args)
        + period_args
        + depth_flag
        + ["--no-total", "-O", "csv"]
        + extra
    )
    cmd_str = "▶ " + " ".join(cmd)
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        return pd.DataFrame(), f"{cmd_str}\n⚠ Error: {r.stderr.strip()}"
    try:
        df = pd.read_csv(io.StringIO(r.stdout))
    except Exception as exc:
        return pd.DataFrame(), f"{cmd_str}\n⚠ Parse error: {exc}"
    return df, cmd_str


def get_ledger_start_date() -> str | None:
    """
    Return the date of the second transaction in the default journal as YYYY-MM-DD,
    skipping the first entry (which sets opening balances).  Returns None on failure.
    """
    r = subprocess.run(hledger_cmd("print"), capture_output=True, text=True)
    if r.returncode != 0:
        return None
    dates = []
    for line in r.stdout.splitlines():
        m = re.match(r"^(\d{4}-\d{2}-\d{2})", line)
        if m:
            dates.append(m.group(1))
            if len(dates) == 2:
                return dates[1]
    return None


_import_lock = threading.Lock()

# Shared state written by the background import thread, read by the poll callback.
# CPython's GIL makes list.append / bool assignment atomic enough for this pattern.
_import_log: list[str] = []
_import_done: bool = False
_import_no_new_tx: bool = False
_import_result: dict = {}  # "component.prop" -> value, populated when done

_NO_NEW_TX_MARKERS = (
    "No new CSVs found — nothing to do.",
    "No files were processed.",
    "no new transactions found in",
)


def _stream_import(
    source: str, period_args: list[str], depth: int, period_label: str
) -> None:
    """
    Run the import pipeline in a background thread.  Progress is written to the
    module-level _import_log list; the poll_import callback reads it every 400 ms.
    source is "debit" or "savings".
    """
    global _import_done, _import_no_new_tx, _import_result

    rules = str(from_config(CFG[f"hledger_rules_{source}"]))
    skip_txcat = bool(CFG.get(f"skip_txcat_{source}", False))

    steps = []
    if not skip_txcat:
        # txcat finds its own config through $ACCOUNTING_DIR, so it needs no cwd of its own.
        steps.append((["txcat", "auto", "--source", source], None))
    steps.append((hledger_cmd("import", rules), None))

    _import_log.append(f"Starting import from {source}…")
    aborted = False
    child_env = {**os.environ, "PYTHONUNBUFFERED": "1"}

    try:
        for cmd, cwd in steps:
            _import_log.append("▶ " + " ".join(cmd))
            try:
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    cwd=cwd,
                    env=child_env,
                )
            except (FileNotFoundError, OSError) as exc:
                _import_log.append(f"⚠ Could not start process: {exc}")
                aborted = True
                break

            while True:
                raw_line = proc.stdout.readline()
                if not raw_line:
                    break
                stripped = raw_line.rstrip()
                if any(m in stripped for m in _NO_NEW_TX_MARKERS):
                    _import_no_new_tx = True
                _import_log.append(stripped)

            proc.wait()
            if proc.returncode != 0:
                _import_log.append(
                    f"⚠ Process exited {proc.returncode} — import aborted."
                )
                aborted = True
                break
    finally:
        _import_lock.release()

    if aborted or _import_no_new_tx:
        _import_done = True
        return

    # ── Refresh all graphs after a successful import ───────────────────────────
    _import_log.append("\n↻ Refreshing charts…")

    inc_acct = CFG["income_account"]
    exp_acct = CFG["expenses_account"]
    sav_acct = CFG["savings_account"]
    deb_acct = CFG["debit_account"]

    inc_raw, l1 = run_hledger(["bal", inc_acct], period_args, depth)
    exp_raw, l2 = run_hledger(["bal", exp_acct], period_args, depth)
    sav_raw, l3 = run_hledger(["bal", sav_acct], period_args, depth)
    deb_raw, l4 = run_hledger(["bal", deb_acct], period_args, depth=None)
    for entry in (l1, l2, l3, l4):
        _import_log.append(entry)

    inc_df = normalise(inc_raw, flip_sign=True)
    exp_df = normalise(exp_raw, flip_sign=False)
    sav_df = normalise(sav_raw, flip_sign=False)
    deb_df = normalise(deb_raw, flip_sign=False)

    debit_change = float(deb_df["amount"].sum()) if not deb_df.empty else 0.0

    if inc_df.empty and exp_df.empty:
        sankey_fig = empty_sankey_figure(
            "No income / expense data returned.\n"
            "Check that hledger is on $PATH and your journal has transactions."
        )
    else:
        sb = build_sankey(inc_df, exp_df, sav_df, debit_change, deb_acct)
        pd_data = sb.to_plotly(node_colors=getattr(sb, "_node_colors", None))
        sankey_fig = go.Figure(
            data=[go.Sankey(arrangement="snap", **pd_data)],
            layout=dark_layout(
                f"Income → Savings & Expenses  [{period_label}, depth {depth}]"
            ),
        )

    inc_med_acct = inc_acct + ":medical"
    exp_med_acct = exp_acct + ":medical"
    inc_m_raw, _ = run_hledger(["bal", inc_acct], period_args, depth, monthly=True)
    exp_m_raw, _ = run_hledger(["bal", exp_acct], period_args, depth, monthly=True)
    inc_med_m_raw, _ = run_hledger(
        ["bal", inc_med_acct], period_args, depth=None, monthly=True
    )
    exp_med_m_raw, _ = run_hledger(
        ["bal", exp_med_acct], period_args, depth=None, monthly=True
    )

    if inc_m_raw.empty or exp_m_raw.empty:
        bar_fig = empty_bar_figure("No monthly data available for this period.")
    else:
        try:
            s_income = pivot_monthly(inc_m_raw, flip=True)
            s_expenses = pivot_monthly(exp_m_raw, flip=False)
            s_inc_medical = (
                pivot_monthly(inc_med_m_raw, flip=True)
                if not inc_med_m_raw.empty
                else pd.Series(0.0, index=s_income.index)
            )
            s_exp_medical = (
                pivot_monthly(exp_med_m_raw, flip=False)
                if not exp_med_m_raw.empty
                else pd.Series(0.0, index=s_expenses.index)
            )
            bar_fig = build_monthly_bar_figure(
                s_income, s_inc_medical, s_expenses, s_exp_medical, period_label
            )
        except Exception as exc:
            bar_fig = empty_bar_figure(f"Error building trend chart: {exc}")

    weekly_raw, _ = run_hledger_weekly(exp_acct, period_args, depth)
    weekly_data = parse_weekly_data(weekly_raw)
    sm_fig, sm_style = build_small_multiples_figure(weekly_data, period_label)
    hm_fig = build_heatmap_figure(weekly_data, period_label)

    reg_txns, reg_cmd = run_hledger_register_full(exp_acct, period_args)
    register_data = {"txns": reg_txns, "cmd": reg_cmd}

    _import_log.append("✓ Charts updated after import")
    _import_result = {
        "sankey-graph.figure": sankey_fig,
        "bar-graph.figure": bar_fig,
        "sm-graph.figure": sm_fig,
        "sm-graph.style": sm_style,
        "hm-graph.figure": hm_fig,
        "strip-data-store.data": weekly_data,
        "register-data-store.data": register_data,
        "strip-parent-filter.data": [],
    }
    _import_done = True


# ── Weekly expense helpers ─────────────────────────────────────────────────────


def week_col_to_date(col: str, to_iso: bool = False) -> str:
    """
    Bidirectional normaliser for hledger weekly column headers.

    to_iso=False (default)  →  'YYYY-MM-DD'
        'YYYY-Www' input: resolved to the Monday of that ISO week.
        'YYYY-MM-DD' input: returned unchanged (trimmed to 10 chars).

    to_iso=True             →  'YY-Www'
        'YYYY-MM-DD' input: converted to ISO week label for axis display.
        'YYYY-Www' input: returned unchanged.
    """
    s = str(col).strip()
    if to_iso:
        if re.match(r"^\d{4}-W\d{2}$", s):
            return datetime.strptime(s + "-1", "%G-W%V-%u").strftime("%g-W%V")
        try:
            return datetime.strptime(s[:10], "%Y-%m-%d").strftime("%g-W%V")
        except ValueError:
            return s
    else:
        if re.match(r"^\d{4}-W\d{2}$", s):
            try:
                return datetime.strptime(s + "-1", "%G-W%V-%u").strftime("%Y-%m-%d")
            except ValueError:
                return s
        return s[:10]


def run_hledger_weekly(
    account: str,
    period_args: list[str],
    depth: int = 3,
) -> tuple[pd.DataFrame, str]:
    """Run hledger balance with --weekly --average for one account prefix."""
    cmd = (
        hledger_cmd("bal", account)
        + period_args
        + [f"-{depth}", "--weekly", "--average", "--no-total", "-O", "csv"]
    )
    cmd_str = "▶ " + " ".join(cmd)
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        return pd.DataFrame(), f"{cmd_str}\n⚠ Error: {r.stderr.strip()}"
    try:
        df = pd.read_csv(io.StringIO(r.stdout))
    except Exception as exc:
        return pd.DataFrame(), f"{cmd_str}\n⚠ Parse error: {exc}"
    return df, cmd_str


def parse_weekly_data(df: pd.DataFrame) -> dict:
    """
    Parse a hledger weekly balance CSV (--weekly --average) into a dict:
        account → {
            "weeks":      ["DD Mon", ...],   # display labels
            "week_dates": ["YYYY-MM-DD", ...], # original start dates for register queries
            "amounts":    [float, ...],
            "average":    float,
        }
    """
    if df.empty:
        return {}
    cols = list(df.columns)
    avg_col = next((c for c in cols if c.lower().strip() == "average"), None)
    wk_cols = [c for c in cols if c != "account" and c != avg_col]

    result: dict = {}
    for _, row in df.iterrows():
        acct = str(row["account"]).strip()
        amounts = [parse_amount(row[c]) for c in wk_cols]
        avg = (
            parse_amount(row[avg_col])
            if avg_col
            else (sum(amounts) / len(amounts) if amounts else 0.0)
        )
        result[acct] = {
            "weeks": [week_col_to_date(c, to_iso=True) for c in wk_cols],
            "week_dates": [week_col_to_date(c) for c in wk_cols],
            "amounts": amounts,
            "average": avg,
        }
    return result


def run_hledger_register_full(
    account: str,
    period_args: list[str],
) -> tuple[list[dict], str]:
    """
    Fetch all register entries for an account prefix over the given period.
    Returns (list_of_transaction_dicts, command_string).
    Each dict: {date, description, account, amount}.
    No depth flag — we want full transaction detail.
    """
    cmd = hledger_cmd("register", account) + period_args + ["-O", "csv"]
    cmd_str = "▶ " + " ".join(cmd)
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        return [], f"{cmd_str}\n⚠ Error: {r.stderr.strip()}"
    try:
        df = pd.read_csv(io.StringIO(r.stdout))
    except Exception as exc:
        return [], f"{cmd_str}\n⚠ Parse error: {exc}"

    if df.empty:
        return [], cmd_str

    txns = []
    for _, row in df.iterrows():
        txns.append({
            "date": str(row.get("date", "")),
            "description": str(row.get("description", "")),
            "account": str(row.get("account", "")),
            "amount": parse_amount(str(row.get("amount", "0"))),
        })
    return txns, cmd_str


def filter_register_data(
    txns: list[dict],
    account: str,
    week_date: str,
) -> list[dict]:
    """
    Filter pre-fetched register rows to those matching `account` (prefix) and
    the 7-day window starting on `week_date` (YYYY-MM-DD).
    """
    try:
        week_start = datetime.strptime(week_date, "%Y-%m-%d").date()
    except ValueError:
        return []
    week_end = week_start + timedelta(days=7)

    result = []
    for t in txns:
        acct = t.get("account", "")
        if acct != account and not acct.startswith(account + ":"):
            continue
        try:
            d = datetime.strptime(t.get("date", ""), "%Y-%m-%d").date()
        except ValueError:
            continue
        if week_start <= d < week_end:
            result.append(t)
    return result


def render_tx_table(txns: list[dict]) -> html.Div:
    """Render a list of transaction dicts as a styled HTML table."""
    if not txns:
        return html.P(
            "No transactions found for this week / category.",
            style={"color": "#999", "fontSize": "13px", "margin": "8px 0"},
        )

    total = sum(t["amount"] for t in txns)

    th_style = {
        "padding": "5px 10px",
        "color": "#888",
        "fontSize": "11px",
        "textAlign": "left",
        "borderBottom": f"1px solid {BORDER}",
        "fontWeight": "400",
    }
    td_style = {"padding": "4px 10px", "fontSize": "12px", "color": FONT_COLOR}
    amt_td = {
        **td_style,
        "textAlign": "right",
        "color": COLOR_EXPENSE,
        "fontFamily": "monospace",
    }

    rows = [
        html.Tr([
            html.Td(t["date"], style=td_style),
            html.Td(t["description"], style=td_style),
            html.Td(
                t["account"].split(":")[-1],
                style={**td_style, "color": "#999", "fontSize": "11px"},
            ),
            html.Td(f"${t['amount']:,.2f}", style=amt_td),
        ])
        for t in txns
    ]
    rows.append(
        html.Tr([
            html.Td("", colSpan=3),
            html.Td(
                f"Total  ${total:,.2f}",
                style={
                    **amt_td,
                    "color": FONT_COLOR,
                    "fontWeight": "600",
                    "fontSize": "13px",
                    "borderTop": f"1px solid {BORDER}",
                },
            ),
        ])
    )

    return html.Table(
        [
            html.Thead(
                html.Tr([
                    html.Th("Date", style=th_style),
                    html.Th("Description", style=th_style),
                    html.Th("Account", style=th_style),
                    html.Th("Amount", style={**th_style, "textAlign": "right"}),
                ])
            ),
            html.Tbody(rows),
        ],
        style={"width": "100%", "borderCollapse": "collapse"},
    )


# ── Sankey builder ─────────────────────────────────────────────────────────────


class SankeyBuilder:
    """Incrementally collect nodes and links for a Plotly Sankey trace."""

    def __init__(self) -> None:
        self._nodes: list[str] = []
        self._idx: dict[str, int] = {}
        self.links: list[dict] = []

    def node(self, label: str) -> int:
        if label not in self._idx:
            self._idx[label] = len(self._nodes)
            self._nodes.append(label)
        return self._idx[label]

    @property
    def node_labels(self) -> list[str]:
        return [n.split(":")[-1] if ":" in n else n for n in self._nodes]

    @property
    def node_full_labels(self) -> list[str]:
        return list(self._nodes)

    def link(
        self,
        source: str,
        target: str,
        value: float,
        color: str = "rgba(160,160,200,0.4)",
    ) -> None:
        if value <= 0:
            return
        self.links.append(
            dict(
                source=self.node(source),
                target=self.node(target),
                value=round(value, 2),
                color=color,
            )
        )

    def to_plotly(self, node_colors: list[str] | None = None) -> dict:
        n = len(self._nodes)
        colors = node_colors or ["#636EFA"] * n
        return dict(
            node=dict(
                label=self.node_labels,
                customdata=self.node_full_labels,
                hovertemplate="%{customdata}<br>%{value:,.2f}<extra></extra>",
                color=colors,
                pad=20,
                thickness=18,
            ),
            link=dict(
                source=[lk["source"] for lk in self.links],
                target=[lk["target"] for lk in self.links],
                value=[lk["value"] for lk in self.links],
                color=[lk["color"] for lk in self.links],
                hovertemplate=(
                    "%{source.customdata} → %{target.customdata}"
                    "<br>%{value:,.2f}<extra></extra>"
                ),
            ),
        )


def build_sankey(
    income_df: pd.DataFrame,
    expenses_df: pd.DataFrame,
    savings_df: pd.DataFrame,
    debit_change: float = 0.0,
    debit_account: str = "",
) -> SankeyBuilder:
    """
    Build the full Sankey node/link graph.
    debit_change > 0 → income retained in checking (outflow from income total)
    debit_change < 0 → prior balance consumed (inflow to income total)
    """
    sb = SankeyBuilder()
    TOTAL_INCOME = "income (total)"

    for _, row in income_df.iterrows():
        sb.link(row["account"], TOTAL_INCOME, row["amount"], LINK_INCOME)

    debit_label_in = f"{debit_account} (prior balance)"
    debit_label_out = f"{debit_account} (retained)"
    if debit_change < 0:
        sb.link(debit_label_in, TOTAL_INCOME, abs(debit_change), LINK_DEBIT)
    elif debit_change > 0:
        sb.link(TOTAL_INCOME, debit_label_out, debit_change, LINK_DEBIT)

    savings_acct = CFG["savings_account"]
    total_savings = savings_df["amount"].sum()
    if total_savings > 0:
        if len(savings_df) > 1:
            sb.link(TOTAL_INCOME, savings_acct, total_savings, LINK_SAVINGS)
            for _, row in savings_df.iterrows():
                sb.link(savings_acct, row["account"], row["amount"], LINK_SAVINGS)
        else:
            sb.link(
                TOTAL_INCOME, savings_df.iloc[0]["account"], total_savings, LINK_SAVINGS
            )

    def depth2(acct: str) -> str:
        parts = acct.split(":")
        return ":".join(parts[:2]) if len(parts) >= 2 else acct

    if not expenses_df.empty:
        exp = expenses_df.copy()
        exp["parent"] = exp["account"].apply(depth2)
        for parent, subtotal in exp.groupby("parent")["amount"].sum().items():
            sb.link(TOTAL_INCOME, parent, subtotal, LINK_EXPENSE)
        for _, row in exp.iterrows():
            if row["account"] != row["parent"]:
                sb.link(row["parent"], row["account"], row["amount"], LINK_EXPENSE)

    income_pfx = CFG["income_account"]
    savings_pfx = CFG["savings_account"].split(":")[0]
    expenses_pfx = CFG["expenses_account"]

    node_colors = []
    for label in sb.node_full_labels:
        if label.startswith(income_pfx) or label == TOTAL_INCOME:
            node_colors.append(COLOR_INCOME)
        elif label.startswith(savings_pfx):
            node_colors.append(COLOR_SAVINGS)
        elif label.startswith(expenses_pfx):
            node_colors.append(COLOR_EXPENSE)
        else:
            node_colors.append(COLOR_DEBIT)

    sb._node_colors = node_colors  # type: ignore[attr-defined]
    return sb


# ── Plotly figure helpers ──────────────────────────────────────────────────────


def dark_layout(
    title: str, height: int | None = None, autosize: bool = True, **kwargs
) -> go.Layout:
    return go.Layout(
        title=dict(text=title, font=dict(size=18, color=FONT_COLOR)),
        font=dict(family="Inter, Arial, sans-serif", size=12, color=FONT_COLOR),
        autosize=autosize,
        **({"height": height} if height is not None else {}),
        margin=dict(l=48, r=48, t=64, b=48, pad=2),
        paper_bgcolor=BG,
        plot_bgcolor=BG,
        **kwargs,
    )


def empty_sankey_figure(message: str = "Click Refresh to load data") -> go.Figure:
    fig = go.Figure(layout=dark_layout("Income → Savings & Expenses"))
    fig.add_annotation(
        text=message,
        x=0.5,
        y=0.5,
        xref="paper",
        yref="paper",
        showarrow=False,
        font=dict(size=16, color=FONT_COLOR),
    )
    return fig


def empty_bar_figure(message: str = "Click Refresh to load data") -> go.Figure:
    fig = go.Figure(layout=dark_layout("Monthly Income vs Expenses"))
    fig.add_annotation(
        text=message,
        x=0.5,
        y=0.5,
        xref="paper",
        yref="paper",
        showarrow=False,
        font=dict(size=16, color=FONT_COLOR),
    )
    return fig


def pivot_monthly(df: pd.DataFrame, flip: bool = False) -> pd.Series:
    """Collapse a monthly hledger CSV into a Series indexed by month label."""
    month_cols = [c for c in df.columns if c not in ("account", "total")]
    totals = df[month_cols].apply(lambda col: col.map(parse_amount)).sum()
    return -totals if flip else totals


def build_monthly_bar_figure(
    s_income: pd.Series,
    s_inc_medical: pd.Series,
    s_expenses: pd.Series,
    s_exp_medical: pd.Series,
    period_label: str,
) -> go.Figure:
    """
    Grouped bar chart with stacked segments.
    Income: medical on bottom, other on top.
    Expenses: medical on bottom, other on top.
    Uses offsetgroup + base so the two groups sit side by side.
    """
    months = s_income.index.tolist()
    s_inc_medical = s_inc_medical.reindex(s_income.index, fill_value=0.0)
    s_inc_other = s_income - s_inc_medical
    s_exp_medical = s_exp_medical.reindex(s_expenses.index, fill_value=0.0)
    s_exp_other = s_expenses - s_exp_medical
    return go.Figure(
        data=[
            go.Bar(
                name="Income (medical)",
                x=months,
                y=s_inc_medical.values,
                marker_color=COLOR_INCOME_MEDICAL,
                offsetgroup="income",
            ),
            go.Bar(
                name="Income (other)",
                x=months,
                y=s_inc_other.values,
                marker_color=COLOR_INCOME,
                offsetgroup="income",
            ),
            go.Bar(
                name="Expenses (medical)",
                x=months,
                y=s_exp_medical.values,
                marker_color=COLOR_EXPENSE_MEDICAL,
                offsetgroup="expenses",
            ),
            go.Bar(
                name="Expenses (other)",
                x=months,
                y=s_exp_other.values,
                marker_color=COLOR_EXPENSE,
                offsetgroup="expenses",
            ),
        ],
        layout=dark_layout(
            f"Monthly Income vs Expenses  [{period_label}]",
            barmode="stack",
            xaxis=dict(
                title="Month", color=FONT_COLOR, gridcolor=BORDER, linecolor=BORDER
            ),
            yaxis=dict(
                title="Amount", color=FONT_COLOR, gridcolor=BORDER, linecolor=BORDER
            ),
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1,
                font=dict(color=FONT_COLOR),
            ),
        ),
    )


def _weekly_empty(title: str, msg: str) -> go.Figure:
    fig = go.Figure(layout=dark_layout(title, height=480))
    fig.add_annotation(
        text=msg,
        x=0.5,
        y=0.5,
        xref="paper",
        yref="paper",
        showarrow=False,
        font=dict(size=14, color=FONT_COLOR),
    )
    return fig


def empty_sm_figure(msg: str = "Click Refresh to load data") -> go.Figure:
    return _weekly_empty("Weekly expenses by category", msg)


def empty_hm_figure(msg: str = "Click Refresh to load data") -> go.Figure:
    return _weekly_empty("Spend heatmap", msg)


def empty_strip_figure(msg: str = "Click Refresh to load data") -> go.Figure:
    return _weekly_empty("Weekly distribution", msg)


# ── Weekly figure builders ─────────────────────────────────────────────────────


def build_small_multiples_figure(
    weekly_data: dict, period_label: str, plot_w: int = 1200
) -> go.Figure:
    """
    One bar-chart panel per expense sub-category.
    Bars = weekly spend; dashed line = period average.
    customdata on each bar carries the original week date (YYYY-MM-DD) so
    click callbacks can resolve the correct register query.
    """
    if not weekly_data:
        return empty_sm_figure("No weekly expense data for this period.")

    cats = list(weekly_data.keys())
    n = len(cats)

    # Sort by max spend descending so rows group categories of similar scale
    cat_max = {cat: max(weekly_data[cat]["amounts"], default=0) for cat in cats}
    cats = sorted(cats, key=lambda c: cat_max[c], reverse=True)

    # ── Font geometry (Plotly has no Python API for text pixel sizes; these are
    # estimates for Inter/Arial using 0.55× font-size per character) ───────────
    _ASPECT_RATIO = 1.0  # W:H per subplot (1 = square)
    _tick_fs = WEEKLY_SMALL_TICK_FONT["size"]  # 12 px
    _title_fs = WEEKLY_AX_TITLE_FONT["size"]  # 15 px
    _ang = math.radians(35)
    _lbl_w = 7 * 0.55 * _tick_fs  # "YY-Www" width ≈ 46 px
    _lbl_h = _tick_fs * 1.2  # cap height ≈ 14 px
    _tick_h_span = _lbl_w * math.cos(_ang) + _lbl_h * math.sin(_ang)  # ≈ 46 px
    _tick_v_drop = _lbl_w * math.sin(_ang) + _lbl_h * math.cos(_ang)  # ≈ 38 px

    # ── Inter-column gap ──────────────────────────────────────────────────────
    # Each side of a column boundary contributes ≈½ label-width; margin so labels
    # from adjacent columns don't overlap.
    _h_gap_px = int(_tick_h_span * 1)  # ≈

    # ── Minimum subplot width: fit ≥ 4 tick labels side-by-side ──────────────
    _min_sw = int(4 * _tick_h_span) + 20  # ≈ 204 px

    # ── Column count: ceil(√n) targets a square grid ──────────────────────────
    # Scoring functions (e.g. 2×empty − n_cols) fail for numbers that happen to
    # divide evenly by 2 (like 22): 22÷2=11 rows with 0 waste beats any 3-col
    # option that has 2 empty cells, giving a pathological 2×11 grid.
    _max_cols = max(1, min(n, int((plot_w + _h_gap_px) / (_min_sw + _h_gap_px))))
    n_cols = min(_max_cols, max(1, math.ceil(math.sqrt(n))))
    n_rows = math.ceil(n / n_cols)

    # ── Subplot dimensions ────────────────────────────────────────────────────
    subplot_w = (plot_w - (n_cols - 1) * _h_gap_px) / max(n_cols, 1)
    subplot_h = subplot_w / _ASPECT_RATIO
    # horizontal_spacing is normalised to total plot-area width (Plotly convention)
    _h_spacing = (_h_gap_px / plot_w) if n_cols > 1 else 0.0

    # ── Vertical spacing: gap must clear tick-label drop + subplot title ───────
    _gap_px = _tick_v_drop + _title_fs * 1.5 + 6  # ≈ 67 px
    _vs = max(0.02, _gap_px / max(n_rows * subplot_h, 1))

    # ── Figure height ─────────────────────────────────────────────────────────
    _plot_area_h = n_rows * subplot_h / max(1.0 - (n_rows - 1) * _vs, 0.1)
    fig_height = int(_plot_area_h) + 140
    short_names = [c.split(":")[-1] for c in cats]

    fig = make_subplots(
        rows=n_rows,
        cols=n_cols,
        subplot_titles=short_names,
        shared_xaxes=False,
        shared_yaxes=True,
        vertical_spacing=_vs,
        horizontal_spacing=_h_spacing,
    )

    for i, (cat, short) in enumerate(zip(cats, short_names)):
        r = i // n_cols + 1
        c = i % n_cols + 1
        info = weekly_data[cat]
        avg = info["average"]
        week_dates = info.get("week_dates", info["weeks"])

        fig.add_trace(
            go.Bar(
                x=info["weeks"],
                y=info["amounts"],
                customdata=week_dates,
                marker=dict(color=COLOR_EXPENSE, opacity=0.75),
                showlegend=(i == 0),
                name="weekly spend",
                legendgroup="spend",
                hovertemplate="%{x}: $%{y:.0f}<extra></extra>",
            ),
            row=r,
            col=c,
        )

        fig.add_trace(
            go.Scatter(
                x=info["weeks"],
                y=[avg] * len(info["weeks"]),
                mode="lines",
                line=dict(color="#3b6fd4", width=1.5, dash="dash"),
                showlegend=(i == 0),
                name="period avg",
                legendgroup="avg",
                hovertemplate=f"avg: ${avg:.0f}<extra></extra>",
            ),
            row=r,
            col=c,
        )

    # ── Per-row shared y-axis range ──────────────────────────────────────────
    # Categories are sorted by max spend, so each row spans a similar scale.
    # Set an identical range for every subplot in the row so tick labels appear
    # only on the leftmost cell without overlapping its neighbours.
    for _r in range(n_rows):
        _row_cats = cats[_r * n_cols : (_r + 1) * n_cols]
        _row_max = max((cat_max[c] for c in _row_cats), default=0) * 1.1 or 1
        for _c in range(1, len(_row_cats) + 1):
            fig.update_yaxes(range=[0, _row_max], row=_r + 1, col=_c)

    fig.update_annotations(font=WEEKLY_AX_TITLE_FONT)
    fig.update_xaxes(
        tickfont=WEEKLY_SMALL_TICK_FONT,
        tickangle=35,
        gridcolor=BORDER,
        linecolor=BORDER,
        showgrid=True,
    )
    fig.update_yaxes(
        tickfont=WEEKLY_SMALL_TICK_FONT,
        gridcolor=BORDER,
        linecolor=BORDER,
        tickprefix="$",
        # automargin=True,
    )
    fig.update_layout(
        title=dict(
            text=f"Weekly expenses by category — {period_label}",
            font=WEEKLY_TITLE_FONT,
        ),
        height=fig_height,
        paper_bgcolor=BG,
        plot_bgcolor=BG,
        font=dict(family="Inter, Arial, sans-serif"),  # size=10, color=FONT_COLOR
        margin=dict(r=0, t=64),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.01,
            xanchor="right",
            x=1,
            font=dict(color=FONT_COLOR, size=11),
            bgcolor="rgba(0,0,0,0)",
        ),
    )
    sm_style = {"width": "100%", "aspectRatio": f"{plot_w} / {fig_height}"}
    return fig, sm_style


def build_heatmap_figure(weekly_data: dict, period_label: str) -> go.Figure:
    """
    Categories as rows (sorted by average descending), weeks as columns.
    Colour intensity = spend amount.  customtext carries original week dates.
    """
    if not weekly_data:
        return empty_hm_figure("No weekly expense data for this period.")

    cats = sorted(
        weekly_data.keys(), key=lambda c: weekly_data[c]["average"], reverse=True
    )
    weeks = weekly_data[cats[0]]["weeks"]
    n_wks = len(weeks)
    short_y = [c.split(":")[-1] for c in cats]

    z = [
        [
            weekly_data[c]["amounts"][i] if i < len(weekly_data[c]["amounts"]) else 0.0
            for i in range(n_wks)
        ]
        for c in cats
    ]

    # Store week dates in customdata matrix for click-through
    week_dates_row = weekly_data[cats[0]].get("week_dates", weeks)
    customdata = [week_dates_row for _ in cats]

    height = max(320, len(cats) * 40 + 160)

    fig = go.Figure(
        go.Heatmap(
            z=z,
            x=weeks,
            y=short_y,
            zmin=0,
            customdata=customdata,
            colorscale=[
                [0.000, "#151313"],
                [0.001, "#2c1a15"],
                [0.200, "#7a3020"],
                [0.600, "#c05030"],
                [1.000, "#ff7050"],
            ],
            showscale=True,
            colorbar=dict(
                title=dict(text="($)", font=WEEKLY_AX_TITLE_FONT),
                tickfont=WEEKLY_TICK_FONT,
                bgcolor=CARD_BG,
                bordercolor=BORDER,
                borderwidth=1,
                len=0.8,
                tickprefix="$",
            ),
            hovertemplate="%{y} — %{x}<br>$%{z:,.0f}<extra></extra>",
        )
    )

    fig.update_layout(
        title=dict(text=f"Spend heatmap — {period_label}", font=WEEKLY_TITLE_FONT),
        height=height,
        paper_bgcolor=BG,
        plot_bgcolor=BG,
        font=dict(family="Inter, Arial, sans-serif"),  # size=11, color=FONT_COLOR
        margin=dict(l=110, r=80, t=64, b=80),
        xaxis=dict(
            tickfont=WEEKLY_TICK_FONT,
            gridcolor=BORDER,
            linecolor=BORDER,
            tickangle=35,
            side="bottom",
        ),
        yaxis=dict(tickfont=WEEKLY_TICK_FONT, autorange="reversed"),
    )
    return fig


def build_strip_figure(
    weekly_data: dict,
    period_label: str,
    orientation: str = "v",
    scale_mode: str = "linear",
    hidden_parents: list | None = None,
) -> go.Figure:
    """
    Violin plot — one trace per expense sub-category (sorted by average descending).
    Each violin shows: distribution shape, embedded IQR box, mean line, all data points.

    scale_mode:
        "transform" — symmetric power transform (POWER=0.3).  Compresses outliers
                      while preserving the visual shape of skewed distributions.
                      Custom ticks show dollar values; box-stats hover suppressed on
                      transformed axes (stats would be meaningless transformed numbers).
        "log"       — log₁₀ transform.  Useful when data spans several orders of
                      magnitude.  Ticks labeled $1/$10/$100/$1k etc.
                      Box-stats hover suppressed for same reason as above.
        "linear"    — no transform.  Box-stats hover shows actual $ values.

    Statistical integrity notes:
    • Zeros (weeks with no spend) are excluded before building each violin. They
      represent absent transactions, not genuine $0 events, and would bias the
      distribution toward zero.
    • The IQR box and mean line positions are computed by Plotly on the *plotted*
      values.  For non-linear modes these are in transform-space, which would make
      the box-hover tooltips show nonsensical numbers (the bug).  Fix: suppress box
      hover for non-linear modes via hoveron="points"; individual point hover always
      shows original $ via customdata.
    • customdata per point: [original_amount, week_label, week_date_ISO]
      This lets click callbacks identify the exact week for a transaction drill-down.
    """
    if not weekly_data:
        return empty_strip_figure("No weekly expense data for this period.")

    cats = sorted(
        weekly_data.keys(), key=lambda c: weekly_data[c]["average"], reverse=True
    )

    # ── Parent-category colour mapping ─────────────────────────────────────────
    # The expenses account prefix has N parts; the next segment is the "parent".
    # e.g.  expenses_account="expenses"  →  "expenses:food:groceries" → parent "food"
    _exp_depth = len(CFG["expenses_account"].split(":"))

    def _get_parent(cat: str) -> str:
        parts = cat.split(":")
        return parts[_exp_depth] if len(parts) > _exp_depth else parts[-1]

    # Build parent list from ALL categories before filtering so hidden parents
    # still appear in the legend and can be clicked again to restore them.
    _parents_ordered: list[str] = list(dict.fromkeys(_get_parent(c) for c in cats))
    _parent_color: dict[str, str] = {
        p: PARENT_CATEGORY_COLORS[i % len(PARENT_CATEGORY_COLORS)]
        for i, p in enumerate(_parents_ordered)
    }

    # ── Filter to visible categories ───────────────────────────────────────────
    # Exclude categories whose parent is in hidden_parents. Hidden parents remain
    # in the legend so the user can click to restore them. Axis labels and plot
    # space for hidden categories are eliminated entirely (not just `legendonly`)
    # so the remaining categories reflow to fill the available space.
    hidden_set = set(hidden_parents or [])
    if hidden_set:
        _visible = [c for c in cats if _get_parent(c) not in hidden_set]
        cats = _visible if _visible else cats  # never leave the plot empty

    short_names = [c.split(":")[-1] for c in cats]

    # ── Transform helpers ──────────────────────────────────────────────────────
    POWER = 0.3

    if scale_mode == "transform":

        def fwd(x):
            x = np.asarray(x, dtype=float)
            return np.sign(x) * np.abs(x) ** POWER

        def inv(t):
            t = np.asarray(t, dtype=float)
            return np.sign(t) * np.abs(t) ** (1.0 / POWER)

        use_nonlinear = True
        scale_label = " <i>(compressed axis)</i>"

    elif scale_mode == "log":

        def fwd(x):
            x = np.asarray(x, dtype=float)
            # Clamp to min $0.01 to avoid log(0); spending should always be >0
            return np.log10(np.maximum(x, 0.01))

        def inv(t):
            return 10.0 ** np.asarray(t, dtype=float)

        use_nonlinear = True
        scale_label = " <i>(log axis)</i>"

    else:  # "linear"

        def fwd(x):
            return np.asarray(x, dtype=float)

        def inv(t):
            return np.asarray(t, dtype=float)

        use_nonlinear = False
        scale_label = ""

    # ── Tick generation ────────────────────────────────────────────────────────
    all_nonzero = [
        v for info in weekly_data.values() for v in info["amounts"] if v != 0
    ]

    def make_power_ticks(values, n_ticks=7):
        """Evenly spaced in transform space → labeled in original $ space."""
        t_min = float(fwd(min(values)))
        t_max = float(fwd(max(values)))
        t_pos = np.linspace(t_min, t_max, n_ticks)
        orig = inv(t_pos)

        def nice_round(v):
            if v == 0 or abs(v) < 1:
                return 0.0
            mag = 10 ** np.floor(np.log10(abs(v)))
            rounded = round(v / mag) * mag
            return rounded

        orig_r = [nice_round(v) for v in orig]
        tick_vals = [float(fwd(v)) for v in orig_r]
        tick_text = [f"${int(v):,}" if abs(v) >= 1 else f"${v:.2f}" for v in orig_r]
        return tick_vals, tick_text

    def make_log_ticks(values):
        """Powers of 10 within the data range."""
        min_v = max(min(v for v in values if v > 0), 0.01)
        max_v = max(values)
        lo = math.floor(math.log10(min_v))
        hi = math.ceil(math.log10(max_v))
        powers = list(range(lo, hi + 1))
        tv = [float(p) for p in powers]  # log10(value) = tick position
        tt = [f"${10**p:,}" if p >= 0 else f"${10**p:.2f}" for p in powers]
        return tv, tt

    if use_nonlinear and all_nonzero:
        if scale_mode == "log":
            tick_vals, tick_text = make_log_ticks(all_nonzero)
        else:
            tick_vals, tick_text = make_power_ticks(all_nonzero)
    else:
        tick_vals = tick_text = None

    # ── Traces ─────────────────────────────────────────────────────────────────
    fig = go.Figure()
    is_h = orientation == "h"

    for cat, short in zip(cats, short_names):
        info = weekly_data[cat]
        weeks_lbl = info["weeks"]
        week_dates = info.get("week_dates", info["weeks"])
        color = _parent_color[_get_parent(cat)]

        # All weeks (including zeros) drive the violin KDE shape and box stats.
        all_amounts = info["amounts"]
        t_all = (
            [float(fwd(v)) for v in all_amounts] if use_nonlinear else list(all_amounts)
        )

        # Non-zero weeks only are shown as scatter points.
        nz_pairs = [
            (a, wl, wd)
            for a, wl, wd in zip(info["amounts"], weeks_lbl, week_dates)
            if a != 0
        ]
        if not nz_pairs:
            nz_pairs = [
                (
                    0.0,
                    weeks_lbl[0] if weeks_lbl else "?",
                    week_dates[0] if week_dates else "?",
                )
            ]

        nz_amounts = [p[0] for p in nz_pairs]
        nz_weeks = [p[1] for p in nz_pairs]
        nz_dates = [p[2] for p in nz_pairs]
        t_nz = [float(fwd(v)) for v in nz_amounts] if use_nonlinear else nz_amounts

        # customdata: [original_$, week_label, week_date_ISO]
        nz_customdata = [
            [a, wl, wd] for a, wl, wd in zip(nz_amounts, nz_weeks, nz_dates)
        ]

        hover = f"{short}: $%{{customdata[0]:,.0f}} (%{{customdata[1]}})<extra></extra>"

        # Trace 1: violin shape + box computed over ALL weeks (including zeros).
        # hoveron="points" for nonlinear fires on nothing (points=False), so the
        # violin body stays non-interactive and avoids showing transformed stats.
        fig.add_trace(
            go.Violin(
                x=t_all if is_h else None,
                y=t_all if not is_h else None,
                hoveron="points" if use_nonlinear else "points+violins+kde",
                name=short,
                orientation=orientation,
                side="both",
                fillcolor=color.replace("0.95", "0.18"),
                line=dict(color=color.replace("0.95", "0.70"), width=1.5),
                box_visible=True,
                box=dict(
                    fillcolor=color.replace("0.95", "0.50"),
                    line=dict(color=color.replace("0.95", "0.90"), width=1),
                ),
                meanline_visible=True,
                meanline=dict(color="#d8d8d8", width=1.5),
                points=False,
                showlegend=False,
                spanmode="hard",
            )
        )
        # Trace 2: scatter points for NON-ZERO weeks only, overlaid on the violin.
        # curve index = 2*i+1; callback resolves category as curve_idx // 2.
        fig.add_trace(
            go.Violin(
                x=t_nz if is_h else None,
                y=t_nz if not is_h else None,
                customdata=nz_customdata,
                hovertemplate=hover,
                hoveron="points",
                name=short,
                orientation=orientation,
                fillcolor="rgba(0,0,0,0)",
                line=dict(color="rgba(0,0,0,0)", width=0),
                box_visible=False,
                meanline_visible=False,
                points="all",
                pointpos=0,
                jitter=0.4,
                marker=dict(
                    color=color.replace("0.95", "0.60"), size=6, line=dict(width=0)
                ),
                showlegend=False,
                spanmode="hard",
            )
        )

    # ── Legend: one invisible scatter per parent category ─────────────────────
    # Hidden parents are dimmed so users can see they exist and click to restore.
    for parent in _parents_ordered:
        c = _parent_color[parent]
        is_hidden = parent in hidden_set
        alpha = "0.30" if is_hidden else "0.85"
        fig.add_trace(
            go.Scatter(
                x=[None],
                y=[None],
                mode="markers",
                marker=dict(color=c.replace("0.95", alpha), size=12, symbol="square"),
                name=parent,
                showlegend=True,
            )
        )

    # ── Axis builders ──────────────────────────────────────────────────────────
    def spend_axis() -> dict:
        base = dict(
            title=dict(text="spend ($)", font=WEEKLY_AX_TITLE_FONT),
            tickfont=WEEKLY_TICK_FONT,
            gridcolor=BORDER,
            linecolor=BORDER,
            zeroline=True,
            zerolinecolor=BORDER,
            # showspikes=True,
            # spikemode="across+marker",
            # spikesnap="cursor",
            # spikethickness=1,
            # spikedash="dot",
            # spikecolor="#555555",
        )
        if use_nonlinear and tick_vals is not None:
            base.update(tickmode="array", tickvals=tick_vals, ticktext=tick_text)
        else:
            base["tickprefix"] = "$"
        return base

    def category_axis() -> dict:
        # categoryarray pins display order to the sort; autorange="reversed" flips
        # the axis so the highest-average category appears at the top.
        return dict(
            tickfont=WEEKLY_TICK_FONT,
            gridcolor=BORDER,
            linecolor=BORDER,
            autorange="reversed",
            categoryorder="array",
            categoryarray=short_names,
        )

    fig.update_layout(
        title=dict(
            text=f"Weekly Spending Distribution — {period_label}{scale_label}",
            font=WEEKLY_TITLE_FONT,
        ),
        autosize=True,
        paper_bgcolor=BG,
        plot_bgcolor=BG,
        font=dict(family="Inter, Arial, sans-serif"),  # size=16, color=FONT_COLOR
        margin=dict(l=110, r=40, t=80, b=60),
        showlegend=True,
        legend=dict(
            orientation="h",
            x=0.5,
            y=1.0,
            xanchor="center",
            yanchor="bottom",
            bgcolor="rgba(0,0,0,0)",
            font=dict(color=FONT_COLOR, size=13),
        ),
        violinmode="overlay",
        violingap=0.1,
        violingroupgap=False,
        xaxis=spend_axis() if is_h else category_axis(),
        yaxis=category_axis() if is_h else spend_axis(),
    )
    return fig


# ── Dash app ───────────────────────────────────────────────────────────────────

app = Dash(
    __name__,
    title="hledger Dashboard",
    meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1"}],
)

# ── Styles ─────────────────────────────────────────────────────────────────────
STYLE_PAGE = {
    "backgroundColor": BG,
    "minHeight": "100vh",
    "fontFamily": "Inter, Arial, sans-serif",
    "color": FONT_COLOR,
    "padding": "16px",
}
STYLE_CARD = {
    "backgroundColor": CARD_BG,
    "border": f"1px solid {BORDER}",
    "borderRadius": "8px",
    "padding": "16px",
    "marginBottom": "16px",
}
STYLE_LABEL = {"color": FONT_COLOR, "fontSize": "13px", "marginBottom": "4px"}
STYLE_BTN_PRIMARY = {
    "backgroundColor": "#3b6fd4",
    "color": "white",
    "border": "none",
    "borderRadius": "4px",
    "padding": "8px 18px",
    "cursor": "pointer",
    "fontSize": "13px",
    "fontWeight": "600",
}
STYLE_BTN_WARN = {
    "backgroundColor": "#aa7408",
    "color": "#ffedcc",
    "border": "none",
    "borderRadius": "4px",
    "padding": "8px 14px",
    "cursor": "pointer",
    "fontSize": "13px",
}
STYLE_BTN_SMALL_WARN = {**STYLE_BTN_WARN, "padding": "6px 10px", "fontSize": "12px"}
STYLE_BTN_NEUTRAL = {
    "backgroundColor": "#2a2727",
    "color": FONT_COLOR,
    "border": f"1px solid {BORDER}",
    "borderRadius": "4px",
    "padding": "8px 14px",
    "cursor": "pointer",
    "fontSize": "13px",
}
STYLE_VIOLIN_TOOLTIP = {
    "display": "none",
    "position": "fixed",
    "backgroundColor": CARD_BG,
    "border": f"1px solid {BORDER}",
    "borderRadius": "6px",
    "padding": "7px 11px",
    "fontSize": "12px",
    "color": FONT_COLOR,
    "pointerEvents": "none",
    "zIndex": "9999",
    "fontFamily": "Inter, Arial, sans-serif",
    "lineHeight": "1.7",
    "whiteSpace": "nowrap",
}
STYLE_STATUS = {
    "backgroundColor": "#0d0c0c",
    "border": f"1px solid {BORDER}",
    "borderRadius": "8px",
    "padding": "10px 14px",
    "fontFamily": "monospace",
    "fontSize": "12px",
    "color": "#aaa",
    "whiteSpace": "pre-wrap",
    "minHeight": "36px",
    "margin": "0",
    "flex": "0 0 50%",
    "alignSelf": "stretch",
}
STYLE_ERROR = {**STYLE_STATUS, "color": "#ff7c6e", "border": "1px solid #7a2a20"}
STYLE_TITLE = {
    "color": FONT_COLOR,
    "fontSize": "22px",
    "fontWeight": "700",
    "marginBottom": "16px",
}

SCALE_LABELS = {
    "transform": "Compressed scale",
    "log": "Log scale",
    "linear": "Linear scale",
}


def _label(text: str) -> html.Div:
    return html.Div(text, style=STYLE_LABEL)


def _tab_style():
    return {
        "backgroundColor": CARD_BG,
        "color": "#999",
        "border": f"1px solid {BORDER}",
    }


def _tab_selected_style():
    return {
        "backgroundColor": BG,
        "color": FONT_COLOR,
        "border": f"1px solid {BORDER}",
        "borderBottom": f"1px solid {BG}",
    }


app.layout = html.Div(
    style=STYLE_PAGE,
    children=[
        # CSS is in assets/dashboard.css
        html.H1("hledger Dashboard", style=STYLE_TITLE),
        # ── Controls card + status log ─────────────────────────────────────────────
        html.Div(
            style={
                "display": "flex",
                "gap": "16px",
                "alignItems": "stretch",
                "marginBottom": "16px",
            },
            children=[
                html.Div(
                    style={**STYLE_CARD, "flex": "1", "marginBottom": "0"},
                    children=[
                        html.Div(
                            style={
                                "display": "flex",
                                "gap": "24px",
                                "flexWrap": "wrap",
                                "marginBottom": "12px",
                            },
                            children=[
                                html.Div([
                                    _label("Period"),
                                    dcc.Dropdown(
                                        id="period-dd",
                                        options=[
                                            {
                                                "label": "From Ledger Start",
                                                "value": "from",
                                            },
                                            {"label": "This year", "value": "thisyear"},
                                            {"label": "Last year", "value": "lastyear"},
                                            {
                                                "label": "This quarter",
                                                "value": "thisquarter",
                                            },
                                            {
                                                "label": "Last quarter",
                                                "value": "lastquarter",
                                            },
                                            {
                                                "label": "This month",
                                                "value": "thismonth",
                                            },
                                            {
                                                "label": "Last month",
                                                "value": "lastmonth",
                                            },
                                            {
                                                "label": "Last 12 months",
                                                "value": "last12months",
                                            },
                                        ],
                                        value="from",
                                        clearable=False,
                                        style={"width": "200px"},
                                    ),
                                ]),
                                html.Div([
                                    _label("Account depth"),
                                    dcc.Dropdown(
                                        id="depth-dd",
                                        options=[
                                            {
                                                "label": "Level 2 — categories",
                                                "value": 2,
                                            },
                                            {
                                                "label": "Level 3 — sub-accounts",
                                                "value": 3,
                                            },
                                            {"label": "Level 4 — detail", "value": 4},
                                        ],
                                        value=CFG.get("default_depth", 2),
                                        clearable=False,
                                        style={"width": "220px"},
                                    ),
                                ]),
                            ],
                        ),
                        html.Div(
                            style={
                                "display": "flex",
                                "gap": "16px",
                                "flexWrap": "wrap",
                                "alignItems": "flex-end",
                            },
                            children=[
                                html.Div([
                                    _label("From date (overrides Period)"),
                                    html.Div(
                                        style={
                                            "display": "flex",
                                            "gap": "6px",
                                            "alignItems": "center",
                                        },
                                        children=[
                                            dcc.DatePickerSingle(
                                                id="begin-dp",
                                                placeholder="YYYY-MM-DD",
                                                display_format="YYYY-MM-DD",
                                            ),
                                            html.Button(
                                                "Today",
                                                id="begin-today-btn",
                                                n_clicks=0,
                                                style=STYLE_BTN_SMALL_WARN,
                                            ),
                                        ],
                                    ),
                                ]),
                                html.Div([
                                    _label("To date"),
                                    html.Div(
                                        style={
                                            "display": "flex",
                                            "gap": "6px",
                                            "alignItems": "center",
                                        },
                                        children=[
                                            dcc.DatePickerSingle(
                                                id="end-dp",
                                                placeholder="YYYY-MM-DD",
                                                display_format="YYYY-MM-DD",
                                            ),
                                            html.Button(
                                                "Today",
                                                id="end-today-btn",
                                                n_clicks=0,
                                                style=STYLE_BTN_SMALL_WARN,
                                            ),
                                        ],
                                    ),
                                ]),
                                html.Div([
                                    _label("\u00a0"),
                                    html.Button(
                                        "✕ Clear dates",
                                        id="clear-btn",
                                        n_clicks=0,
                                        style=STYLE_BTN_WARN,
                                    ),
                                ]),
                                html.Div([
                                    _label("\u00a0"),
                                    html.Button(
                                        "↻ Refresh",
                                        id="refresh-btn",
                                        n_clicks=0,
                                        style=STYLE_BTN_PRIMARY,
                                    ),
                                ]),
                                html.Div([
                                    _label("\u00a0"),
                                    html.Button(
                                        "⟳ Import",
                                        id="import-btn",
                                        n_clicks=0,
                                        title="Run txcat → hledger import, then refresh",
                                        style=STYLE_BTN_NEUTRAL,
                                    ),
                                ]),
                                html.Div([
                                    _label("\u00a0"),
                                    html.Button(
                                        "⚙",
                                        id="settings-btn",
                                        n_clicks=0,
                                        title="Settings",
                                        style=STYLE_BTN_NEUTRAL,
                                    ),
                                ]),
                            ],
                        ),
                    ],
                ),
                html.Pre(
                    id="status-log",
                    style=STYLE_STATUS,
                    children="Ready — press ↻ Refresh to fetch data from hledger.",
                ),
            ],
        ),
        # ── Tabs ───────────────────────────────────────────────────────────────────
        dcc.Tabs(
            id="tabs",
            value="tab-sankey",
            colors={"border": BORDER, "primary": "#3b6fd4", "background": CARD_BG},
            style={"marginBottom": "0"},
            children=[
                dcc.Tab(
                    label="Sankey",
                    value="tab-sankey",
                    style=_tab_style(),
                    selected_style=_tab_selected_style(),
                    children=[
                        html.Div(
                            className="graph-frame",
                            children=[
                                dcc.Graph(
                                    id="sankey-graph",
                                    figure=empty_sankey_figure(),
                                    config={
                                        "displayModeBar": True,
                                        "responsive": True,
                                        "modeBarButtonsToRemove": [
                                            "lasso2d",
                                            "select2d",
                                        ],
                                    },
                                    style={"height": "100%", "width": "100%"},
                                ),
                            ],
                        ),
                    ],
                ),
                dcc.Tab(
                    label="Monthly Trend",
                    value="tab-trend",
                    style=_tab_style(),
                    selected_style=_tab_selected_style(),
                    children=[
                        html.Div(
                            className="graph-frame",
                            children=[
                                dcc.Graph(
                                    id="bar-graph",
                                    figure=empty_bar_figure(),
                                    config={"displayModeBar": True, "responsive": True},
                                    style={"height": "100%", "width": "100%"},
                                ),
                            ],
                        ),
                    ],
                ),
                dcc.Tab(
                    label="Small multiples",
                    value="tab-sm",
                    style=_tab_style(),
                    selected_style=_tab_selected_style(),
                    children=[
                        html.Div(
                            # style={"width": "100%", "overflowX": "auto"},
                            # className="graph-frame",
                            children=[
                                dcc.Graph(
                                    id="sm-graph",
                                    figure=empty_sm_figure(),
                                    config={"displayModeBar": True, "responsive": True},
                                    style={"width": "100%"},
                                ),
                            ],
                        ),
                    ],
                ),
                dcc.Tab(
                    label="Heatmap",
                    value="tab-hm",
                    style=_tab_style(),
                    selected_style=_tab_selected_style(),
                    children=[
                        html.Div(
                            # style={"width": "100%", "overflowX": "auto"},
                            # className="graph-frame",
                            children=[
                                dcc.Graph(
                                    id="hm-graph",
                                    figure=empty_hm_figure(),
                                    config={"displayModeBar": True, "responsive": True},
                                    style={
                                        "height": "100vh",
                                        "width": "100%",
                                    },
                                ),
                            ],
                        ),
                    ],
                ),
                dcc.Tab(
                    label="Distribution",
                    value="tab-strip",
                    style=_tab_style(),
                    selected_style=_tab_selected_style(),
                    children=[
                        html.Div(
                            children=[
                                html.Div(
                                    style={
                                        "display": "flex",
                                        # "justifyContent": "flex-end",
                                        "gap": "8px",
                                        "padding": "8px 12px",
                                    },
                                    children=[
                                        html.Button(
                                            "Swap axes",
                                            id="swap-axes-btn",
                                            n_clicks=0,
                                            style=STYLE_BTN_WARN,
                                        ),
                                        html.Button(
                                            id="scale-cycle-btn",
                                            n_clicks=0,
                                            children="Linear",
                                            style=STYLE_BTN_NEUTRAL,
                                        ),
                                    ],
                                ),
                                dcc.Graph(
                                    id="strip-graph",
                                    figure=empty_strip_figure(),
                                    config={"displayModeBar": True, "responsive": True},
                                    responsive=True,
                                    style={
                                        "width": "100%",
                                        "height": "100vh",
                                    },
                                ),
                            ],
                        ),
                    ],
                ),
                dcc.Tab(
                    label="hledger Shell",
                    value="tab-shell",
                    style=_tab_style(),
                    selected_style=_tab_selected_style(),
                    children=[
                        html.Div(
                            style={"padding": "16px"},
                            children=[
                                html.Div(
                                    style={
                                        "display": "flex",
                                        "gap": "8px",
                                        "marginBottom": "10px",
                                        "alignItems": "center",
                                    },
                                    children=[
                                        html.Span(
                                            "hledger",
                                            style={
                                                "fontFamily": "monospace",
                                                "fontSize": "13px",
                                                "color": "#888",
                                                "flexShrink": "0",
                                            },
                                        ),
                                        dcc.Input(
                                            id="shell-input",
                                            type="text",
                                            debounce=False,
                                            placeholder="bal expenses --depth 2",
                                            value="",
                                            n_submit=0,
                                            style={
                                                "flex": "1",
                                                "fontFamily": "monospace",
                                                "fontSize": "13px",
                                                "backgroundColor": "#0d0c0c",
                                                "color": FONT_COLOR,
                                                "border": f"1px solid {BORDER}",
                                                "borderRadius": "4px",
                                                "padding": "7px 10px",
                                                "outline": "none",
                                            },
                                        ),
                                        html.Button(
                                            "▶ Run",
                                            id="shell-run-btn",
                                            n_clicks=0,
                                            style=STYLE_BTN_PRIMARY,
                                        ),
                                    ],
                                ),
                                html.Pre(
                                    id="shell-output",
                                    style={
                                        **STYLE_STATUS,
                                        "flex": "unset",
                                        "minHeight": "300px",
                                        "maxHeight": "70vh",
                                        "overflowY": "auto",
                                        "fontSize": "13px",
                                        "whiteSpace": "pre",
                                    },
                                    children=(
                                        "Enter a hledger command above and press Run (or hit "
                                        "Enter). The journal is already selected — a -f you "
                                        "type here adds a second journal file rather than "
                                        "replacing it."
                                    ),
                                ),
                            ],
                        ),
                    ],
                ),
            ],
        ),
        # ── Hidden state stores ────────────────────────────────────────────────────
        dcc.Store(id="clear-signal", data=0),
        dcc.Store(id="strip-orientation", data="v"),
        dcc.Store(id="violin-scale", data="linear"),
        dcc.Store(id="strip-data-store"),
        dcc.Store(id="register-data-store"),
        dcc.Store(id="strip-legend-meta", data=None),
        dcc.Store(id="strip-parent-filter", data=[]),
        dcc.Store(id="sm-width-store", data=1200),
        dcc.Store(id="sm-period-label-store", data=""),
        dcc.Interval(id="import-poll", interval=400, n_intervals=0, disabled=True),
        html.Div(id="_resize-dummy", style={"display": "none"}),
        html.Div(id="_violin-setup-dummy", style={"display": "none"}),
        html.Div(id="violin-hover-tooltip", style=STYLE_VIOLIN_TOOLTIP),
        # ── Transaction detail modal ───────────────────────────────────────────────
        html.Div(
            id="tx-modal",
            style={"display": "none"},
            children=[
                # Overlay backdrop
                html.Div(
                    style={
                        "position": "fixed",
                        "top": "0",
                        "left": "0",
                        "width": "100vw",
                        "height": "100vh",
                        "backgroundColor": "rgba(0,0,0,0.72)",
                        "zIndex": "900",
                    },
                    id="tx-modal-backdrop",
                ),
                # Modal panel
                html.Div(
                    style={
                        "position": "fixed",
                        "top": "50%",
                        "left": "50%",
                        "transform": "translate(-50%, -50%)",
                        "zIndex": "1000",
                        "width": "min(720px, 92vw)",
                        "maxHeight": "80vh",
                        "overflowY": "auto",
                        "backgroundColor": CARD_BG,
                        "border": f"1px solid {BORDER}",
                        "borderRadius": "8px",
                        "padding": "20px 24px",
                        "boxShadow": "0 16px 48px rgba(0,0,0,0.6)",
                    },
                    children=[
                        html.Div(
                            style={
                                "display": "flex",
                                "justifyContent": "space-between",
                                "alignItems": "flex-start",
                                "marginBottom": "14px",
                            },
                            children=[
                                html.Div([
                                    html.H3(
                                        id="tx-modal-title",
                                        style={
                                            "color": FONT_COLOR,
                                            "margin": "0 0 4px",
                                            "fontSize": "15px",
                                            "fontWeight": "500",
                                        },
                                    ),
                                    html.Pre(
                                        id="tx-modal-cmd",
                                        style={
                                            "color": "#555",
                                            "fontSize": "10px",
                                            "margin": "0",
                                            "fontFamily": "monospace",
                                        },
                                    ),
                                ]),
                                html.Button(
                                    "✕ Close",
                                    id="tx-modal-close",
                                    n_clicks=0,
                                    style={
                                        **STYLE_BTN_SMALL_WARN,
                                        "flexShrink": "0",
                                        "marginLeft": "16px",
                                    },
                                ),
                            ],
                        ),
                        html.Div(id="tx-modal-content"),
                    ],
                ),
            ],
        ),
        # ── Account source selection modal ────────────────────────────────────────
        html.Div(
            id="import-source-modal",
            style={"display": "none"},
            children=[
                html.Div(
                    style={
                        "position": "fixed",
                        "top": "0",
                        "left": "0",
                        "width": "100vw",
                        "height": "100vh",
                        "backgroundColor": "rgba(0,0,0,0.72)",
                        "zIndex": "900",
                    },
                ),
                html.Div(
                    style={
                        "position": "fixed",
                        "top": "50%",
                        "left": "50%",
                        "transform": "translate(-50%, -50%)",
                        "zIndex": "1000",
                        "width": "min(420px, 92vw)",
                        "backgroundColor": CARD_BG,
                        "border": f"1px solid {BORDER}",
                        "borderRadius": "8px",
                        "padding": "24px 28px",
                        "boxShadow": "0 16px 48px rgba(0,0,0,0.6)",
                        "textAlign": "center",
                    },
                    children=[
                        html.H3(
                            "Import from which account?",
                            style={
                                "color": FONT_COLOR,
                                "margin": "0 0 20px",
                                "fontSize": "16px",
                                "fontWeight": "500",
                            },
                        ),
                        html.Div(
                            style={
                                "display": "flex",
                                "gap": "12px",
                                "justifyContent": "center",
                                "marginBottom": "14px",
                            },
                            children=[
                                html.Button(
                                    CFG["debit_account"],
                                    id="import-debit-btn",
                                    n_clicks=0,
                                    style=STYLE_BTN_NEUTRAL,
                                ),
                                html.Button(
                                    CFG["savings_account"],
                                    id="import-savings-btn",
                                    n_clicks=0,
                                    style=STYLE_BTN_NEUTRAL,
                                ),
                            ],
                        ),
                        html.Button(
                            "Cancel",
                            id="import-source-cancel",
                            n_clicks=0,
                            style={**STYLE_BTN_SMALL_WARN, "marginTop": "4px"},
                        ),
                    ],
                ),
            ],
        ),
        # ── Bank navigation modal (no new transactions) ───────────────────────────
        html.Div(
            id="bank-nav-modal",
            style={"display": "none"},
            children=[
                html.Div(
                    style={
                        "position": "fixed",
                        "top": "0",
                        "left": "0",
                        "width": "100vw",
                        "height": "100vh",
                        "backgroundColor": "rgba(0,0,0,0.72)",
                        "zIndex": "900",
                    },
                ),
                html.Div(
                    style={
                        "position": "fixed",
                        "top": "50%",
                        "left": "50%",
                        "transform": "translate(-50%, -50%)",
                        "zIndex": "1000",
                        "width": "min(420px, 92vw)",
                        "backgroundColor": CARD_BG,
                        "border": f"1px solid {BORDER}",
                        "borderRadius": "8px",
                        "padding": "24px 28px",
                        "boxShadow": "0 16px 48px rgba(0,0,0,0.6)",
                        "textAlign": "center",
                    },
                    children=[
                        html.P(
                            "No new transactions found.",
                            style={
                                "color": FONT_COLOR,
                                "fontSize": "15px",
                                "fontWeight": "500",
                                "margin": "0 0 8px",
                            },
                        ),
                        html.P(
                            "Visit your bank to download new statements?",
                            style={
                                "color": "#999",
                                "fontSize": "13px",
                                "margin": "0 0 20px",
                            },
                        ),
                        html.Div(
                            style={
                                "display": "flex",
                                "gap": "12px",
                                "justifyContent": "center",
                            },
                            children=[
                                html.A(
                                    "Open bank website →",
                                    id="bank-nav-link",
                                    href=CFG.get("bank_url", ""),
                                    target="_blank",
                                    style={
                                        **STYLE_BTN_PRIMARY,
                                        "textDecoration": "none",
                                        "display": "inline-block",
                                    },
                                ),
                                html.Button(
                                    "✕ Dismiss",
                                    id="bank-nav-close",
                                    n_clicks=0,
                                    style=STYLE_BTN_SMALL_WARN,
                                ),
                            ],
                        ),
                    ],
                ),
            ],
        ),
        # ── Settings modal ────────────────────────────────────────────────────────
        html.Div(
            id="settings-modal",
            style={"display": "none"},
            children=[
                html.Div(
                    style={
                        "position": "fixed",
                        "top": "0",
                        "left": "0",
                        "width": "100vw",
                        "height": "100vh",
                        "backgroundColor": "rgba(0,0,0,0.72)",
                        "zIndex": "900",
                    },
                ),
                html.Div(
                    style={
                        "position": "fixed",
                        "top": "50%",
                        "left": "50%",
                        "transform": "translate(-50%, -50%)",
                        "zIndex": "1000",
                        "width": "min(600px, 92vw)",
                        "maxHeight": "85vh",
                        "overflowY": "auto",
                        "backgroundColor": CARD_BG,
                        "border": f"1px solid {BORDER}",
                        "borderRadius": "8px",
                        "padding": "24px 28px",
                        "boxShadow": "0 16px 48px rgba(0,0,0,0.6)",
                    },
                    children=[
                        html.Div(
                            style={
                                "display": "flex",
                                "justifyContent": "space-between",
                                "alignItems": "center",
                                "marginBottom": "20px",
                            },
                            children=[
                                html.H3(
                                    "Settings",
                                    style={
                                        "color": FONT_COLOR,
                                        "margin": "0",
                                        "fontSize": "16px",
                                        "fontWeight": "500",
                                    },
                                ),
                                html.Button(
                                    "✕ Close",
                                    id="settings-close",
                                    n_clicks=0,
                                    style=STYLE_BTN_SMALL_WARN,
                                ),
                            ],
                        ),
                        # Account mapping
                        html.P(
                            "Account Mapping",
                            style={
                                "color": "#888",
                                "fontSize": "11px",
                                "textTransform": "uppercase",
                                "letterSpacing": "0.08em",
                                "margin": "0 0 10px",
                            },
                        ),
                        *[
                            html.Div(
                                style={"marginBottom": "10px"},
                                children=[
                                    html.Label(
                                        label,
                                        style={
                                            **STYLE_LABEL,
                                            "marginBottom": "4px",
                                            "display": "block",
                                        },
                                    ),
                                    dcc.Input(
                                        id=f"settings-{field}",
                                        type="text",
                                        debounce=False,
                                        style={
                                            "width": "100%",
                                            "backgroundColor": BG,
                                            "color": FONT_COLOR,
                                            "border": f"1px solid {BORDER}",
                                            "borderRadius": "4px",
                                            "padding": "6px 10px",
                                            "fontSize": "13px",
                                            "boxSizing": "border-box",
                                        },
                                    ),
                                ],
                            )
                            for field, label in [
                                ("income-account", "Income account"),
                                ("expenses-account", "Expenses account"),
                                ("savings-account", "Savings account"),
                                ("debit-account", "Debit account"),
                            ]
                        ],
                        # Import settings
                        html.P(
                            "Import",
                            style={
                                "color": "#888",
                                "fontSize": "11px",
                                "textTransform": "uppercase",
                                "letterSpacing": "0.08em",
                                "margin": "16px 0 10px",
                            },
                        ),
                        *[
                            html.Div(
                                style={"marginBottom": "10px"},
                                children=[
                                    html.Label(
                                        label,
                                        style={
                                            **STYLE_LABEL,
                                            "marginBottom": "4px",
                                            "display": "block",
                                        },
                                    ),
                                    dcc.Input(
                                        id=f"settings-{field}",
                                        type="text",
                                        debounce=False,
                                        style={
                                            "width": "100%",
                                            "backgroundColor": BG,
                                            "color": FONT_COLOR,
                                            "border": f"1px solid {BORDER}",
                                            "borderRadius": "4px",
                                            "padding": "6px 10px",
                                            "fontSize": "13px",
                                            "boxSizing": "border-box",
                                        },
                                    ),
                                ],
                            )
                            for field, label in [
                                ("bank-url", "Bank website URL"),
                                ("hledger-rules-debit", "hledger rules — debit"),
                                ("hledger-rules-savings", "hledger rules — savings"),
                            ]
                        ],
                        *[
                            html.Div(
                                style={"marginBottom": "10px"},
                                children=[
                                    html.Label(
                                        label,
                                        style={
                                            **STYLE_LABEL,
                                            "marginBottom": "6px",
                                            "display": "block",
                                        },
                                    ),
                                    html.Div(
                                        style={
                                            "display": "flex",
                                            "border": "1px solid #444",
                                            "borderRadius": "4px",
                                            "overflow": "hidden",
                                            "width": "fit-content",
                                        },
                                        children=[
                                            html.Button(
                                                "Run txcat",
                                                id=f"settings-skip-txcat-{acct}-no",
                                                n_clicks=0,
                                                style={},
                                            ),
                                            html.Button(
                                                "Skip txcat",
                                                id=f"settings-skip-txcat-{acct}-yes",
                                                n_clicks=0,
                                                style={},
                                            ),
                                        ],
                                    ),
                                    dcc.Store(
                                        id=f"settings-skip-txcat-{acct}", data=False
                                    ),
                                ],
                            )
                            for acct, label in [
                                ("debit", "Skip txcat — debit"),
                                ("savings", "Skip txcat — savings"),
                            ]
                        ],
                        # Display settings
                        html.P(
                            "Display",
                            style={
                                "color": "#888",
                                "fontSize": "11px",
                                "textTransform": "uppercase",
                                "letterSpacing": "0.08em",
                                "margin": "16px 0 10px",
                            },
                        ),
                        html.Div(
                            style={"marginBottom": "20px"},
                            children=[
                                html.Label(
                                    "Default account depth",
                                    style={
                                        **STYLE_LABEL,
                                        "marginBottom": "6px",
                                        "display": "block",
                                    },
                                ),
                                html.Div(
                                    style={
                                        "display": "flex",
                                        "border": "1px solid #444",
                                        "borderRadius": "4px",
                                        "overflow": "hidden",
                                        "width": "fit-content",
                                    },
                                    children=[
                                        html.Button(
                                            "2 — categories",
                                            id="settings-depth-btn-2",
                                            n_clicks=0,
                                            style={},
                                        ),
                                        html.Button(
                                            "3 — sub-accounts",
                                            id="settings-depth-btn-3",
                                            n_clicks=0,
                                            style={},
                                        ),
                                        html.Button(
                                            "4 — detail",
                                            id="settings-depth-btn-4",
                                            n_clicks=0,
                                            style={},
                                        ),
                                    ],
                                ),
                                dcc.Store(
                                    id="settings-default-depth",
                                    data=CFG.get("default_depth", 2),
                                ),
                            ],
                        ),
                        html.Button(
                            "Save",
                            id="settings-save",
                            n_clicks=0,
                            style=STYLE_BTN_PRIMARY,
                        ),
                    ],
                ),
            ],
        ),
    ],
)


# ── Callbacks ──────────────────────────────────────────────────────────────────

app.clientside_callback(
    """
    function(tab) {
        setTimeout(function() { window.dispatchEvent(new Event('resize')); }, 60);
        return tab;
    }
    """,
    Output("_resize-dummy", "children"),
    Input("tabs", "value"),
)

app.clientside_callback(
    """
    function(id) {
        function measure() {
            var el = document.getElementById('sm-graph');
            return el ? Math.round(el.getBoundingClientRect().width) : window.innerWidth;
        }
        window.addEventListener('resize', function() {
            var w = measure();
            if (w > 0) { dash_clientside.set_props('sm-width-store', {data: w}); }
        });
        return measure() || window.innerWidth;
    }
    """,
    Output("sm-width-store", "data"),
    Input("sm-graph", "id"),
)

app.clientside_callback(
    """
    function(figure, scaleMode) {
        /* Re-runs whenever the strip figure or scale mode changes.
           Attaches plotly_hover / plotly_unhover handlers that:
             - For VIOLIN BODY hover: hide native Plotly tooltip (which shows
               transformed numbers), show a custom positioned div with stats
               back-converted to dollars via inv().
             - For POINT hover: restore native tooltip (hovertemplate already
               shows correct $), hide the custom div.
           The spike-line guideline is purely axis config (showspikes) and
           needs no JS — it follows the cursor automatically.                    */

        var POWER = 0.3;
        function inv(t) {
            if (scaleMode === 'log')       return Math.pow(10, t);
            if (scaleMode === 'transform') return Math.sign(t) * Math.pow(Math.abs(t), 1.0 / POWER);
            return t;
        }
        function fmt(v) {
            v = Math.abs(v);
            if (v >= 1000) return '$' + Math.round(v).toLocaleString();
            if (v >= 1)    return '$' + v.toFixed(0);
            return '$' + v.toFixed(2);
        }

        function bindEvents() {
            var graphDiv = document.getElementById('strip-graph');
            var tooltip  = document.getElementById('violin-hover-tooltip');
            if (!graphDiv || !tooltip) return;

            /* Plotly attaches .on() after rendering; retry until it's ready. */
            if (typeof graphDiv.on !== 'function') {
                setTimeout(bindEvents, 50);
                return;
            }

            /* Remove previous listeners to avoid accumulation on re-renders. */
            if (graphDiv._violinHoverFn) {
                graphDiv.removeAllListeners('plotly_hover');
                graphDiv.removeAllListeners('plotly_unhover');
            }

            graphDiv._violinHoverFn = function(data) {
                if (!data || !data.points || !data.points.length) return;
                var pt          = data.points[0];
                var hoverLayer  = graphDiv.querySelector('.hoverlayer');
                var isViolinStats = (pt.median !== undefined && pt.q1 !== undefined);

                if (isViolinStats) {
                    /* Violin body hover — suppress native tooltip, show ours. */
                    if (hoverLayer) hoverLayer.style.visibility = 'hidden';

                    var name  = (pt.fullData && pt.fullData.name) ? pt.fullData.name : '';
                    var stats = [
                        ['min',    pt.lowerFence],
                        ['Q1',     pt.q1],
                        ['median', pt.median],
                        ['mean',   pt.mean],
                        ['Q3',     pt.q3],
                        ['max',    pt.upperFence],
                    ];
                    var lines = stats
                        .filter(function(s) { return s[1] !== undefined; })
                        .map(function(s) {
                            return '<span style="color:#888;font-size:11px">' + s[0] + ':</span> '
                                   + fmt(inv(s[1]));
                        });

                    tooltip.innerHTML = '<b style="font-size:13px">' + name + '</b><br>' + lines.join('<br>');
                    tooltip.style.display = 'block';

                    /* Position near cursor, flip left/up if near viewport edge. */
                    var ex = data.event.clientX, ey = data.event.clientY;
                    var tw = tooltip.offsetWidth  || 140;
                    var th = tooltip.offsetHeight || 120;
                    var lft = (ex + 18 + tw > window.innerWidth)  ? ex - tw - 10 : ex + 14;
                    var top = (ey + 10 + th > window.innerHeight)  ? ey - th - 4  : ey + 6;
                    tooltip.style.left = lft + 'px';
                    tooltip.style.top  = top + 'px';

                } else {
                    /* Point hover — keep native hovertemplate tooltip. */
                    if (hoverLayer) hoverLayer.style.visibility = '';
                    tooltip.style.display = 'none';
                }
            };

            graphDiv._violinUnhoverFn = function() {
                var hoverLayer = graphDiv.querySelector('.hoverlayer');
                if (hoverLayer) hoverLayer.style.visibility = '';
                tooltip.style.display = 'none';
            };

            graphDiv.on('plotly_hover',   graphDiv._violinHoverFn);
            graphDiv.on('plotly_unhover', graphDiv._violinUnhoverFn);
        }

        bindEvents();
        return window.dash_clientside.no_update;
    }
    """,
    Output("_violin-setup-dummy", "children"),
    Input("strip-graph", "figure"),
    Input("violin-scale", "data"),
    prevent_initial_call=True,
)


@app.callback(
    Output("begin-dp", "date"),
    Output("end-dp", "date"),
    Input("clear-btn", "n_clicks"),
    Input("begin-today-btn", "n_clicks"),
    Input("end-today-btn", "n_clicks"),
    prevent_initial_call=True,
)
def handle_date_buttons(_clear, _begin_today, _end_today):
    """Clear both dates, or stamp one with today's date."""
    today = date.today().isoformat()
    triggered = callback_context.triggered_id
    if triggered == "begin-today-btn":
        return today, no_update
    if triggered == "end-today-btn":
        return no_update, today
    return None, None


@app.callback(
    Output("strip-orientation", "data"),
    Input("swap-axes-btn", "n_clicks"),
    State("strip-orientation", "data"),
    prevent_initial_call=True,
)
def toggle_orientation(n, current):
    return "v" if current == "h" else "h"


@app.callback(
    Output("violin-scale", "data"),
    Output("scale-cycle-btn", "children"),
    Input("scale-cycle-btn", "n_clicks"),
    State("violin-scale", "data"),
    prevent_initial_call=True,
)
def cycle_scale(n, current):
    cycle = ["linear", "transform", "log"]
    nxt = cycle[(cycle.index(current) + 1) % len(cycle)]
    return nxt, SCALE_LABELS[nxt]


@app.callback(
    Output("sankey-graph", "figure"),
    Output("bar-graph", "figure"),
    Output("sm-graph", "figure"),
    Output("sm-graph", "style"),
    Output("hm-graph", "figure"),
    Output("strip-data-store", "data"),
    Output("register-data-store", "data"),
    Output("sm-period-label-store", "data"),
    Output("status-log", "children"),
    Output("status-log", "style"),
    Output("strip-parent-filter", "data"),
    Input("refresh-btn", "n_clicks"),
    State("period-dd", "value"),
    State("depth-dd", "value"),
    State("begin-dp", "date"),
    State("end-dp", "date"),
    State("sm-width-store", "data"),
    prevent_initial_call=True,
)
def refresh(_refresh_n, period, depth, begin, end, sm_width):

    # ── Guardrail: --end without --begin ───────────────────────────────────────
    if end and not begin:
        msg = (
            "⚠ Invalid date range: a To date is set without a From date.\n\n"
            "Using only --end returns cumulative balances from ledger start\n"
            "(including prior-period opening balances), making the Sankey wrong.\n\n"
            "Fix: also set a From date, or clear the To date and use the Period dropdown."
        )
        return (
            no_update,
            no_update,
            no_update,
            no_update,  # sm-graph.style
            no_update,
            no_update,
            no_update,
            no_update,  # sm-period-label-store
            msg,
            STYLE_ERROR,
            no_update,
        )

    # ── Build period args ──────────────────────────────────────────────────────
    if begin and end:
        period_args = ["--begin", begin, "--end", end]
        period_label = f"{begin} – {end}"

    elif begin:
        period_args = ["--begin", begin]
        period_label = f"from {begin}"

    elif period == "from":
        # Discover the earliest transaction date from the journal
        earliest = get_ledger_start_date()
        if earliest:
            period_args = ["--begin", earliest]
            period_label = f"from {earliest} (ledger start)"
        else:
            period_args = []  # no date filter = all time
            period_label = "all time"

    else:
        period_args = ["--period", period]
        period_label = PERIOD_LABELS.get(period, period)

    inc_acct = CFG["income_account"]
    exp_acct = CFG["expenses_account"]
    sav_acct = CFG["savings_account"]
    deb_acct = CFG["debit_account"]

    log_lines: list[str] = []

    # ── Sankey data ────────────────────────────────────────────────────────────
    inc_raw, l1 = run_hledger(["bal", inc_acct], period_args, depth)
    exp_raw, l2 = run_hledger(["bal", exp_acct], period_args, depth)
    sav_raw, l3 = run_hledger(["bal", sav_acct], period_args, depth)
    deb_raw, l4 = run_hledger(["bal", deb_acct], period_args, depth=None)
    log_lines += [l1, l2, l3, l4]

    inc_df = normalise(inc_raw, flip_sign=True)
    exp_df = normalise(exp_raw, flip_sign=False)
    sav_df = normalise(sav_raw, flip_sign=False)
    deb_df = normalise(deb_raw, flip_sign=False)

    debit_change = float(deb_df["amount"].sum()) if not deb_df.empty else 0.0
    log_lines.append(
        f"  {deb_acct} net change: {debit_change:+.2f}"
        + (
            " → prior balance consumed"
            if debit_change < 0
            else " → income retained in checking"
            if debit_change > 0
            else " → no change"
        )
    )

    if inc_df.empty and exp_df.empty:
        sankey_fig = empty_sankey_figure(
            "No income / expense data returned.\n"
            "Check that hledger is on $PATH and your journal has transactions."
        )
    else:
        sb = build_sankey(inc_df, exp_df, sav_df, debit_change, deb_acct)
        pd_data = sb.to_plotly(node_colors=getattr(sb, "_node_colors", None))
        sankey_fig = go.Figure(
            data=[go.Sankey(arrangement="snap", **pd_data)],
            layout=dark_layout(
                f"Income → Savings & Expenses  [{period_label}, depth {depth}]"
            ),
        )
        log_lines.append(
            f"✓ Sankey: {len(sb.node_full_labels)} nodes, {len(sb.links)} links"
        )

    # ── Monthly trend ──────────────────────────────────────────────────────────
    inc_med_acct = inc_acct + ":medical"
    exp_med_acct = exp_acct + ":medical"
    inc_m_raw, lm1 = run_hledger(["bal", inc_acct], period_args, depth, monthly=True)
    exp_m_raw, lm2 = run_hledger(["bal", exp_acct], period_args, depth, monthly=True)
    inc_med_m_raw, lm3 = run_hledger(
        ["bal", inc_med_acct], period_args, depth=None, monthly=True
    )
    exp_med_m_raw, lm4 = run_hledger(
        ["bal", exp_med_acct], period_args, depth=None, monthly=True
    )
    log_lines += [lm1, lm2, lm3, lm4]

    if inc_m_raw.empty or exp_m_raw.empty:
        bar_fig = empty_bar_figure("No monthly data available for this period.")
    else:
        try:
            s_income = pivot_monthly(inc_m_raw, flip=True)
            s_expenses = pivot_monthly(exp_m_raw, flip=False)
            s_inc_medical = (
                pivot_monthly(inc_med_m_raw, flip=True)
                if not inc_med_m_raw.empty
                else pd.Series(0.0, index=s_income.index)
            )
            s_exp_medical = (
                pivot_monthly(exp_med_m_raw, flip=False)
                if not exp_med_m_raw.empty
                else pd.Series(0.0, index=s_expenses.index)
            )
            bar_fig = build_monthly_bar_figure(
                s_income, s_inc_medical, s_expenses, s_exp_medical, period_label
            )
            log_lines.append("✓ Monthly trend chart updated")
        except Exception as exc:
            bar_fig = empty_bar_figure(f"Error building trend chart: {exc}")
            log_lines.append(f"⚠ Trend chart error: {exc}")

    # ── Weekly expense data (shared by all three weekly views) ─────────────────
    weekly_raw, wl = run_hledger_weekly(exp_acct, period_args, depth)
    log_lines.append(wl)
    weekly_data = parse_weekly_data(weekly_raw)

    if weekly_data:
        n_weeks = len(next(iter(weekly_data.values()))["weeks"])
        log_lines.append(f"  Weekly: {len(weekly_data)} accounts × {n_weeks} weeks")
    else:
        log_lines.append("  Weekly data: none returned")

    sm_fig, sm_style = build_small_multiples_figure(
        weekly_data, period_label, plot_w=int(sm_width or 1200)
    )
    hm_fig = build_heatmap_figure(weekly_data, period_label)

    log_lines.append("✓ Weekly charts updated")

    # ── Pre-fetch full register for popup drill-down ───────────────────────────
    reg_txns, reg_cmd = run_hledger_register_full(exp_acct, period_args)
    register_data = {"txns": reg_txns, "cmd": reg_cmd}
    log_lines.append(reg_cmd)

    return (
        sankey_fig,
        bar_fig,
        sm_fig,
        sm_style,
        hm_fig,
        weekly_data,
        register_data,
        period_label,
        "\n".join(log_lines),
        STYLE_STATUS,
        [],  # reset strip-parent-filter
    )


@app.callback(
    Output("sm-graph", "figure", allow_duplicate=True),
    Output("sm-graph", "style", allow_duplicate=True),
    Input("sm-width-store", "data"),
    State("strip-data-store", "data"),
    State("sm-period-label-store", "data"),
    prevent_initial_call=True,
)
def update_sm_on_resize(sm_width, weekly_data, period_label):
    if not weekly_data:
        return no_update, no_update
    fig, sm_style = build_small_multiples_figure(
        weekly_data, period_label or "", plot_w=int(sm_width or 1200)
    )
    return fig, sm_style


@app.callback(
    Output("strip-graph", "figure"),
    Output("strip-legend-meta", "data"),
    Input("strip-data-store", "data"),
    Input("strip-orientation", "data"),
    Input("violin-scale", "data"),
    Input("strip-parent-filter", "data"),
    State("period-dd", "value"),
    prevent_initial_call=False,
)
def update_strip_plot(data, orientation, scale_mode, hidden_parents, period):
    if not data:
        return empty_strip_figure("No data — press ↻ Refresh"), None
    period_label = PERIOD_LABELS.get(period, period) if period else ""
    fig = build_strip_figure(
        data,
        period_label,
        orientation,
        scale_mode or "transform",
        hidden_parents=hidden_parents or [],
    )
    # Build legend meta so the filter callback can map trace indices → parent names.
    # n_cats must reflect the VISIBLE category count (same filtering as build_strip_figure)
    # because parent legend traces are appended at 2*n_visible_cats + j.
    _exp_depth = len(CFG["expenses_account"].split(":"))

    def _get_parent(cat: str) -> str:
        parts = cat.split(":")
        return parts[_exp_depth] if len(parts) > _exp_depth else parts[-1]

    all_cats = sorted(data.keys(), key=lambda c: data[c]["average"], reverse=True)
    parents = list(dict.fromkeys(_get_parent(c) for c in all_cats))  # all, for legend
    hidden_set = set(hidden_parents or [])
    visible_cats = [c for c in all_cats if _get_parent(c) not in hidden_set] or all_cats
    meta = {"n_cats": len(visible_cats), "parents": parents}
    return fig, meta


@app.callback(
    Output("strip-parent-filter", "data", allow_duplicate=True),
    Input("strip-graph", "restyleData"),
    State("strip-legend-meta", "data"),
    State("strip-parent-filter", "data"),
    prevent_initial_call=True,
)
def update_strip_filter(restyle_data, meta, current_filter):
    """
    Handle legend single-click (toggle) and double-click (isolate/restore).

    Single click  → restyleData has one index.
    Double click  → Plotly sends a batch restyle over ALL traces: the clicked
                    parent legend trace becomes True, all others "legendonly".
                    A second double-click on the now-isolated parent restores all
                    traces to True.
    """
    if not restyle_data or not meta:
        return no_update
    try:
        changes, indices = restyle_data
        n_cats = meta["n_cats"]
        parents = meta["parents"]
        visible_vals = changes.get("visible")
        if visible_vals is None:
            return no_update
    except (KeyError, IndexError, TypeError, ValueError):
        return no_update

    # Collect the visibility value for every parent legend trace in this restyle.
    # Parent scatter traces are at figure positions 2*n_cats, 2*n_cats+1, …
    legend_vis: dict[int, object] = {}  # parent_j → True / "legendonly"
    for i, tidx in enumerate(indices):
        if tidx >= 2 * n_cats:
            pj = tidx - 2 * n_cats
            if pj < len(parents) and i < len(visible_vals):
                legend_vis[pj] = visible_vals[i]

    if not legend_vis:
        return no_update

    if len(legend_vis) == 1:
        # ── Single click: toggle this parent ──────────────────────────────────
        pj = next(iter(legend_vis))
        parent_name = parents[pj]
        current = list(current_filter or [])
        if parent_name in current:
            current.remove(parent_name)
        else:
            current.append(parent_name)
        if set(current) >= set(parents):
            return []
        return current

    else:
        # ── Double click: batch restyle from Plotly's isolate/restore ─────────
        # If every legend trace is being set to True → "restore all" action.
        if all(v is True for v in legend_vis.values()):
            return []
        # Otherwise Plotly is isolating the one parent whose trace is True.
        visible_parents = {parents[pj] for pj, v in legend_vis.items() if v is True}
        if visible_parents:
            hidden = [p for p in parents if p not in visible_parents]
            return hidden if hidden else []
        return []


@app.callback(
    Output("shell-output", "children"),
    Input("shell-run-btn", "n_clicks"),
    Input("shell-input", "n_submit"),
    State("shell-input", "value"),
    prevent_initial_call=True,
)
def run_shell(_btn, _enter, cmd_str):
    """Run an arbitrary hledger command and display the raw text output."""
    if not cmd_str or not cmd_str.strip():
        return no_update
    try:
        parts = shlex.split(cmd_str.strip())
    except ValueError as exc:
        return f"⚠ Parse error: {exc}"
    # Strip leading 'hledger' so users can type with or without it
    if parts and parts[0] in ("hledger", HLEDGER_BIN):
        parts = parts[1:]
    if not parts:
        return "⚠ No command given."
    cmd = hledger_cmd(*parts)
    header = "▶ " + " ".join(cmd) + "\n"
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except FileNotFoundError:
        return header + f"⚠ hledger not found at: {HLEDGER_BIN}"
    out = r.stdout
    if r.returncode != 0 and r.stderr:
        out += "\n⚠ " + r.stderr.strip()
    return header + out


@app.callback(
    Output("tx-modal", "style"),
    Output("tx-modal-title", "children"),
    Output("tx-modal-cmd", "children"),
    Output("tx-modal-content", "children"),
    Input("sm-graph", "clickData"),
    Input("hm-graph", "clickData"),
    Input("strip-graph", "clickData"),
    Input("tx-modal-close", "n_clicks"),
    Input("tx-modal-backdrop", "n_clicks"),
    State("strip-data-store", "data"),
    State("register-data-store", "data"),
    prevent_initial_call=True,
)
def handle_tx_popup(
    sm_click, hm_click, strip_click, _close, _backdrop, weekly_data, register_data
):
    """
    Open the transaction modal when a data point is clicked on any weekly chart,
    close it when the close button or backdrop is clicked.
    """
    triggered = callback_context.triggered_id
    hidden_style = {"display": "none"}

    if triggered in ("tx-modal-close", "tx-modal-backdrop"):
        return hidden_style, no_update, no_update, no_update

    if not weekly_data:
        return hidden_style, no_update, no_update, no_update

    visible_style = {"display": "block"}

    # Build label→date lookup from any account (all share same week structure)
    any_info = next(iter(weekly_data.values()))
    label_to_date = dict(
        zip(any_info["weeks"], any_info.get("week_dates", any_info["weeks"]))
    )
    # Sorted cats lists (must match the order used in the build functions)
    cats_sm = sorted(  # sm-graph: sorted by max spend desc (matches build_small_multiples_figure)
        weekly_data.keys(),
        key=lambda c: max(weekly_data[c]["amounts"], default=0),
        reverse=True,
    )
    cats_sorted = sorted(  # hm/strip-graph: sorted by average desc
        weekly_data.keys(),
        key=lambda c: weekly_data[c]["average"],
        reverse=True,
    )

    account = None
    week_date = None
    week_label = None

    try:
        if triggered == "sm-graph" and sm_click:
            pt = sm_click["points"][0]
            curve_idx = pt["curveNumber"]
            cat_idx = curve_idx // 2  # 2 traces per category (bar + avg line)
            if cat_idx < len(cats_sm):
                account = cats_sm[cat_idx]
                week_label = str(pt.get("x", "?"))
                week_date = label_to_date.get(week_label, week_label)

        elif triggered == "hm-graph" and hm_click:
            pt = hm_click["points"][0]
            short_name = str(pt.get("y", ""))
            week_label = str(pt.get("x", "?"))
            # Look up full account name by short name
            account = next(
                (k for k in weekly_data if k.split(":")[-1] == short_name), None
            )
            week_date = label_to_date.get(week_label, week_label)

        elif triggered == "strip-graph" and strip_click:
            pt = strip_click["points"][0]
            curve_idx = pt["curveNumber"]
            cat_idx = curve_idx // 2  # 2 traces per category: violin shape + points
            if cat_idx < len(cats_sorted):
                account = cats_sorted[cat_idx]
            # customdata: [original_$, week_label, week_date_ISO]
            cd = pt.get("customdata")
            if cd and len(cd) >= 3:
                week_label = str(cd[1])
                week_date = str(cd[2])
            elif cd and len(cd) >= 2:
                week_label = str(cd[1])
                week_date = label_to_date.get(week_label, week_label)

    except (KeyError, IndexError, TypeError):
        return hidden_style, no_update, no_update, no_update

    if not account or not week_date:
        return hidden_style, no_update, no_update, no_update

    short = account.split(":")[-1]
    title = f"{short}  ·  week of {week_date}"

    all_txns = (register_data or {}).get("txns", [])
    cmd_str = (register_data or {}).get("cmd", "")
    txns = filter_register_data(all_txns, account, week_date)

    return (
        visible_style,
        title,
        cmd_str,
        render_tx_table(txns),
    )


# ── Import source selection callbacks ─────────────────────────────────────────


def _build_period_args(period, begin, end):
    if begin and end:
        return ["--begin", begin, "--end", end], f"{begin} – {end}"
    if begin:
        return ["--begin", begin], f"from {begin}"
    if period == "from":
        earliest = get_ledger_start_date()
        if earliest:
            return ["--begin", earliest], f"from {earliest} (ledger start)"
        return [], "all time"
    return ["--period", period], PERIOD_LABELS.get(period, period)


@app.callback(
    Output("import-source-modal", "style"),
    Output("import-poll", "disabled"),
    Output("status-log", "children", allow_duplicate=True),
    Input("import-btn", "n_clicks"),
    Input("import-source-cancel", "n_clicks"),
    Input("import-debit-btn", "n_clicks"),
    Input("import-savings-btn", "n_clicks"),
    State("period-dd", "value"),
    State("depth-dd", "value"),
    State("begin-dp", "date"),
    State("end-dp", "date"),
    prevent_initial_call=True,
)
def handle_import_modal(_btn, _cancel, _debit, _savings, period, depth, begin, end):
    global _import_done, _import_no_new_tx, _import_result
    triggered = callback_context.triggered_id
    if triggered == "import-btn":
        return {"display": "block"}, no_update, no_update
    if triggered == "import-source-cancel":
        return {"display": "none"}, no_update, no_update
    source = "debit" if triggered == "import-debit-btn" else "savings"
    if not _import_lock.acquire(blocking=False):
        return {"display": "none"}, no_update, "⚠ Import already running — please wait."
    # Reset shared state before starting
    _import_log.clear()
    _import_done = False
    _import_no_new_tx = False
    _import_result = {}
    period_args, period_label = _build_period_args(period, begin, end)
    threading.Thread(
        target=_stream_import,
        args=(source, period_args, depth, period_label),
        daemon=True,
    ).start()
    return {"display": "none"}, False, no_update  # False = enable interval


# ── Bank navigation modal callback ────────────────────────────────────────────


@app.callback(
    Output("bank-nav-modal", "style"),
    Input("bank-nav-close", "n_clicks"),
    prevent_initial_call=True,
)
def close_bank_modal(_):
    return {"display": "none"}


# ── Import progress polling ───────────────────────────────────────────────────


@app.callback(
    Output("status-log", "children", allow_duplicate=True),
    Output("import-poll", "disabled", allow_duplicate=True),
    Output("sankey-graph", "figure", allow_duplicate=True),
    Output("bar-graph", "figure", allow_duplicate=True),
    Output("sm-graph", "figure", allow_duplicate=True),
    Output("sm-graph", "style", allow_duplicate=True),
    Output("hm-graph", "figure", allow_duplicate=True),
    Output("strip-data-store", "data", allow_duplicate=True),
    Output("register-data-store", "data", allow_duplicate=True),
    Output("strip-parent-filter", "data", allow_duplicate=True),
    Output("bank-nav-modal", "style", allow_duplicate=True),
    Input("import-poll", "n_intervals"),
    prevent_initial_call=True,
)
def poll_import(_):
    log = "\n".join(_import_log)
    if not _import_done:
        return log, False, *([no_update] * 9)
    r = _import_result
    bank_style = (
        {"display": "block"} if _import_no_new_tx and CFG.get("bank_url") else no_update
    )
    return (
        log,
        True,  # disable interval
        r.get("sankey-graph.figure", no_update),
        r.get("bar-graph.figure", no_update),
        r.get("sm-graph.figure", no_update),
        r.get("sm-graph.style", no_update),
        r.get("hm-graph.figure", no_update),
        r.get("strip-data-store.data", no_update),
        r.get("register-data-store.data", no_update),
        r.get("strip-parent-filter.data", no_update),
        bank_style,
    )


# ── Settings modal callbacks ──────────────────────────────────────────────────

_SETTINGS_DISK_KEYS = [
    "income_account",
    "expenses_account",
    "savings_account",
    "debit_account",
    "bank_url",
    "hledger_rules_debit",
    "hledger_rules_savings",
    "skip_txcat_debit",
    "skip_txcat_savings",
    "default_depth",
]

_DEPTH_BTN_BASE = {
    "border": "none",
    "borderRight": "1px solid #444",
    "padding": "7px 16px",
    "cursor": "pointer",
    "fontSize": "13px",
}
_DEPTH_BTN_LAST = {**_DEPTH_BTN_BASE, "borderRight": "none"}


def _depth_btn_styles(selected: int) -> tuple[dict, dict, dict]:
    def _s(val: int) -> dict:
        base = _DEPTH_BTN_LAST if val == 4 else _DEPTH_BTN_BASE
        if val == selected:
            return {
                **base,
                "backgroundColor": "#3b6fd4",
                "color": "white",
                "fontWeight": "600",
            }
        return {**base, "backgroundColor": "#2a2727", "color": FONT_COLOR}

    return _s(2), _s(3), _s(4)


def _bool_btn_styles(skip: bool) -> tuple[dict, dict]:
    """Return (run_style, skip_style) for a Yes/No skip-txcat toggle."""
    run_style = {
        **_DEPTH_BTN_BASE,
        "backgroundColor": "#2a2727" if skip else "#3b6fd4",
        "color": FONT_COLOR if skip else "white",
        "fontWeight": "400" if skip else "600",
    }
    skip_style = {
        **_DEPTH_BTN_LAST,
        "backgroundColor": "#3b6fd4" if skip else "#2a2727",
        "color": "white" if skip else FONT_COLOR,
        "fontWeight": "600" if skip else "400",
    }
    return run_style, skip_style


@app.callback(
    Output("settings-default-depth", "data", allow_duplicate=True),
    Output("settings-depth-btn-2", "style", allow_duplicate=True),
    Output("settings-depth-btn-3", "style", allow_duplicate=True),
    Output("settings-depth-btn-4", "style", allow_duplicate=True),
    Input("settings-depth-btn-2", "n_clicks"),
    Input("settings-depth-btn-3", "n_clicks"),
    Input("settings-depth-btn-4", "n_clicks"),
    prevent_initial_call=True,
)
def select_depth_btn(_2, _3, _4):
    val = int(callback_context.triggered_id.split("-")[-1])
    return (val, *_depth_btn_styles(val))


@app.callback(
    Output("settings-skip-txcat-debit", "data", allow_duplicate=True),
    Output("settings-skip-txcat-savings", "data", allow_duplicate=True),
    Output("settings-skip-txcat-debit-no", "style", allow_duplicate=True),
    Output("settings-skip-txcat-debit-yes", "style", allow_duplicate=True),
    Output("settings-skip-txcat-savings-no", "style", allow_duplicate=True),
    Output("settings-skip-txcat-savings-yes", "style", allow_duplicate=True),
    Input("settings-skip-txcat-debit-no", "n_clicks"),
    Input("settings-skip-txcat-debit-yes", "n_clicks"),
    Input("settings-skip-txcat-savings-no", "n_clicks"),
    Input("settings-skip-txcat-savings-yes", "n_clicks"),
    State("settings-skip-txcat-debit", "data"),
    State("settings-skip-txcat-savings", "data"),
    prevent_initial_call=True,
)
def select_skip_txcat(_dn, _dy, _sn, _sy, debit_val, savings_val):
    tid = callback_context.triggered_id
    if "debit" in tid:
        debit_val = "yes" in tid
    else:
        savings_val = "yes" in tid
    return (
        debit_val,
        savings_val,
        *_bool_btn_styles(debit_val),
        *_bool_btn_styles(savings_val),
    )


@app.callback(
    Output("settings-modal", "style"),
    Output("settings-income-account", "value"),
    Output("settings-expenses-account", "value"),
    Output("settings-savings-account", "value"),
    Output("settings-debit-account", "value"),
    Output("settings-bank-url", "value"),
    Output("settings-hledger-rules-debit", "value"),
    Output("settings-hledger-rules-savings", "value"),
    Output("settings-default-depth", "data"),
    Output("settings-depth-btn-2", "style"),
    Output("settings-depth-btn-3", "style"),
    Output("settings-depth-btn-4", "style"),
    Output("settings-skip-txcat-debit", "data"),
    Output("settings-skip-txcat-savings", "data"),
    Output("settings-skip-txcat-debit-no", "style"),
    Output("settings-skip-txcat-debit-yes", "style"),
    Output("settings-skip-txcat-savings-no", "style"),
    Output("settings-skip-txcat-savings-yes", "style"),
    Input("settings-btn", "n_clicks"),
    Input("settings-close", "n_clicks"),
    prevent_initial_call=True,
)
def handle_settings_modal(_, __):
    if callback_context.triggered_id == "settings-btn":
        depth = CFG.get("default_depth", 2)
        skip_d = bool(CFG.get("skip_txcat_debit", False))
        skip_s = bool(CFG.get("skip_txcat_savings", False))
        return (
            {"display": "block"},
            CFG["income_account"],
            CFG["expenses_account"],
            CFG["savings_account"],
            CFG["debit_account"],
            CFG.get("bank_url", ""),
            CFG.get("hledger_rules_debit", ""),
            CFG.get("hledger_rules_savings", ""),
            depth,
            *_depth_btn_styles(depth),
            skip_d,
            skip_s,
            *_bool_btn_styles(skip_d),
            *_bool_btn_styles(skip_s),
        )
    return ({"display": "none"},) + (no_update,) * 17


@app.callback(
    Output("depth-dd", "value"),
    Output("bank-nav-link", "href"),
    Output("import-debit-btn", "children"),
    Output("import-savings-btn", "children"),
    Input("settings-save", "n_clicks"),
    State("settings-income-account", "value"),
    State("settings-expenses-account", "value"),
    State("settings-savings-account", "value"),
    State("settings-debit-account", "value"),
    State("settings-bank-url", "value"),
    State("settings-hledger-rules-debit", "value"),
    State("settings-hledger-rules-savings", "value"),
    State("settings-skip-txcat-debit", "data"),
    State("settings-skip-txcat-savings", "data"),
    State("settings-default-depth", "data"),
    prevent_initial_call=True,
)
def save_settings(
    _,
    income,
    expenses,
    savings,
    debit,
    bank_url,
    rules_debit,
    rules_savings,
    skip_debit,
    skip_savings,
    depth,
):
    updates = {
        "income_account": income or CFG["income_account"],
        "expenses_account": expenses or CFG["expenses_account"],
        "savings_account": savings or CFG["savings_account"],
        "debit_account": debit or CFG["debit_account"],
        "bank_url": bank_url or "",
        "hledger_rules_debit": rules_debit or CFG.get("hledger_rules_debit", ""),
        "hledger_rules_savings": rules_savings or CFG.get("hledger_rules_savings", ""),
        "skip_txcat_debit": bool(skip_debit),
        "skip_txcat_savings": bool(skip_savings),
        "default_depth": int(depth) if depth else CFG.get("default_depth", 2),
    }
    CFG.update(updates)
    on_disk = {k: CFG[k] for k in _SETTINGS_DISK_KEYS}
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(on_disk, indent=2))
    set_props("settings-modal", {"style": {"display": "none"}})
    return (
        CFG["default_depth"],
        CFG["bank_url"],
        CFG["debit_account"],
        CFG["savings_account"],
    )


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="hledger Dashboard")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8050)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    print(f"\n  hledger Dashboard")
    print(f"  Accounts : {CFG}")
    print(f"  Open     →  http://{args.host}:{args.port}\n")
    app.run(host=args.host, port=args.port, debug=args.debug)
