"""Celery tasks for background processing.

Primary task: run_analysis_task — executes LLM agent analysis
and persists results to the TaskResult DB table.
"""

import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger("api.tasks")


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

            # Get or create graph
            graph = init_graph()
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

            # Sync graph state to user's portfolio
            try:
                from api.db_sync import save_graph_to_db
                save_graph_to_db(graph, user_id=user_id)
            except Exception as sync_e:
                logger.error("Failed to sync to DB for user %d: %s", user_id, sync_e)

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
