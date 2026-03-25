"""Telegram Bot notifier for TradingAgents.

Sends trading alerts via Telegram Bot API.
All methods are fault-tolerant — notification failures never interrupt trading.

Setup:
1. Create a bot with @BotFather, get the token
2. Start a chat with the bot, get your chat_id (use @userinfobot)
3. Set config: notifications.telegram_bot_token + telegram_chat_id
"""

import json
import logging
import time
import threading
from datetime import datetime
from typing import Optional, Dict, Any
from urllib.request import Request, urlopen
from urllib.error import URLError
from urllib.parse import quote

logger = logging.getLogger(__name__)


class Notifier:
    """Telegram Bot notifier for trading alerts.

    Sends formatted messages for trade executions, rejections,
    stop-loss hits, kill switch activations, and daily summaries.

    All public methods are fault-tolerant:
    they log warnings on failure but never raise exceptions.

    Usage:
        notifier = Notifier(config)
        notifier.send_trade_alert(order_result)
        notifier.send_daily_summary(report)
    """

    def __init__(self, config: dict):
        """Initialize the Telegram notifier.

        Args:
            config: Full application config dict
        """
        notif_cfg = config.get("notifications", {})
        self.enabled = notif_cfg.get("enabled", False)
        self.bot_token = notif_cfg.get("telegram_bot_token", "")
        self.chat_id = notif_cfg.get("telegram_chat_id", "")

        # Alert toggles
        self.alert_on_trade = notif_cfg.get("alert_on_trade", True)
        self.alert_on_rejection = notif_cfg.get("alert_on_rejection", True)
        self.alert_on_stop_loss = notif_cfg.get("alert_on_stop_loss", True)
        self.alert_on_kill_switch = notif_cfg.get("alert_on_kill_switch", True)
        self.daily_summary_enabled = notif_cfg.get("daily_summary_enabled", True)

        # Rate limiting
        self._rate_limit = notif_cfg.get("rate_limit_per_minute", 30)
        self._send_times: list = []
        self._lock = threading.Lock()

        if self.enabled and self.bot_token and self.chat_id:
            print(f"[Notifier] ✅ Telegram Bot enabled (chat_id: {self.chat_id[:6]}...)")
        elif self.enabled:
            print("[Notifier] ⚠️ Telegram enabled but bot_token/chat_id missing")
            self.enabled = False

    # ── Public Alert Methods ──────────────────────────────────────────

    def send_trade_alert(self, order_result, ticker: str = "") -> None:
        """Send alert for an executed trade.

        Args:
            order_result: OrderResult object
            ticker: Ticker symbol (fallback)
        """
        if not self.enabled or not self.alert_on_trade:
            return

        try:
            t = ticker or getattr(order_result, 'ticker', '???')
            side = getattr(order_result.side, 'value', str(order_result.side))
            status = getattr(order_result.status, 'value', str(order_result.status))
            qty = order_result.filled_quantity
            price = order_result.filled_price or 0

            emoji = "🟢" if side == "BUY" else "🔴"
            msg = (
                f"{emoji} *Trade Executed*\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"📌 Ticker: `{t}`\n"
                f"📊 Side: *{side}*\n"
                f"📦 Quantity: `{qty}`\n"
                f"💰 Price: `${price:,.4f}`\n"
                f"📋 Status: {status}\n"
                f"🕐 {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"
            )

            if hasattr(order_result, 'broker_name') and order_result.broker_name:
                msg += f"\n🏦 Broker: {order_result.broker_name}"

            self._send_telegram(msg)

        except Exception as e:
            logger.warning(f"[Notifier] send_trade_alert failed: {e}")

    def send_rejection_alert(self, decision, risk_verdict) -> None:
        """Send alert for a rejected trade.

        Args:
            decision: TradeDecision that was rejected
            risk_verdict: RiskVerdict with rejection details
        """
        if not self.enabled or not self.alert_on_rejection:
            return

        try:
            action = getattr(decision.action, 'value', str(decision.action))
            msg = (
                f"⛔ *Trade Rejected*\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"📌 Ticker: `{decision.ticker}`\n"
                f"📊 Action: *{action}*\n"
                f"🎯 Confidence: `{decision.confidence_score:.0%}`\n"
                f"⚠️ Reason: _{risk_verdict.rejection_reason}_\n"
                f"📈 Risk Score: `{risk_verdict.risk_score:.2f}`\n"
                f"🕐 {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"
            )
            self._send_telegram(msg)

        except Exception as e:
            logger.warning(f"[Notifier] send_rejection_alert failed: {e}")

    def send_stop_loss_alert(
        self, ticker: str, exit_price: float, loss_amount: float, reason: str = ""
    ) -> None:
        """Send alert when a stop-loss is triggered.

        Args:
            ticker: Ticker symbol
            exit_price: Price at which position was closed
            loss_amount: Dollar amount of loss
            reason: Exit reason (trailing_stop, atr_stop, etc.)
        """
        if not self.enabled or not self.alert_on_stop_loss:
            return

        try:
            msg = (
                f"🛑 *Stop-Loss Triggered*\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"📌 Ticker: `{ticker}`\n"
                f"💸 Exit Price: `${exit_price:,.4f}`\n"
                f"📉 Loss: `${abs(loss_amount):,.2f}`\n"
                f"📋 Reason: _{reason}_\n"
                f"🕐 {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"
            )
            self._send_telegram(msg)

        except Exception as e:
            logger.warning(f"[Notifier] send_stop_loss_alert failed: {e}")

    def send_kill_switch_alert(self, reason: str, total_loss: float = 0) -> None:
        """Send alert when kill switch is activated.

        Args:
            reason: Why the kill switch was activated
            total_loss: Total loss amount
        """
        if not self.enabled or not self.alert_on_kill_switch:
            return

        try:
            msg = (
                f"🚨🚨 *KILL SWITCH ACTIVATED* 🚨🚨\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"⚠️ Reason: _{reason}_\n"
                f"📉 Total Loss: `${abs(total_loss):,.2f}`\n"
                f"🔒 All trading halted until next trading day\n"
                f"🕐 {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"
            )
            self._send_telegram(msg)

        except Exception as e:
            logger.warning(f"[Notifier] send_kill_switch_alert failed: {e}")

    def send_daily_summary(self, report: dict) -> None:
        """Send daily performance summary.

        Args:
            report: Performance report dict from TradeJournal
        """
        if not self.enabled or not self.daily_summary_enabled:
            return

        try:
            total = report.get("total_trades", 0)
            win_rate = report.get("win_rate", 0)
            pnl = report.get("avg_pnl", 0) * total
            best = report.get("best_trade", 0)
            worst = report.get("worst_trade", 0)
            sharpe = report.get("sharpe_ratio", 0)
            pf = report.get("profit_factor", 0)

            pnl_emoji = "📈" if pnl >= 0 else "📉"

            msg = (
                f"📊 *Daily Trading Summary*\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"📅 Date: {datetime.utcnow().strftime('%Y-%m-%d')}\n"
                f"🔢 Total Trades: `{total}`\n"
                f"🎯 Win Rate: `{win_rate:.0%}`\n"
                f"{pnl_emoji} Net P&L: `${pnl:,.2f}`\n"
                f"✅ Best Trade: `${best:,.2f}`\n"
                f"❌ Worst Trade: `${worst:,.2f}`\n"
                f"📐 Sharpe: `{sharpe:.2f}`\n"
                f"⚖️ Profit Factor: `{pf:.2f}`"
            )
            self._send_telegram(msg)

        except Exception as e:
            logger.warning(f"[Notifier] send_daily_summary failed: {e}")

    def send_custom(self, title: str, message: str) -> None:
        """Send a custom notification.

        Args:
            title: Alert title
            message: Alert message body
        """
        if not self.enabled:
            return

        try:
            msg = f"📢 *{title}*\n━━━━━━━━━━━━━━━━\n{message}"
            self._send_telegram(msg)
        except Exception as e:
            logger.warning(f"[Notifier] send_custom failed: {e}")

    def send_position_alert(self, ticker: str, alert_type: str, details: str) -> None:
        """Send a position-related alert.

        Args:
            ticker: Ticker symbol
            alert_type: e.g., "trailing_stop_update", "max_hold_warning"
            details: Human-readable details
        """
        if not self.enabled:
            return

        try:
            msg = (
                f"📍 *Position Alert: {ticker}*\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"🏷️ Type: _{alert_type}_\n"
                f"📝 {details}\n"
                f"🕐 {datetime.utcnow().strftime('%H:%M UTC')}"
            )
            self._send_telegram(msg)
        except Exception as e:
            logger.warning(f"[Notifier] send_position_alert failed: {e}")

    # ── Telegram API ──────────────────────────────────────────────────

    def _send_telegram(self, message: str) -> bool:
        """Send a message via Telegram Bot API.

        Uses urllib (built-in) to avoid external HTTP dependencies.
        Supports MarkdownV2 formatting.

        Args:
            message: Message text with Markdown formatting

        Returns:
            True if sent successfully
        """
        if not self.bot_token or not self.chat_id:
            return False

        # Rate limiting
        if not self._check_rate_limit():
            logger.warning("[Notifier] Rate limit exceeded, message dropped")
            return False

        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"

            payload = json.dumps({
                "chat_id": self.chat_id,
                "text": message,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
            }).encode("utf-8")

            req = Request(url, data=payload, method="POST")
            req.add_header("Content-Type", "application/json")

            with urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                if result.get("ok"):
                    return True
                else:
                    logger.warning(f"[Notifier] Telegram API error: {result}")
                    return False

        except URLError as e:
            logger.warning(f"[Notifier] Telegram send failed: {e}")
            return False
        except Exception as e:
            logger.warning(f"[Notifier] Telegram unexpected error: {e}")
            return False

    def _check_rate_limit(self) -> bool:
        """Check if we're within the rate limit."""
        with self._lock:
            now = time.time()
            # Remove entries older than 60 seconds
            self._send_times = [t for t in self._send_times if now - t < 60]
            if len(self._send_times) >= self._rate_limit:
                return False
            self._send_times.append(now)
            return True

    # ── Health ────────────────────────────────────────────────────────

    def test_connection(self) -> bool:
        """Send a test message to verify Telegram setup.

        Returns:
            True if test message was sent successfully
        """
        return self._send_telegram(
            "🤖 *TradingAgents Connected*\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"✅ Notifications are working!\n"
            f"🕐 {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"
        )
