"""
hledger Interactive Finance Dashboard
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
import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import Dash, Input, Output, State, callback_context, dcc, html, no_update
from plotly.subplots import make_subplots

# ── Config ─────────────────────────────────────────────────────────────────────

CONFIG_PATH = Path(__file__).parent / "config.json"

CONFIG_DEFAULTS: dict[str, str] = {
    "income_account": "income",
    "expenses_account": "expenses",
    "savings_account": "assets:bank:savings",
    "debit_account": "assets:bank:debit",
}


def load_config() -> dict[str, str]:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            on_disk = json.load(f)
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

# ── Weekly plot formatting ────────────────────────────────────────────────–––––
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
        [HLEDGER_BIN]
        + args
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
    r = subprocess.run([HLEDGER_BIN, "print"], capture_output=True, text=True)
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
        [HLEDGER_BIN, "bal", account]
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
    cmd = [HLEDGER_BIN, "register", account] + period_args + ["-O", "csv"]
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


def build_small_multiples_figure(weekly_data: dict, period_label: str) -> go.Figure:
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

    # ── Grid layout: minimise empty cells (n_cols*n_rows - n), prefer more
    # columns on ties so the figure stays landscape rather than tall. ──
    _plot_w = 1200  # assumed usable width (px); 72 = l+r figure margins
    _min_sw = 130  # minimum readable subplot width (px)
    _max_cols = max(1, int(_plot_w / _min_sw))  # hard ceiling (~8 at 1200 px)
    _ideal_nc = math.ceil(math.sqrt(n))
    _lo = max(1, _ideal_nc - 2)
    _hi = min(n, min(_ideal_nc * 2, _max_cols))

    best_empty, best_n_cols = n + 1, _ideal_nc
    for _nc in range(_lo, _hi + 1):
        _nr = math.ceil(n / _nc)
        _empty = _nc * _nr - n
        if _empty < best_empty or (_empty == best_empty and _nc > best_n_cols):
            best_empty = _empty
            best_n_cols = _nc

    n_cols = best_n_cols
    n_rows = math.ceil(n / n_cols)

    # ── Figure height: scale so each subplot hits aspect ratio ~1.2:1 (w:h),
    # which is comfortably within the [1:1, 3:2] allowed band. ──
    _subplot_w = _plot_w / n_cols
    _subplot_h = _subplot_w / 1.2
    fig_height = int(n_rows * _subplot_h)  # 128 px ≈ top + bottom margins
    short_names = [c.split(":")[-1] for c in cats]

    fig = make_subplots(
        rows=n_rows,
        cols=n_cols,
        subplot_titles=short_names,
        shared_xaxes=False,
        shared_yaxes=True,
        vertical_spacing=max(0.06, 0.333 / n_rows),
        horizontal_spacing=0.02,
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
        automargin=True,
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
    return fig


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
    short_names = [c.split(":")[-1] for c in cats]

    # ── Parent-category colour mapping ─────────────────────────────────────────
    # The expenses account prefix has N parts; the next segment is the "parent".
    # e.g.  expenses_account="expenses"  →  "expenses:food:groceries" → parent "food"
    _exp_depth = len(CFG["expenses_account"].split(":"))

    def _get_parent(cat: str) -> str:
        parts = cat.split(":")
        return parts[_exp_depth] if len(parts) > _exp_depth else parts[-1]

    _parents_ordered: list[str] = list(dict.fromkeys(_get_parent(c) for c in cats))
    _parent_color: dict[str, str] = {
        p: PARENT_CATEGORY_COLORS[i % len(PARENT_CATEGORY_COLORS)]
        for i, p in enumerate(_parents_ordered)
    }

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
    for parent in _parents_ordered:
        c = _parent_color[parent]
        fig.add_trace(
            go.Scatter(
                x=[None],
                y=[None],
                mode="markers",
                marker=dict(color=c.replace("0.95", "0.85"), size=12, symbol="square"),
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
        html.H1("hledger Finance Dashboard", style=STYLE_TITLE),
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
                                        value=2,
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
                    label="Sankey — Income → Savings & Expenses",
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
                    label="Monthly Trend — Income vs Expenses",
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
                    label="Weekly — Small multiples",
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
                    label="Weekly — Heatmap",
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
                    label="Weekly — Distribution",
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
            ],
        ),
        # ── Hidden state stores ────────────────────────────────────────────────────
        dcc.Store(id="clear-signal", data=0),
        dcc.Store(id="strip-orientation", data="v"),
        dcc.Store(id="violin-scale", data="linear"),
        dcc.Store(id="strip-data-store"),
        dcc.Store(id="register-data-store"),
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
    Output("hm-graph", "figure"),
    Output("strip-data-store", "data"),
    Output("register-data-store", "data"),
    Output("status-log", "children"),
    Output("status-log", "style"),
    Input("refresh-btn", "n_clicks"),
    State("period-dd", "value"),
    State("depth-dd", "value"),
    State("begin-dp", "date"),
    State("end-dp", "date"),
    prevent_initial_call=True,
)
def refresh(n_clicks, period, depth, begin, end):

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
            no_update,
            no_update,
            no_update,
            msg,
            STYLE_ERROR,
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
    inc_m_raw, lm1 = run_hledger(["bal", inc_acct], period_args, depth, monthly=True)
    exp_m_raw, lm2 = run_hledger(["bal", exp_acct], period_args, depth, monthly=True)
    log_lines += [lm1, lm2]

    if inc_m_raw.empty or exp_m_raw.empty:
        bar_fig = empty_bar_figure("No monthly data available for this period.")
    else:
        try:
            s_income = pivot_monthly(inc_m_raw, flip=True)
            s_expenses = pivot_monthly(exp_m_raw, flip=False)
            months = s_income.index.tolist()
            bar_fig = go.Figure(
                data=[
                    go.Bar(
                        name="Income",
                        x=months,
                        y=s_income.values,
                        marker_color=COLOR_INCOME,
                    ),
                    go.Bar(
                        name="Expenses",
                        x=months,
                        y=s_expenses.values,
                        marker_color=COLOR_EXPENSE,
                    ),
                ],
                layout=dark_layout(
                    f"Monthly Income vs Expenses  [{period_label}]",
                    barmode="group",
                    xaxis=dict(
                        title="Month",
                        color=FONT_COLOR,
                        gridcolor=BORDER,
                        linecolor=BORDER,
                    ),
                    yaxis=dict(
                        title="Amount",
                        color=FONT_COLOR,
                        gridcolor=BORDER,
                        linecolor=BORDER,
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

    sm_fig = build_small_multiples_figure(weekly_data, period_label)
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
        hm_fig,
        weekly_data,
        register_data,
        "\n".join(log_lines),
        STYLE_STATUS,
    )


@app.callback(
    Output("strip-graph", "figure"),
    Input("strip-data-store", "data"),
    Input("strip-orientation", "data"),
    Input("violin-scale", "data"),
    State("period-dd", "value"),
    prevent_initial_call=False,
)
def update_strip_plot(data, orientation, scale_mode, period):
    if not data:
        return empty_strip_figure("No data — press ↻ Refresh")
    period_label = PERIOD_LABELS.get(period, period) if period else ""
    return build_strip_figure(
        data, period_label, orientation, scale_mode or "transform"
    )


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


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="hledger Finance Dashboard")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8050)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    print(f"\n  hledger Finance Dashboard")
    print(f"  Accounts : {CFG}")
    print(f"  Open     →  http://{args.host}:{args.port}\n")
    app.run(host=args.host, port=args.port, debug=args.debug)
