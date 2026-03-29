#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  install.sh  —  sets up the hledger Finance Dashboard in a venv
#
#  Usage:
#    chmod +x install.sh
#    ./install.sh            # full setup: prompts for accounts, installs deps
#    ./install.sh --run      # also launches the server immediately after setup
#    ./install.sh --reconfigure   # re-run only the account name prompts
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

VENV_DIR="$(dirname "$0")/venv"
APP_DIR="$(dirname "$0")"
CONFIG_FILE="$APP_DIR/config.json"
ASSETS_DIR="$APP_DIR/assets"
CSS_FILE="$ASSETS_DIR/dashboard.css"
RUN_AFTER=false
RECONFIGURE=false

# ── Parse flags ───────────────────────────────────────────────────────────────
for arg in "$@"; do
    case "$arg" in
        --run)         RUN_AFTER=true ;;
        --reconfigure) RECONFIGURE=true ;;
        --help|-h)
            echo "Usage: $0 [--run] [--reconfigure]"
            echo "  --run           Launch the server immediately after setup"
            echo "  --reconfigure   Re-prompt for account names only (skip venv/deps)"
            exit 0 ;;
    esac
done

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║       hledger Finance Dashboard — installer          ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

# ── Account name configuration ────────────────────────────────────────────────
# Reads a key from config.json, falling back to a built-in default.
read_cfg() {
    local key="$1" default="$2"
    if [ -f "$CONFIG_FILE" ] && command -v python3 &>/dev/null; then
        val=$(python3 -c "
import json
try:
    d = json.load(open('$CONFIG_FILE'))
    print(d.get('$key', ''))
except Exception:
    print('')
" 2>/dev/null)
        echo "${val:-$default}"
    else
        echo "$default"
    fi
}

configure_accounts() {
    echo "── Account names ────────────────────────────────────────────────────────────"
    echo "  Enter your hledger account names (press Enter to accept the default)."
    echo "  These are the top-level account prefixes used in your journal file."
    echo ""

    default_income=$(read_cfg   "income_account"   "income")
    default_expenses=$(read_cfg "expenses_account" "expenses")
    default_savings=$(read_cfg  "savings_account"  "assets:bank:savings")
    default_debit=$(read_cfg    "debit_account"    "assets:bank:debit")

    read -r -p "  Income account   [$default_income]: " income_account
    income_account="${income_account:-$default_income}"

    read -r -p "  Expenses account [$default_expenses]: " expenses_account
    expenses_account="${expenses_account:-$default_expenses}"

    read -r -p "  Savings account  [$default_savings]: " savings_account
    savings_account="${savings_account:-$default_savings}"

    echo ""
    echo "  The debit/checking account reconciles the Sankey diagram."
    echo "  It accounts for prior-period balances that fund spending beyond income."
    read -r -p "  Debit account    [$default_debit]: " debit_account
    debit_account="${debit_account:-$default_debit}"

    cat > "$CONFIG_FILE" << ENDJSON
{
  "income_account":   "$income_account",
  "expenses_account": "$expenses_account",
  "savings_account":  "$savings_account",
  "debit_account":    "$debit_account"
}
ENDJSON

    echo ""
    echo "✓  config.json written:"
    echo "     income:   $income_account"
    echo "     expenses: $expenses_account"
    echo "     savings:  $savings_account"
    echo "     debit:    $debit_account"
    echo ""
}

# --reconfigure: update config only, then exit
if $RECONFIGURE; then
    configure_accounts
    echo "  Re-run  python app.py  to pick up the new account names."
    echo ""
    exit 0
fi

# ── Check Python 3.10+ ────────────────────────────────────────────────────────
PYTHON_BIN=""
for candidate in python3 python; do
    if command -v "$candidate" &>/dev/null; then
        ver=$("$candidate" -c "import sys; print(sys.version_info >= (3,10))")
        if [ "$ver" = "True" ]; then
            PYTHON_BIN="$candidate"
            break
        fi
    fi
done

if [ -z "$PYTHON_BIN" ]; then
    echo "✗  Python 3.10 or newer is required but was not found."
    echo "   Install it from https://python.org and re-run this script."
    exit 1
fi

echo "✓  Python: $($PYTHON_BIN --version)"

# ── Check hledger ─────────────────────────────────────────────────────────────
HLEDGER_BIN="${HLEDGER_BIN:-hledger}"
if command -v "$HLEDGER_BIN" &>/dev/null; then
    echo "✓  hledger: $($HLEDGER_BIN --version | head -1)"
else
    echo ""
    echo "⚠  hledger was not found on PATH."
    echo "   The dashboard will still install, but the Refresh button will"
    echo "   fail until hledger is available."
    echo ""
    echo "   Install hledger:"
    echo "     macOS  →  brew install hledger"
    echo "     Debian →  sudo apt install hledger"
    echo "     Other  →  https://hledger.org/install.html"
    echo ""
fi

# ── Account names ─────────────────────────────────────────────────────────────
if [ -f "$CONFIG_FILE" ]; then
    echo "✓  config.json already exists — skipping account setup"
    echo "   (run  ./install.sh --reconfigure  to change account names)"
    echo ""
else
    configure_accounts
fi

# ── Create / reuse virtual environment ────────────────────────────────────────
if [ -d "$VENV_DIR" ]; then
    echo "✓  Virtual environment already exists at $VENV_DIR — skipping creation"
else
    echo "→  Creating virtual environment at $VENV_DIR …"
    "$PYTHON_BIN" -m venv "$VENV_DIR"
    echo "✓  Virtual environment created"
fi

# ── Create assets/ directory and write CSS ────────────────────────────────────
mkdir -p "$ASSETS_DIR"

if [ -f "$CSS_FILE" ]; then
    echo "✓  assets/dashboard.css already exists — skipping"
else
    cat > "$CSS_FILE" << 'ENDCSS'
/* hledger Dashboard — responsive graph sizing
   --ctrl-h: total pixel height of everything above the tab panels
   (heading + controls card + status log + tab bar).
   Increase this value if you add controls above the charts. */
:root { --ctrl-h: 268px; }

.graph-frame {
    height: calc(100vh - var(--ctrl-h));
    /* Cap width at 3:2 aspect ratio relative to the available height */
    width: min(100%, calc((100vh - var(--ctrl-h)) * 1.5));
    margin: 0 auto;
}

/* Make Plotly fill the frame rather than using its own pixel dimensions */
.graph-frame .js-plotly-plot,
.graph-frame .plot-container {
    height: 100% !important;
    width:  100% !important;
}
ENDCSS
    echo "✓  assets/dashboard.css created"
fi

# ── Activate venv and install deps ────────────────────────────────────────────
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

echo "→  Installing Python dependencies …"
pip install --quiet --upgrade pip
pip install --quiet -r "$APP_DIR/requirements.txt"

echo "✓  All dependencies installed"

echo ""
echo "════════════════════════════════════════════════════════"
echo "  Installation complete!"
echo ""
echo "  To start the dashboard:"
echo "    source venv/bin/activate"
echo "    python app.py"
echo ""
echo "  Then open  →  http://127.0.0.1:8050"
echo ""
echo "  Optional flags:"
echo "    python app.py --port 9090       # change port"
echo "    python app.py --debug           # enable hot-reload"
echo "    python app.py --host 0.0.0.0    # expose on LAN"
echo ""
echo "  To change account names:"
echo "    ./install.sh --reconfigure"
echo ""
echo "  Environment variables:"
echo "    HLEDGER_BIN=/path/to/hledger python app.py"
echo "════════════════════════════════════════════════════════"
echo ""

# ── Optionally launch ─────────────────────────────────────────────────────────
if $RUN_AFTER; then
    echo "Launching dashboard …"
    python "$APP_DIR/app.py"
fi
