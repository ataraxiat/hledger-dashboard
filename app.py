"""
hledger Interactive Finance Dashboard
======================================
Dash web-app equivalent of hledger_sankey.ipynb.

Run:
    python app.py
Then open http://127.0.0.1:8050 in your browser.

Requirements:
    hledger must be on $PATH (or set HLEDGER_BIN env var).
    Python packages: see requirements.txt
    Account names: edit config.json (created by install.sh)
"""

from __future__ import annotations

import io
import json
import os
import re
import subprocess
from datetime import date
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from dash import Dash, Input, Output, State, callback_context, dcc, html, no_update

# ── Config ─────────────────────────────────────────────────────────────────────

CONFIG_PATH = Path(__file__).parent / "config.json"

CONFIG_DEFAULTS: dict[str, str] = {
    "income_account":   "income",
    "expenses_account": "expenses",
    "savings_account":  "assets:bank:savings",
    "debit_account":    "assets:bank:debit",
}


def load_config() -> dict[str, str]:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            on_disk = json.load(f)
        return {**CONFIG_DEFAULTS, **on_disk}
    return dict(CONFIG_DEFAULTS)


CFG = load_config()

# ── Colour palette (dark theme) ────────────────────────────────────────────────
COLOR_INCOME  = "rgba(110, 160, 255, 0.95)"
COLOR_SAVINGS = "rgba( 50, 230, 170, 0.95)"
COLOR_EXPENSE = "rgba(255, 110,  90, 0.95)"
COLOR_DEBIT   = "rgba(200, 160,  80, 0.95)"   # amber — prior balance / retained
LINK_INCOME   = "rgba(110, 160, 255, 0.35)"
LINK_SAVINGS  = "rgba( 50, 230, 170, 0.35)"
LINK_EXPENSE  = "rgba(255, 110,  90, 0.35)"
LINK_DEBIT    = "rgba(200, 160,  80, 0.35)"
FONT_COLOR    = "#d8d8d8"
BG            = "#151313"
CARD_BG       = "#1e1b1b"
BORDER        = "#2e2b2b"

HLEDGER_BIN = os.environ.get("HLEDGER_BIN", "hledger")

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
    col_map  = {c.lower(): c for c in df.columns}
    acct_col = col_map.get("account", df.columns[0])
    bal_col  = col_map.get("balance", df.columns[-1])
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
    depth=None omits the -N depth flag (used for single named-account queries).
    Returns (empty DataFrame, error_string) on failure.
    """
    depth_flag = [f"-{depth}"] if depth is not None else []
    extra      = ["--monthly"] if monthly else []
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


# ── Sankey builder ─────────────────────────────────────────────────────────────

class SankeyBuilder:
    """Incrementally collect nodes and links for a Plotly Sankey trace."""

    def __init__(self) -> None:
        self._nodes: list[str]      = []
        self._idx:   dict[str, int] = {}
        self.links:  list[dict]     = []

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
        self.links.append(dict(
            source=self.node(source),
            target=self.node(target),
            value=round(value, 2),
            color=color,
        ))

    def to_plotly(self, node_colors: list[str] | None = None) -> dict:
        n      = len(self._nodes)
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
                value= [lk["value"]  for lk in self.links],
                color= [lk["color"]  for lk in self.links],
                hovertemplate=(
                    "%{source.customdata} → %{target.customdata}"
                    "<br>%{value:,.2f}<extra></extra>"
                ),
            ),
        )


def build_sankey(
    income_df:     pd.DataFrame,
    expenses_df:   pd.DataFrame,
    savings_df:    pd.DataFrame,
    debit_change:  float = 0.0,
    debit_account: str   = "",
) -> SankeyBuilder:
    """
    Build the full Sankey node/link graph.

    debit_change is the net period change in the debit/checking account
    (hledger convention: positive = account grew; negative = account shrank).

    To keep inflows == outflows:
      debit_change < 0  → prior balance was consumed → add as income-side inflow
      debit_change > 0  → income was retained in checking → add as outflow
    """
    sb           = SankeyBuilder()
    TOTAL_INCOME = "income (total)"

    # 1. income sub-accounts → income (total)
    for _, row in income_df.iterrows():
        sb.link(row["account"], TOTAL_INCOME, row["amount"], LINK_INCOME)

    # 2. debit account balance adjustment ──────────────────────────────────────
    debit_label_in  = f"{debit_account} (prior balance)"
    debit_label_out = f"{debit_account} (retained)"
    if debit_change < 0:
        # Account shrank → prior balance fuelled spending → treat as inflow
        sb.link(debit_label_in, TOTAL_INCOME, abs(debit_change), LINK_DEBIT)
    elif debit_change > 0:
        # Account grew → some income retained in checking → treat as outflow
        sb.link(TOTAL_INCOME, debit_label_out, debit_change, LINK_DEBIT)

    # 3. income (total) → savings ──────────────────────────────────────────────
    savings_acct  = CFG["savings_account"]
    total_savings = savings_df["amount"].sum()
    if total_savings > 0:
        if len(savings_df) > 1:
            sb.link(TOTAL_INCOME, savings_acct, total_savings, LINK_SAVINGS)
            for _, row in savings_df.iterrows():
                sb.link(savings_acct, row["account"], row["amount"], LINK_SAVINGS)
        else:
            sb.link(TOTAL_INCOME, savings_df.iloc[0]["account"],
                    total_savings, LINK_SAVINGS)

    # 4. income (total) → expense depth-2 → expense leaves ────────────────────
    def depth2(acct: str) -> str:
        parts = acct.split(":")
        return ":".join(parts[:2]) if len(parts) >= 2 else acct

    if not expenses_df.empty:
        exp           = expenses_df.copy()
        exp["parent"] = exp["account"].apply(depth2)
        for parent, subtotal in exp.groupby("parent")["amount"].sum().items():
            sb.link(TOTAL_INCOME, parent, subtotal, LINK_EXPENSE)
        for _, row in exp.iterrows():
            if row["account"] != row["parent"]:
                sb.link(row["parent"], row["account"], row["amount"], LINK_EXPENSE)

    # 5. Assign node colours ───────────────────────────────────────────────────
    income_pfx   = CFG["income_account"]
    savings_pfx  = CFG["savings_account"].split(":")[0]
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

def dark_layout(title: str, height: int | None = None, **kwargs) -> go.Layout:
    return go.Layout(
        title=dict(text=title, font=dict(size=18, color=FONT_COLOR)),
        font=dict(family="Inter, Arial, sans-serif", size=12, color=FONT_COLOR),
        autosize=True,
        **({"height": height} if height is not None else {}),
        margin=dict(l=48, r=48, t=64, b=48, pad=2),
        paper_bgcolor=BG,
        plot_bgcolor=BG,
        **kwargs,
    )


def empty_sankey_figure(message: str = "Click Refresh to load data") -> go.Figure:
    fig = go.Figure(layout=dark_layout("Income → Savings & Expenses"))
    fig.add_annotation(
        text=message, x=0.5, y=0.5, xref="paper", yref="paper",
        showarrow=False, font=dict(size=16, color=FONT_COLOR),
    )
    return fig


def empty_bar_figure(message: str = "Click Refresh to load data") -> go.Figure:
    fig = go.Figure(layout=dark_layout("Monthly Income vs Expenses"))
    fig.add_annotation(
        text=message, x=0.5, y=0.5, xref="paper", yref="paper",
        showarrow=False, font=dict(size=16, color=FONT_COLOR),
    )
    return fig


def pivot_monthly(df: pd.DataFrame, flip: bool = False) -> pd.Series:
    """Collapse a monthly hledger CSV into a Series indexed by month label."""
    month_cols = [c for c in df.columns if c not in ("account", "total")]
    totals     = df[month_cols].apply(lambda col: col.map(parse_amount)).sum()
    return -totals if flip else totals


# ── Dash app ───────────────────────────────────────────────────────────────────

app = Dash(
    __name__,
    title="hledger Dashboard",
    meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1"}],
)

# ── Styles ─────────────────────────────────────────────────────────────────────
STYLE_PAGE    = {"backgroundColor": BG, "minHeight": "100vh",
                 "fontFamily": "Inter, Arial, sans-serif",
                 "color": FONT_COLOR, "padding": "16px"}
STYLE_CARD    = {"backgroundColor": CARD_BG, "border": f"1px solid {BORDER}",
                 "borderRadius": "8px", "padding": "16px", "marginBottom": "16px"}
STYLE_LABEL   = {"color": FONT_COLOR, "fontSize": "13px", "marginBottom": "4px"}
STYLE_BTN_PRIMARY = {
    "backgroundColor": "#3b6fd4", "color": "white", "border": "none",
    "borderRadius": "4px", "padding": "8px 18px",
    "cursor": "pointer", "fontSize": "13px", "fontWeight": "600",
}
STYLE_BTN_WARN = {
    "backgroundColor": "#7a5a1e", "color": "#f0c060", "border": "none",
    "borderRadius": "4px", "padding": "8px 14px",
    "cursor": "pointer", "fontSize": "13px",
}
STYLE_BTN_SMALL_WARN = {
    **STYLE_BTN_WARN, "padding": "6px 10px", "fontSize": "12px",
}
STYLE_STATUS  = {
    "backgroundColor": "#0d0c0c", "border": f"1px solid {BORDER}",
    "borderRadius": "4px", "padding": "10px 14px",
    "fontFamily": "monospace", "fontSize": "12px",
    "color": "#aaa", "whiteSpace": "pre-wrap",
    "minHeight": "36px", "marginBottom": "16px",
}
STYLE_ERROR   = {**STYLE_STATUS, "color": "#ff7c6e", "border": "1px solid #7a2a20"}
STYLE_TITLE   = {"color": FONT_COLOR, "fontSize": "22px",
                 "fontWeight": "700", "marginBottom": "16px"}


def _label(text: str) -> html.Div:
    return html.Div(text, style=STYLE_LABEL)


app.layout = html.Div(style=STYLE_PAGE, children=[

    # CSS is in assets/dashboard.css — Dash auto-serves that directory.

    html.H1("hledger Finance Dashboard", style=STYLE_TITLE),

    # ── Controls card ──────────────────────────────────────────────────────────
    html.Div(style=STYLE_CARD, children=[

        # Row 1: period preset + depth
        html.Div(style={"display": "flex", "gap": "24px", "flexWrap": "wrap",
                        "marginBottom": "12px"}, children=[
            html.Div([
                _label("Period"),
                dcc.Dropdown(
                    id="period-dd",
                    options=[
                        {"label": "This year",      "value": "thisyear"},
                        {"label": "Last year",      "value": "lastyear"},
                        {"label": "This quarter",   "value": "thisquarter"},
                        {"label": "Last quarter",   "value": "lastquarter"},
                        {"label": "This month",     "value": "thismonth"},
                        {"label": "Last month",     "value": "lastmonth"},
                        {"label": "Last 12 months", "value": "last12months"},
                    ],
                    value="thisyear",
                    clearable=False,
                    style={"width": "200px", "backgroundColor": "#252222",
                           "color": FONT_COLOR},
                ),
            ]),
            html.Div([
                _label("Account depth"),
                dcc.Dropdown(
                    id="depth-dd",
                    options=[
                        {"label": "Level 2 — categories",   "value": 2},
                        {"label": "Level 3 — sub-accounts", "value": 3},
                        {"label": "Level 4 — detail",       "value": 4},
                    ],
                    value=3,
                    clearable=False,
                    style={"width": "220px", "backgroundColor": "#252222",
                           "color": FONT_COLOR},
                ),
            ]),
        ]),

        # Row 2: date pickers + buttons
        html.Div(style={"display": "flex", "gap": "16px", "flexWrap": "wrap",
                        "alignItems": "flex-end"}, children=[
            html.Div([
                _label("From date (overrides Period)"),
                html.Div(style={"display": "flex", "gap": "6px",
                                "alignItems": "center"}, children=[
                    dcc.DatePickerSingle(
                        id="begin-dp",
                        placeholder="YYYY-MM-DD",
                        display_format="YYYY-MM-DD",
                        style={"backgroundColor": "#252222"},
                    ),
                    html.Button("Today", id="begin-today-btn", n_clicks=0,
                                style=STYLE_BTN_SMALL_WARN),
                ]),
            ]),
            html.Div([
                _label("To date"),
                html.Div(style={"display": "flex", "gap": "6px",
                                "alignItems": "center"}, children=[
                    dcc.DatePickerSingle(
                        id="end-dp",
                        placeholder="YYYY-MM-DD",
                        display_format="YYYY-MM-DD",
                        style={"backgroundColor": "#252222"},
                    ),
                    html.Button("Today", id="end-today-btn", n_clicks=0,
                                style=STYLE_BTN_SMALL_WARN),
                ]),
            ]),
            html.Div([
                _label("\u00a0"),
                html.Button("✕ Clear dates", id="clear-btn", n_clicks=0,
                            style=STYLE_BTN_WARN),
            ]),
            html.Div([
                _label("\u00a0"),
                html.Button("↻ Refresh", id="refresh-btn", n_clicks=0,
                            style=STYLE_BTN_PRIMARY),
            ]),
        ]),
    ]),

    # ── Status / error log ─────────────────────────────────────────────────────
    html.Pre(id="status-log", style=STYLE_STATUS,
             children="Ready — press ↻ Refresh to fetch data from hledger."),

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
                style={"backgroundColor": CARD_BG, "color": "#999",
                       "border": f"1px solid {BORDER}"},
                selected_style={"backgroundColor": BG, "color": FONT_COLOR,
                                "border": f"1px solid {BORDER}",
                                "borderBottom": f"1px solid {BG}"},
                children=[
                    html.Div(className="graph-frame", children=[
                        dcc.Graph(
                            id="sankey-graph",
                            figure=empty_sankey_figure(),
                            config={"displayModeBar": True,
                                    "modeBarButtonsToRemove": ["lasso2d", "select2d"],
                                    "responsive": True},
                            style={"height": "100%", "width": "100%"},
                        ),
                    ]),
                ],
            ),
            dcc.Tab(
                label="Monthly Trend — Income vs Expenses",
                value="tab-trend",
                style={"backgroundColor": CARD_BG, "color": "#999",
                       "border": f"1px solid {BORDER}"},
                selected_style={"backgroundColor": BG, "color": FONT_COLOR,
                                "border": f"1px solid {BORDER}",
                                "borderBottom": f"1px solid {BG}"},
                children=[
                    html.Div(className="graph-frame", children=[
                        dcc.Graph(
                            id="bar-graph",
                            figure=empty_bar_figure(),
                            config={"displayModeBar": True, "responsive": True},
                            style={"height": "100%", "width": "100%"},
                        ),
                    ]),
                ],
            ),
        ],
    ),

    dcc.Store(id="clear-signal", data=0),
    html.Div(id="_resize-dummy", style={"display": "none"}),
])


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


@app.callback(
    Output("begin-dp", "date"),
    Output("end-dp",   "date"),
    Input("clear-btn",       "n_clicks"),
    Input("begin-today-btn", "n_clicks"),
    Input("end-today-btn",   "n_clicks"),
    prevent_initial_call=True,
)
def handle_date_buttons(_clear, _begin_today, _end_today):
    """Clear both dates, or stamp one of them with today's date."""
    today     = date.today().isoformat()
    triggered = callback_context.triggered_id
    if triggered == "begin-today-btn":
        return today, no_update
    if triggered == "end-today-btn":
        return no_update, today
    return None, None   # clear-btn


@app.callback(
    Output("sankey-graph", "figure"),
    Output("bar-graph",    "figure"),
    Output("status-log",   "children"),
    Output("status-log",   "style"),
    Input("refresh-btn",   "n_clicks"),
    State("period-dd",  "value"),
    State("depth-dd",   "value"),
    State("begin-dp",   "date"),
    State("end-dp",     "date"),
    prevent_initial_call=True,
)
def refresh(n_clicks, period, depth, begin, end):

    # ── Guardrail: --end without --begin ───────────────────────────────────────
    # hledger balance with only --end returns cumulative totals from the very
    # start of the ledger, including opening balances from prior periods.
    # This makes the Sankey inaccurate, so we block it and explain why.
    if end and not begin:
        msg = (
            "⚠ Invalid date range: a To date is set without a From date.\n\n"
            "Using only --end would show cumulative balances from the start of\n"
            "your ledger (including opening balances from prior periods), which\n"
            "makes the Sankey totals incorrect.\n\n"
            "Fix: also set a From date, or clear the To date and use the\n"
            "Period dropdown instead."
        )
        return no_update, no_update, msg, STYLE_ERROR

    # ── Build period args ──────────────────────────────────────────────────────
    if begin and end:
        period_args  = ["--begin", begin, "--end", end]
        period_label = f"{begin} – {end}"
    elif begin:
        period_args  = ["--begin", begin]
        period_label = f"from {begin}"
    else:
        period_args  = ["--period", period]
        period_label = period

    inc_acct = CFG["income_account"]
    exp_acct = CFG["expenses_account"]
    sav_acct = CFG["savings_account"]
    deb_acct = CFG["debit_account"]

    log_lines: list[str] = []

    # ── Fetch Sankey data ──────────────────────────────────────────────────────
    inc_raw, l1 = run_hledger(["bal", inc_acct], period_args, depth)
    exp_raw, l2 = run_hledger(["bal", exp_acct], period_args, depth)
    sav_raw, l3 = run_hledger(["bal", sav_acct], period_args, depth)
    # No depth flag for the debit account — it's a single named account and
    # a depth flag would aggregate it into its parent (e.g. "assets").
    deb_raw, l4 = run_hledger(["bal", deb_acct], period_args, depth=None)
    log_lines += [l1, l2, l3, l4]

    inc_df = normalise(inc_raw, flip_sign=True)
    exp_df = normalise(exp_raw, flip_sign=False)
    sav_df = normalise(sav_raw, flip_sign=False)
    deb_df = normalise(deb_raw, flip_sign=False)

    # Net change in the debit account over the period.
    # hledger reports asset changes as positive (grew) / negative (shrank).
    debit_change = float(deb_df["amount"].sum()) if not deb_df.empty else 0.0
    log_lines.append(
        f"  {deb_acct} net change: {debit_change:+.2f}"
        + (" → prior balance consumed (added as inflow)" if debit_change < 0
           else " → income retained in checking (added as outflow)" if debit_change > 0
           else " → no change")
    )

    # ── Build Sankey figure ────────────────────────────────────────────────────
    if inc_df.empty and exp_df.empty:
        sankey_fig = empty_sankey_figure(
            "No income / expense data returned.\n"
            "Check that hledger is on $PATH and your journal has transactions."
        )
    else:
        sb      = build_sankey(inc_df, exp_df, sav_df, debit_change, deb_acct)
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

    # ── Fetch monthly trend data ───────────────────────────────────────────────
    inc_m_raw, lm1 = run_hledger(["bal", inc_acct], period_args, depth, monthly=True)
    exp_m_raw, lm2 = run_hledger(["bal", exp_acct], period_args, depth, monthly=True)
    log_lines += [lm1, lm2]

    if inc_m_raw.empty or exp_m_raw.empty:
        bar_fig = empty_bar_figure("No monthly data available for this period.")
    else:
        try:
            s_income   = pivot_monthly(inc_m_raw, flip=True)
            s_expenses = pivot_monthly(exp_m_raw, flip=False)
            months     = s_income.index.tolist()
            bar_fig    = go.Figure(
                data=[
                    go.Bar(name="Income",   x=months, y=s_income.values,
                           marker_color=COLOR_INCOME),
                    go.Bar(name="Expenses", x=months, y=s_expenses.values,
                           marker_color=COLOR_EXPENSE),
                ],
                layout=dark_layout(
                    f"Monthly Income vs Expenses  [{period_label}]",
                    barmode="group",
                    xaxis=dict(title="Month",  color=FONT_COLOR,
                               gridcolor=BORDER, linecolor=BORDER),
                    yaxis=dict(title="Amount", color=FONT_COLOR,
                               gridcolor=BORDER, linecolor=BORDER),
                    legend=dict(
                        orientation="h", yanchor="bottom", y=1.02,
                        xanchor="right", x=1, font=dict(color=FONT_COLOR),
                    ),
                ),
            )
            log_lines.append("✓ Monthly trend chart updated")
        except Exception as exc:
            bar_fig = empty_bar_figure(f"Error building trend chart: {exc}")
            log_lines.append(f"⚠ Trend chart error: {exc}")

    return sankey_fig, bar_fig, "\n".join(log_lines), STYLE_STATUS


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="hledger Finance Dashboard")
    parser.add_argument("--host",  default="127.0.0.1")
    parser.add_argument("--port",  type=int, default=8050)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    print(f"\n  hledger Finance Dashboard")
    print(f"  Accounts : {CFG}")
    print(f"  Open     →  http://{args.host}:{args.port}\n")
    app.run(host=args.host, port=args.port, debug=args.debug)
