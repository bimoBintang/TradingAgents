"""Retry utility with exponential backoff for broker API calls.

Provides a reusable retry mechanism for transient network errors that
commonly occur with exchange APIs. Non-retryable errors (business logic
errors like InsufficientFunds) are raised immediately.

Usage:
    from tradingagents.execution.retry import RetryConfig, with_retry

    config = RetryConfig(max_retries=3, base_delay=1.0)
    result = with_retry(
        lambda: exchange.fetch_balance(),
        config=config,
        operation_name="fetch_balance",
    )
"""

import logging
import random
import time
from dataclasses import dataclass, field
from typing import Callable, TypeVar, Type, Tuple, Optional

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass(frozen=True)
class RetryConfig:
    """Configuration for retry behavior.

    Attributes:
        max_retries: Maximum number of retry attempts (0 = no retries).
        base_delay: Initial delay in seconds before the first retry.
        max_delay: Maximum delay cap in seconds.
        backoff_factor: Multiplier applied to delay after each attempt.
        jitter_range: Random jitter range (±%) to prevent thundering herd.
    """

    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 30.0
    backoff_factor: float = 2.0
    jitter_range: float = 0.2  # ±20%

    @classmethod
    def from_config(cls, exec_cfg: dict) -> "RetryConfig":
        """Create RetryConfig from an execution config dict."""
        return cls(
            max_retries=exec_cfg.get("retry_max_attempts", 3),
            base_delay=exec_cfg.get("retry_base_delay", 1.0),
            max_delay=exec_cfg.get("retry_max_delay", 30.0),
            backoff_factor=exec_cfg.get("retry_backoff_factor", 2.0),
        )


# Default CCXT exceptions that are safe to retry (transient/network errors)
_DEFAULT_RETRYABLE: Tuple[Type[BaseException], ...] = ()

try:
    import ccxt

    _DEFAULT_RETRYABLE = (
        ccxt.NetworkError,        # General network issues
        ccxt.RequestTimeout,      # Timeout
        ccxt.DDoSProtection,      # Rate limit hit
        ccxt.ExchangeNotAvailable,  # Exchange maintenance/down
    )
except ImportError:
    pass


def _calculate_delay(
    attempt: int, config: RetryConfig
) -> float:
    """Calculate delay with exponential backoff and jitter.

    Formula: min(base_delay * backoff_factor^attempt, max_delay) * jitter
    """
    delay = min(
        config.base_delay * (config.backoff_factor ** attempt),
        config.max_delay,
    )
    # Apply jitter: ±jitter_range
    jitter = 1.0 + random.uniform(-config.jitter_range, config.jitter_range)
    return delay * jitter


def with_retry(
    func: Callable[[], T],
    config: Optional[RetryConfig] = None,
    retryable_exceptions: Optional[Tuple[Type[BaseException], ...]] = None,
    operation_name: str = "operation",
) -> T:
    """Execute a function with exponential backoff retry on transient errors.

    Args:
        func: Zero-argument callable to execute (use lambda for args).
        config: Retry configuration. Uses defaults if None.
        retryable_exceptions: Tuple of exception types to retry on.
                              Uses _DEFAULT_RETRYABLE if None.
        operation_name: Human-readable name for logging.

    Returns:
        The return value of func().

    Raises:
        The last exception if all retries are exhausted, or any
        non-retryable exception immediately.
    """
    if config is None:
        config = RetryConfig()
    if retryable_exceptions is None:
        retryable_exceptions = _DEFAULT_RETRYABLE

    last_exception: Optional[BaseException] = None

    for attempt in range(config.max_retries + 1):
        try:
            return func()

        except retryable_exceptions as e:
            last_exception = e

            if attempt >= config.max_retries:
                logger.error(
                    "[Retry] %s failed after %d attempts: %s",
                    operation_name, attempt + 1, e,
                )
                raise

            delay = _calculate_delay(attempt, config)
            logger.warning(
                "[Retry] %s attempt %d/%d failed (%s: %s). "
                "Retrying in %.1fs...",
                operation_name,
                attempt + 1,
                config.max_retries + 1,
                type(e).__name__,
                e,
                delay,
            )
            time.sleep(delay)

    # Should not reach here, but safety net
    if last_exception:
        raise last_exception
    raise RuntimeError(f"Retry logic error in {operation_name}")
