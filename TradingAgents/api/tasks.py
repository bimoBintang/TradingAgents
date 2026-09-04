"""Celery tasks for background processing.

Primary task: run_analysis_task — executes LLM agent analysis
and persists results to the TaskResult DB table.
"""

import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger("api.tasks")


def _persist_pending_orders(db, user_id: int, task_id: str, graph, user_config: dict) -> int:
    """Write orders the engine queued for approval into the database.

    Scoped to `user_id` and given an explicit expiry, so the approval
    endpoint can find them after this graph is gone and can refuse ones
    that have gone stale.
    """
    from datetime import timedelta
    from api.models import PendingOrder

    engine = getattr(graph, "execution_engine", None)
    if engine is None:
        return 0

    ttl = int(user_config.get("execution", {}).get("pending_order_ttl_seconds", 900))
    now = datetime.now(timezone.utc)
    written = 0

    for pending in engine.get_pending_orders():
        key = pending.get("idempotency_key")
        if not key:
            continue
        # Idempotency keys are unique; never write the same order twice.
        if db.query(PendingOrder).filter(PendingOrder.idempotency_key == key).first():
            continue

        db.add(PendingOrder(
            user_id=user_id,
            task_id=task_id,
            ticker=pending.get("ticker", ""),
            action=str(pending.get("action", "")),
            quantity=float(pending.get("quantity", 0) or 0),
            price=float(pending.get("price", 0) or 0),
            value=float(pending.get("value", 0) or 0),
            confidence=float(pending.get("confidence", 0) or 0),
            stop_loss_pct=pending.get("stop_loss_pct"),
            take_profit_pct=pending.get("take_profit_pct"),
            order_type=str(pending.get("order_type", "MARKET")),
            time_horizon=pending.get("time_horizon"),
            risk_score=pending.get("risk_reward_ratio"),
            reasoning=(pending.get("reasoning") or "")[:1000],
            key_factors=json.dumps(pending.get("key_factors") or []),
            decision_json=pending.get("decision_json") or "",
            idempotency_key=key,
            status="PENDING",
            created_at=now,
            expires_at=now + timedelta(seconds=ttl),
        ))
        written += 1

    if written:
        db.commit()
        logger.info("Persisted %d pending order(s) for user %d", written, user_id)
    return written


def _do_analysis(task_id: str, user_id: int, ticker: str, trade_date: str, auto_execute: bool):
    """Core analysis logic — shared by Celery task and thread fallback.

    Updates TaskResult in the database with status and results.
    """
    from api.database import SessionLocal
    from api.models import TaskResult

    with SessionLocal() as db:
        # Mark as running
        task_row = db.query(TaskResult).filter(TaskResult.task_id == task_id).first()
        if task_row:
            task_row.status = "running"
            db.commit()

        try:
            from api.dependencies import init_graph
            from tradingagents.graph.trading_graph import TradingAgentsGraph
            from api.user_context import get_user_config

            # ── Multi-tenant: load user-specific config ──
            user_config = get_user_config(db, user_id)

            # Get or create graph with user-specific config
            graph = init_graph(config=user_config)
            if graph is None:
                raise RuntimeError("TradingAgentsGraph not available")

            final_state, decision, order_result = graph.propagate(
                ticker, trade_date, auto_execute=auto_execute
            )

            # Serialize order result
            order_dict = None
            if order_result:
                order_dict = {
                    "order_id": order_result.order_id,
                    "ticker": order_result.ticker,
                    "side": order_result.side.value if hasattr(order_result.side, "value") else str(order_result.side),
                    "filled_quantity": order_result.filled_quantity,
                    "filled_price": order_result.filled_price,
                    "status": order_result.status.value if hasattr(order_result.status, "value") else str(order_result.status),
                    "broker_name": getattr(order_result, "broker_name", None),
                }

            reports = {
                "market_report": final_state.get("market_report"),
                "quant_report": final_state.get("quant_report"),
                "onchain_report": final_state.get("onchain_report"),
                "macro_geo_report": final_state.get("macro_geo_report"),
                "correlation_report": final_state.get("correlation_report"),
                "execution_strategy": final_state.get("execution_strategy"),
            }

            result_payload = {
                "decision": decision,
                "order_result": order_dict,
                "reports": reports,
            }

            # Save to DB
            if task_row:
                task_row.status = "completed"
                task_row.result_json = json.dumps(result_payload, default=str)
                task_row.updated_at = datetime.now(timezone.utc)
                db.commit()

            # Persist any order the engine queued for manual approval.
            #
            # The engine holds pending orders in memory, but this analysis
            # runs on a per-user TradingAgentsGraph that is discarded the
            # moment this function returns — so without this write the
            # order simply vanished, and since require_confirmation
            # defaults to True that meant NO trade could ever be executed.
            # Persisting here also scopes the order to its user, which the
            # in-memory queue on a shared singleton never did.
            try:
                _persist_pending_orders(db, user_id, task_id, graph, user_config)
            except Exception as pend_e:
                logger.error("Failed to persist pending orders for user %d: %s", user_id, pend_e)

            # Record this decision alongside what each baseline would have
            # called at the same instant and price — the only lookahead-free
            # way to find out whether this agent stack is worth its cost.
            # See api/services/forward_benchmark.py. Never allowed to break
            # the analysis: measurement must not take down the thing it measures.
            try:
                from api.routers.analysis import _parse_decision
                from api.services.forward_benchmark import record_decision_set

                parsed = _parse_decision(decision)
                if parsed is not None:
                    record_decision_set(
                        db, user_id, ticker,
                        agent_action=parsed.action,
                        agent_confidence=parsed.confidence_score,
                    )
            except Exception as bench_e:
                logger.error("Forward benchmark record failed for user %d: %s", user_id, bench_e)

            # Sync graph state to user's portfolio
            try:
                from api.db_sync import save_graph_to_db
                save_graph_to_db(graph, user_id=user_id)
            except Exception as sync_e:
                logger.error("Failed to sync to DB for user %d: %s", user_id, sync_e)

            # If this was a live (non-paper) fill, pull the REAL post-trade
            # balance immediately rather than waiting up to
            # balance_sync_interval_seconds for the next scheduled tick —
            # see api/services/balance_sync.py.
            if order_result is not None:
                try:
                    from api.services.balance_sync import sync_user_balance
                    sync_user_balance(user_id, db=db)
                except Exception as sync_e:
                    logger.error("Post-fill balance sync failed for user %d: %s", user_id, sync_e)

        except Exception as e:
            logger.error("Analysis task %s failed: %s", task_id, e)
            if task_row:
                task_row.status = "failed"
                task_row.error = f"{type(e).__name__}: {e}"
                task_row.updated_at = datetime.now(timezone.utc)
                db.commit()


# ── Celery task (only registered if Celery is available) ──────────────

try:
    from api.celery_app import celery_app, is_celery_available

    if celery_app and is_celery_available():
        @celery_app.task(
            bind=True,
            name="api.tasks.run_analysis_task",
            max_retries=2,
            default_retry_delay=30,
        )
        def run_analysis_task(self, task_id: str, user_id: int, ticker: str, trade_date: str, auto_execute: bool):
            """Celery task wrapper for analysis."""
            try:
                _do_analysis(task_id, user_id, ticker, trade_date, auto_execute)
            except Exception as exc:
                logger.warning("Task %s failed, retrying (%d/%d): %s", task_id, self.request.retries, self.max_retries, exc)
                raise self.retry(exc=exc)
except ImportError:
    pass


# ── Thread fallback ───────────────────────────────────────────────────

def run_analysis_thread(task_id: str, user_id: int, ticker: str, trade_date: str, auto_execute: bool):
    """Thread-based fallback when Celery is not available."""
    import threading
    thread = threading.Thread(
        target=_do_analysis,
        args=(task_id, user_id, ticker, trade_date, auto_execute),
        daemon=True,
    )
    thread.start()
