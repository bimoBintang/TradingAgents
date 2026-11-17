#!/bin/bash
# Prepares persistent paths and env, (optionally) installs/configures MT5, then hands over to supervisord.
set -euo pipefail

# ── Persistent data (mount/keep /workspace across restarts) ──────────────────
DATA=/workspace/tradingagents
mkdir -p "$DATA/results" "$DATA/home" /workspace/ollama
ln -sfn "$DATA/home" /root/.tradingagents              # storage/journal DB lives under ~/.tradingagents
export DATABASE_URL="${DATABASE_URL:-sqlite:///$DATA/app.db}"
export TRADINGAGENTS_RESULTS_DIR="${TRADINGAGENTS_RESULTS_DIR:-$DATA/results}"
export OLLAMA_MODELS="${OLLAMA_MODELS:-/workspace/ollama}"
export TRADINGAGENTS_LLM_PRESET="${TRADINGAGENTS_LLM_PRESET:-ollama}"
export ENVIRONMENT="${ENVIRONMENT:-production}"         # FERNET_KEY is then mandatory (backend refuses to start without it)

# ── MetaTrader 5 (forex) is optional: only when MT5_LOGIN is set ─────────────
if [ -n "${MT5_LOGIN:-}" ]; then
  : "${MT5_PASSWORD:?set MT5_PASSWORD}" "${MT5_SERVER:?set MT5_SERVER}"
  export MT5_AUTOSTART=true
  MT5_DIR="$WINEPREFIX/drive_c/mt5"
  mkdir -p "$MT5_DIR"
  umask 077
  cat > "$MT5_DIR/common.ini" <<INI
[Common]
Login=${MT5_LOGIN}
Password=${MT5_PASSWORD}
Server=${MT5_SERVER}
[Experts]
AllowLiveTrading=1
Enabled=1
INI
  TERMINAL="$WINEPREFIX/drive_c/Program Files/MetaTrader 5/terminal64.exe"
  if [ ! -f "$TERMINAL" ]; then
    : "${MT5_SETUP_URL:?set MT5_SETUP_URL to your broker's (or MetaQuotes') mt5setup.exe}"
    echo "Installing MetaTrader 5 (first run)..."
    wget -q -O /tmp/mt5setup.exe "$MT5_SETUP_URL"
    xvfb-run -a wine /tmp/mt5setup.exe /auto || true
    wineserver -w
    rm -f /tmp/mt5setup.exe
    [ -f "$TERMINAL" ] || { echo "MT5 install failed: $TERMINAL not found" >&2; exit 1; }
  fi
  export MT5_RPYC_HOST="${MT5_RPYC_HOST:-127.0.0.1}" MT5_RPYC_PORT="${MT5_RPYC_PORT:-18812}"
else
  export MT5_AUTOSTART=false
fi

# -n: foreground; Ubuntu's supervisord.conf includes conf.d/*.conf
exec /usr/bin/supervisord -n -c /etc/supervisor/supervisord.conf
