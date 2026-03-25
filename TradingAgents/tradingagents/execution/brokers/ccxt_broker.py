"""CCXT broker for cryptocurrency exchange integration.

Supports 100+ exchanges including Binance, Bybit, OKX, Coinbase, etc.
Handles partial fills with remaining_quantity and average_fill_price tracking.
Requires the `ccxt` package: pip install ccxt

Usage:
    broker = CcxtBroker(
        exchange_id="binance",
        api_key="your_api_key",
        api_secret="your_secret",
        sandbox=True,  # Use testnet
    )
"""

import logging
import threading
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Tuple

logger = logging.getLogger(__name__)

try:
    import ccxt
except ImportError:
    raise ImportError(
        "CCXT is required for crypto broker. Install it: pip install ccxt"
    )

from tradingagents.execution.order_models import (
    OrderSide,
    OrderType,
    OrderStatus,
    OrderResult,
    PositionInfo,
)
from .broker_base import BaseBroker
from tradingagents.execution.retry import RetryConfig, with_retry


# Map our OrderType to CCXT order types
_ORDER_TYPE_MAP = {
    OrderType.MARKET: "market",
    OrderType.LIMIT: "limit",
    OrderType.STOP: "stop",
    OrderType.STOP_LIMIT: "stopLimit",
}

# Map CCXT statuses to our OrderStatus
_STATUS_MAP = {
    "open": OrderStatus.SUBMITTED,
    "closed": OrderStatus.FILLED,
    "canceled": OrderStatus.CANCELLED,
    "cancelled": OrderStatus.CANCELLED,
    "expired": OrderStatus.EXPIRED,
    "rejected": OrderStatus.REJECTED,
}


class CcxtBroker(BaseBroker):
    """Broker implementation using CCXT for cryptocurrency exchanges.

    Supports spot and futures trading across 100+ exchanges. Configure with
    exchange_id and API credentials. Use sandbox=True for testnet.

    Properly tracks partial fills: when an order is only partially
    filled, OrderResult.remaining_quantity shows how much is left.
    """

    def __init__(
        self,
        exchange_id: str = "binance",
        api_key: str = "",
        api_secret: str = "",
        password: str = "",  # Some exchanges require a passphrase
        sandbox: bool = True,
        default_quote_currency: str = "USDT",
        market_type: str = "spot",  # "spot" or "future"
        name: str = "ccxt",
        extra_config: Optional[dict] = None,
        retry_config: Optional[RetryConfig] = None,
        db: Optional["Database"] = None,
    ):
        """Initialize CCXT broker.

        Args:
            exchange_id: CCXT exchange ID (binance, bybit, okx, coinbase, etc.)
            api_key: API key from the exchange
            api_secret: API secret from the exchange
            password: API passphrase (required by some exchanges like OKX)
            sandbox: Use testnet/sandbox mode (recommended for testing)
            default_quote_currency: Default quote currency for pairs (USDT, USD, BTC)
            name: Broker identifier
            extra_config: Additional CCXT exchange config options
            retry_config: Retry settings for transient network errors
            db: Database instance for persisting entry prices across restarts
        """
        super().__init__(name=f"ccxt_{exchange_id}")
        self.exchange_id = exchange_id
        self.default_quote = default_quote_currency

        # Initialize CCXT exchange
        exchange_class = getattr(ccxt, exchange_id, None)
        if exchange_class is None:
            raise ValueError(
                f"Exchange '{exchange_id}' not supported by CCXT. "
                f"Available: {', '.join(ccxt.exchanges[:10])}..."
            )

        config = {
            "apiKey": api_key,
            "secret": api_secret,
            "enableRateLimit": True,
            "options": {"defaultType": market_type},
        }
        if password:
            config["password"] = password
        if extra_config:
            config.update(extra_config)

        self.exchange: ccxt.Exchange = exchange_class(config)

        # Enable sandbox/testnet mode
        if sandbox:
            self.exchange.set_sandbox_mode(True)
            logger.info("%s SANDBOX mode enabled", exchange_id)

        self._entry_price_cache: Dict[str, Tuple[float, float]] = {}
        self._cache_lock = threading.Lock()
        self._retry_config = retry_config or RetryConfig()
        self._db = db
        self.market_type = market_type  # "spot" or "future"

        # Load persisted entry prices from DB (survive restarts)
        if self._db is not None:
            try:
                persisted = self._db.load_entry_prices()
                if persisted:
                    self._entry_price_cache.update(persisted)
                    logger.info("Loaded %d cached entry prices from DB", len(persisted))
            except Exception as e:
                logger.warning("Failed to load entry prices from DB: %s", e)

        logger.info("Connected to %s (%s, %s)", exchange_id, 'sandbox' if sandbox else 'LIVE', market_type)

    def _normalize_ticker(self, ticker: str) -> str:
        """Normalize ticker to CCXT format (e.g., 'BTC' -> 'BTC/USDT')."""
        if "/" in ticker:
            return ticker
        return f"{ticker}/{self.default_quote}"

    @staticmethod
    def _determine_fill_status(
        filled: float, requested: float
    ) -> OrderStatus:
        """Determine order status based on fill amounts.

        Handles partial fills properly instead of just mapping CCXT statuses.
        """
        if filled <= 0:
            return OrderStatus.SUBMITTED
        elif filled >= requested:
            return OrderStatus.FILLED
        else:
            return OrderStatus.PARTIALLY_FILLED

    def place_order(
        self,
        ticker: str,
        side: OrderSide,
        quantity: float,
        order_type: OrderType = OrderType.MARKET,
        limit_price: Optional[float] = None,
        stop_price: Optional[float] = None,
        position_side: Optional[str] = None,
    ) -> OrderResult:
        """Place an order on the exchange via CCXT.

        Handles partial fills: if the exchange returns a partially filled order,
        the result will have status=PARTIALLY_FILLED, remaining_quantity populated,
        and average_fill_price set separately from filled_price.

        Args:
            position_side: For futures hedge mode: "LONG" or "SHORT"
        """
        symbol = self._normalize_ticker(ticker)
        ccxt_side = side.value.lower()  # "buy" or "sell"
        ccxt_type = _ORDER_TYPE_MAP.get(order_type, "market")

        try:
            params = {}
            if stop_price is not None:
                params["stopPrice"] = stop_price
            # Futures hedge mode: include positionSide
            if self.market_type == "future" and position_side:
                params["positionSide"] = position_side

            order = self.exchange.create_order(
                symbol=symbol,
                type=ccxt_type,
                side=ccxt_side,
                amount=quantity,
                price=limit_price,
                params=params,
            )

            filled = order.get("filled", 0.0) or 0.0
            remaining = order.get("remaining", quantity - filled)
            if remaining is None:
                remaining = max(0.0, quantity - filled)
            avg_price = order.get("average") or order.get("price")

            # Use our own fill-based status detection (more reliable than exchange strings)
            ccxt_status = order.get("status", "")
            if ccxt_status in ("canceled", "cancelled", "expired", "rejected"):
                status = _STATUS_MAP.get(ccxt_status, OrderStatus.REJECTED)
            else:
                status = self._determine_fill_status(filled, quantity)

            # Cache entry price on fill for accurate PnL in get_positions()
            if status in (OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED):
                if avg_price and avg_price > 0 and filled > 0:
                    self._update_entry_cache(symbol, avg_price, filled, side)

            return OrderResult(
                order_id=str(order["id"]),
                ticker=symbol,
                side=side,
                order_type=order_type,
                status=status,
                requested_quantity=quantity,
                filled_quantity=filled,
                remaining_quantity=remaining,
                requested_price=limit_price,
                filled_price=avg_price,
                average_fill_price=avg_price,
                commission=order.get("fee", {}).get("cost", 0.0) or 0.0,
                broker_name=self.name,
                raw_response=order,
            )

        except ccxt.InsufficientFunds as e:
            return OrderResult(
                order_id=f"failed_{uuid.uuid4().hex[:8]}",
                ticker=symbol,
                side=side,
                order_type=order_type,
                status=OrderStatus.REJECTED,
                requested_quantity=quantity,
                requested_price=limit_price,
                error_message=f"Insufficient funds: {str(e)}",
                broker_name=self.name,
            )

        except ccxt.ExchangeError as e:
            return OrderResult(
                order_id=f"failed_{uuid.uuid4().hex[:8]}",
                ticker=symbol,
                side=side,
                order_type=order_type,
                status=OrderStatus.REJECTED,
                requested_quantity=quantity,
                requested_price=limit_price,
                error_message=f"Exchange error: {str(e)}",
                broker_name=self.name,
            )

        except Exception as e:
            return OrderResult(
                order_id=f"failed_{uuid.uuid4().hex[:8]}",
                ticker=symbol,
                side=side,
                order_type=order_type,
                status=OrderStatus.REJECTED,
                requested_quantity=quantity,
                error_message=f"Unexpected error: {str(e)}",
                broker_name=self.name,
            )

    def cancel_order(self, order_id: str, symbol: Optional[str] = None) -> bool:
        """Cancel a pending order on the exchange.

        Args:
            order_id: The exchange's order ID.
            symbol: Trading pair symbol (e.g. 'BTC/USDT'). Many exchanges
                     (Bybit, OKX, Binance Futures) require this parameter;
                     without it cancel_order will raise ArgumentsRequired.
                     Pass None only when the exchange can resolve by ID alone.

        Returns:
            True if cancellation was successful, False otherwise.
        """
        try:
            import ccxt as ccxt_lib
        except ImportError:
            logger.error("ccxt not installed, cannot cancel order")
            return False

        try:
            if symbol is not None:
                self.exchange.cancel_order(order_id, symbol)
            else:
                self.exchange.cancel_order(order_id)
            return True

        except ccxt_lib.ArgumentsRequired as e:
            # Exchange requires symbol but caller didn't provide it
            logger.warning(
                "cancel_order(%s) requires 'symbol' parameter on this exchange. "
                "Pass symbol to cancel_order() for reliable cancellation.",
                order_id,
            )
            return False

        except ccxt_lib.ExchangeError as e:
            logger.error("Cancel exchange error for %s: %s", order_id, e)
            return False

        except Exception as e:
            logger.error("Cancel failed for %s: %s", order_id, e)
            return False

    def get_order_status(self, order_id: str) -> OrderResult:
        """Fetch current status of an order from the exchange."""
        try:
            order = with_retry(
                lambda: self.exchange.fetch_order(order_id),
                config=self._retry_config,
                operation_name=f"fetch_order({order_id})",
            )

            filled = order.get("filled", 0) or 0
            requested = order.get("amount", 0) or 0
            remaining = order.get("remaining", max(0, requested - filled))
            if remaining is None:
                remaining = max(0, requested - filled)
            avg_price = order.get("average") or order.get("price")

            ccxt_status = order.get("status", "")
            if ccxt_status in ("canceled", "cancelled", "expired", "rejected"):
                status = _STATUS_MAP.get(ccxt_status, OrderStatus.REJECTED)
            else:
                status = self._determine_fill_status(filled, requested)

            return OrderResult(
                order_id=str(order["id"]),
                ticker=order.get("symbol", ""),
                side=OrderSide.BUY if order.get("side") == "buy" else OrderSide.SELL,
                status=status,
                requested_quantity=requested,
                filled_quantity=filled,
                remaining_quantity=remaining,
                filled_price=avg_price,
                average_fill_price=avg_price,
                commission=order.get("fee", {}).get("cost", 0) or 0,
                broker_name=self.name,
                raw_response=order,
            )
        except Exception as e:
            return OrderResult(
                order_id=order_id,
                ticker="UNKNOWN",
                side=OrderSide.BUY,
                status=OrderStatus.REJECTED,
                requested_quantity=0,
                error_message=f"Failed to fetch order: {str(e)}",
                broker_name=self.name,
            )

    def get_balance(self) -> Dict[str, float]:
        """Fetch account balance from the exchange (with retry)."""
        try:
            balance = with_retry(
                lambda: self.exchange.fetch_balance(),
                config=self._retry_config,
                operation_name="fetch_balance",
            )
            free = balance.get("free", {})
            total = balance.get("total", {})

            # Get total in quote currency
            quote_free = free.get(self.default_quote, 0.0) or 0.0
            quote_total = total.get(self.default_quote, 0.0) or 0.0

            return {
                "cash": quote_free,
                "total_equity": quote_total,
                "buying_power": quote_free,
                "balances": {k: v for k, v in total.items() if v and v > 0},
            }
        except Exception as e:
            logger.error("Balance fetch failed: %s", e)
            return {"cash": 0.0, "total_equity": 0.0, "buying_power": 0.0}

    def get_positions(self) -> List[PositionInfo]:
        """Get open positions (derived from non-zero balances).

        Entry price resolution priority:
        1. Local fill cache (_entry_price_cache) — most accurate
        2. Exchange-provided entryPrice (Binance Futures, etc.)
        3. Current market price — fallback (PnL will be ≈ 0)
        """
        positions = []
        try:
            balance = with_retry(
                lambda: self.exchange.fetch_balance(),
                config=self._retry_config,
                operation_name="get_positions.fetch_balance",
            )
            total = balance.get("total", {})

            for currency, amount in total.items():
                if not amount or amount <= 0 or currency == self.default_quote:
                    continue

                # Get current price
                symbol = f"{currency}/{self.default_quote}"
                try:
                    ticker_data = with_retry(
                        lambda s=symbol: self.exchange.fetch_ticker(s),
                        config=self._retry_config,
                        operation_name=f"fetch_ticker({symbol})",
                    )
                    current_price = ticker_data.get("last", 0)
                except Exception:
                    continue

                if not current_price or current_price <= 0:
                    continue

                # Resolve entry price with priority chain
                entry_price = self._resolve_entry_price(
                    symbol, ticker_data, current_price
                )

                positions.append(
                    PositionInfo(
                        ticker=symbol,
                        side=OrderSide.BUY,
                        quantity=amount,
                        entry_price=entry_price,
                        current_price=current_price,
                        entry_timestamp=datetime.utcnow(),
                    )
                )
        except Exception as e:
            logger.error("Position fetch failed: %s", e)

        return positions

    # ── Futures-Specific Methods ─────────────────────────────────────

    def set_leverage(self, symbol: str, leverage: int) -> bool:
        """Set leverage for a futures symbol.

        Only effective when market_type is 'future'.
        Returns True on success, False if skipped or failed.
        """
        if self.market_type != "future":
            logger.debug("set_leverage skipped: market_type is '%s'", self.market_type)
            return False
        normalized = self._normalize_ticker(symbol)
        try:
            self.exchange.set_leverage(leverage, normalized)
            logger.info("[CcxtBroker] Set leverage %dx for %s", leverage, normalized)
            return True
        except Exception as e:
            logger.warning("[CcxtBroker] set_leverage failed for %s: %s", normalized, e)
            return False

    def set_margin_mode(self, symbol: str, margin_type: str = "isolated") -> bool:
        """Set margin mode (isolated/cross) for a futures symbol.

        Only effective when market_type is 'future'.
        Returns True on success, False if skipped or failed.
        """
        if self.market_type != "future":
            logger.debug("set_margin_mode skipped: market_type is '%s'", self.market_type)
            return False
        normalized = self._normalize_ticker(symbol)
        try:
            self.exchange.set_margin_mode(margin_type, normalized)
            logger.info("[CcxtBroker] Set margin mode '%s' for %s", margin_type, normalized)
            return True
        except Exception as e:
            # Many exchanges return error if mode is already set
            if "already" in str(e).lower() or "no need" in str(e).lower():
                logger.debug("Margin mode '%s' already set for %s", margin_type, normalized)
                return True
            logger.warning("[CcxtBroker] set_margin_mode failed for %s: %s", normalized, e)
            return False

    def get_futures_positions(self) -> List["PositionInfo"]:
        """Fetch open futures positions using CCXT fetch_positions().

        Only works when market_type is 'future'.
        Returns PositionInfo objects with leverage, liquidation_price, etc.
        """
        if self.market_type != "future":
            return self.get_positions()

        from tradingagents.execution.order_models import PositionSide, MarginType

        positions = []
        try:
            raw_positions = with_retry(
                lambda: self.exchange.fetch_positions(),
                config=self._retry_config,
                operation_name="fetch_positions",
            )
            for pos in raw_positions:
                contracts = float(pos.get("contracts", 0) or 0)
                if contracts <= 0:
                    continue

                entry_price = float(pos.get("entryPrice", 0) or 0)
                current_price = float(pos.get("markPrice", 0) or pos.get("lastPrice", 0) or 0)
                liq_price = pos.get("liquidationPrice")
                leverage_val = int(pos.get("leverage", 1) or 1)
                pos_side_str = (pos.get("side", "long") or "long").upper()
                margin_mode = (pos.get("marginMode", "isolated") or "isolated").lower()

                side = OrderSide.BUY if pos_side_str in ("LONG", "BUY") else OrderSide.SELL
                p_side = PositionSide.LONG if pos_side_str in ("LONG", "BUY") else PositionSide.SHORT
                m_type = MarginType.CROSS if margin_mode == "cross" else MarginType.ISOLATED

                positions.append(
                    PositionInfo(
                        ticker=pos.get("symbol", ""),
                        side=side,
                        quantity=contracts,
                        entry_price=entry_price if entry_price > 0 else current_price,
                        current_price=current_price if current_price > 0 else entry_price,
                        entry_timestamp=datetime.utcnow(),
                        position_side=p_side,
                        leverage=leverage_val,
                        liquidation_price=float(liq_price) if liq_price else None,
                        margin_type=m_type,
                    )
                )
        except Exception as e:
            logger.error("Futures position fetch failed: %s", e)

        return positions

    def _resolve_entry_price(
        self, symbol: str, ticker_data: dict, current_price: float
    ) -> float:
        """Resolve the best available entry price for a position.

        Priority:
        1. Local fill cache (from place_order)
        2. Exchange-provided entryPrice field
        3. Current market price (fallback)
        """
        # Priority 1: local cache from our own fills
        with self._cache_lock:
            cached = self._entry_price_cache.get(symbol)
        if cached is not None:
            return cached[0]  # weighted avg price

        # Priority 2: exchange-provided entry price (Binance Futures, etc.)
        info = ticker_data.get("info", {})
        if isinstance(info, dict):
            exchange_entry = info.get("entryPrice")
            if exchange_entry is not None:
                try:
                    ep = float(exchange_entry)
                    if ep > 0:
                        return ep
                except (ValueError, TypeError):
                    pass

        # Priority 3: fallback
        return current_price

    def _update_entry_cache(
        self,
        symbol: str,
        fill_price: float,
        fill_qty: float,
        side: "OrderSide",
    ) -> None:
        """Update the entry price cache with a new fill.

        For BUY fills, computes a weighted average if a cached entry exists.
        For SELL fills, removes the cache entry when fully closed.
        Write-through to DB if available.
        """
        with self._cache_lock:
            if side == OrderSide.SELL:
                # Reduce cached quantity; remove if fully sold
                existing = self._entry_price_cache.get(symbol)
                if existing:
                    old_price, old_qty = existing
                    remaining = old_qty - fill_qty
                    if remaining <= 0:
                        self._entry_price_cache.pop(symbol, None)
                        self._db_delete_entry(symbol)
                    else:
                        self._entry_price_cache[symbol] = (old_price, remaining)
                        self._db_upsert_entry(symbol, old_price, remaining)
                return

            # BUY: weighted average
            existing = self._entry_price_cache.get(symbol)
            if existing:
                old_price, old_qty = existing
                total_qty = old_qty + fill_qty
                weighted_avg = (
                    (old_price * old_qty) + (fill_price * fill_qty)
                ) / total_qty
                self._entry_price_cache[symbol] = (weighted_avg, total_qty)
                self._db_upsert_entry(symbol, weighted_avg, total_qty)
            else:
                self._entry_price_cache[symbol] = (fill_price, fill_qty)
                self._db_upsert_entry(symbol, fill_price, fill_qty)

    def clear_entry_cache(self, symbol: Optional[str] = None) -> None:
        """Clear the entry price cache (memory + DB).

        Args:
            symbol: If provided, clear only this symbol's cached entry.
                    If None, clear the entire cache.
        """
        with self._cache_lock:
            if symbol is not None:
                self._entry_price_cache.pop(symbol, None)
                self._db_delete_entry(symbol)
            else:
                self._entry_price_cache.clear()
                self._db_delete_entry(None)

    # ── DB helpers (fire-and-forget, errors are logged not raised) ────

    def _db_upsert_entry(self, symbol: str, avg_price: float, qty: float) -> None:
        if self._db is not None:
            try:
                self._db.upsert_entry_price(symbol, avg_price, qty)
            except Exception as e:
                logger.error("DB upsert_entry_price failed: %s", e)

    def _db_delete_entry(self, symbol: Optional[str]) -> None:
        if self._db is not None:
            try:
                self._db.delete_entry_price(symbol)
            except Exception as e:
                logger.error("DB delete_entry_price failed: %s", e)

    def get_current_price(self, ticker: str) -> Optional[float]:
        """Fetch current price from the exchange (with retry)."""
        symbol = self._normalize_ticker(ticker)
        try:
            tick = with_retry(
                lambda: self.exchange.fetch_ticker(symbol),
                config=self._retry_config,
                operation_name=f"fetch_ticker({symbol})",
            )
            return tick.get("last")
        except Exception as e:
            logger.error("Price fetch failed for %s: %s", symbol, e)
            return None

    def get_supported_exchanges(self) -> List[str]:
        """List all CCXT-supported exchange IDs."""
        return ccxt.exchanges
