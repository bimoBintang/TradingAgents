"""Autopilot: the autonomous analysis loop, driven entirely by the owner's DB config.

Single source of truth for dashboard, API job and MCP tools: all state lives in the
database (user_configs / task_results / trades / portfolio_state), none in process memory
except a lock that stops two ticks from overlapping.

The AI runs only while `scheduler.enabled` is true, and stops by itself when a goal in the
`autopilot` config block is met (profit target, loss limit, end time). Stopping means "no
new analyses": open positions keep their broker-side stops and the exit monitor.
"""

import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from sqlalchemy.orm import Session

from api.auth import get_or_create_owner
from api.database import SessionLocal
from api.models import PortfolioState, TaskResult, Trade
from api.user_context import get_user_config, save_user_config

logger = logging.getLogger("api.autopilot")

_tick_lock = threading.Lock()
_running_ticker: Optional[str] = None  # informational only; the DB is authoritative
_last_tick_at: Optional[datetime] = None
_last_error: Optional[str] = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return _aware(datetime.fromisoformat(str(value).replace("Z", "+00:00")))
    except ValueError:
        return None


# ── Goals ─────────────────────────────────────────────────────────────

def evaluate_goals(ap: Dict[str, Any], equity: float, now: Optional[datetime] = None) -> Optional[str]:
    """Return the reason to stop ('max_loss' | 'target_profit' | 'end_at') or None.

    Loss is checked first: if equity swung through both limits between two ticks, the safe
    reason wins.
    """
    now = now or _now()
    start = ap.get("start_equity")
    if start:
        change_pct = (equity - start) / start * 100.0
        max_loss = ap.get("max_loss_pct")
        if max_loss is not None and change_pct <= -abs(float(max_loss)):
            return "max_loss"
        target = ap.get("target_profit_pct")
        if target is not None and change_pct >= float(target):
            return "target_profit"
    end_at = _parse_iso(ap.get("end_at"))
    if end_at is not None and now >= end_at:
        return "end_at"
    return None


def _equity(db: Session, user_id: int) -> float:
    ps = db.query(PortfolioState).filter(PortfolioState.user_id == user_id).first()
    return float(ps.total_equity) if ps and ps.total_equity is not None else 0.0


# ── Commands (dashboard + MCP) ────────────────────────────────────────

def start(db: Session, target_profit_pct: Optional[float] = None, max_loss_pct: Optional[float] = None,
          end_at: Optional[str] = None) -> Dict[str, Any]:
    """Begin a run: record the baseline equity and goals, then enable the scheduler."""
    if end_at is not None and _parse_iso(end_at) is None:
        raise ValueError("end_at must be an ISO timestamp, e.g. 2026-12-01T00:00:00Z")
    for name, v in (("target_profit_pct", target_profit_pct), ("max_loss_pct", max_loss_pct)):
        if v is not None and float(v) <= 0:
            raise ValueError(f"{name} must be > 0")
    owner = get_or_create_owner(db)
    save_user_config(db, owner.id, {
        "scheduler": {"enabled": True},
        "autopilot": {
            "target_profit_pct": target_profit_pct, "max_loss_pct": max_loss_pct, "end_at": end_at,
            "started_at": _now().isoformat(), "start_equity": _equity(db, owner.id),
            "stopped_reason": None, "stopped_at": None,
        },
    })
    return status(db)


def pause(db: Session) -> Dict[str, Any]:
    owner = get_or_create_owner(db)
    save_user_config(db, owner.id, {"scheduler": {"enabled": False}})
    return status(db)


def resume(db: Session) -> Dict[str, Any]:
    """Re-enable without touching the baseline. A run that already hit a goal must be restarted."""
    owner = get_or_create_owner(db)
    cfg = get_user_config(db, owner.id)
    if cfg["autopilot"].get("stopped_reason"):
        raise ValueError(
            f"The run ended ({cfg['autopilot']['stopped_reason']}). Start a new run with new goals."
        )
    save_user_config(db, owner.id, {"scheduler": {"enabled": True}})
    return status(db)


def set_watchlist(db: Session, tickers: List[str]) -> Dict[str, Any]:
    clean = [t.strip().upper() for t in tickers if t and t.strip()]
    if not clean:
        raise ValueError("watchlist must contain at least one ticker")
    owner = get_or_create_owner(db)
    save_user_config(db, owner.id, {"scheduler": {"watchlist": clean}})
    return status(db)


# ── Read side ─────────────────────────────────────────────────────────

def _last_task(db: Session, user_id: int, ticker: str) -> Optional[TaskResult]:
    return (
        db.query(TaskResult)
        .filter(TaskResult.user_id == user_id, TaskResult.ticker == ticker)
        .order_by(TaskResult.created_at.desc())
        .first()
    )


def _market_label(exec_cfg: Dict[str, Any]) -> str:
    broker = exec_cfg.get("broker")
    if exec_cfg.get("mode") == "paper" or broker == "paper":
        return "Paper"
    if broker == "mt5":
        return "Forex · MT5"
    if broker == "alpaca":
        return "Saham · Alpaca"
    kind = "Futures" if exec_cfg.get("market_type") == "future" else "Spot"
    return f"Kripto {kind} · {str(exec_cfg.get('exchange') or 'ccxt').capitalize()}"


def status(db: Session) -> Dict[str, Any]:
    from tradingagents.scheduler.scheduler import is_market_open

    owner = get_or_create_owner(db)
    cfg = get_user_config(db, owner.id)
    sched, ap, exec_cfg = cfg["scheduler"], cfg["autopilot"], cfg["execution"]
    now = _now()
    equity = _equity(db, owner.id)
    start_eq = ap.get("start_equity")
    change_pct = ((equity - start_eq) / start_eq * 100.0) if start_eq else None
    interval = timedelta(minutes=int(sched.get("interval_minutes", 60)))

    tickers = []
    for t in sched.get("watchlist", []):
        last = _last_task(db, owner.id, t)
        last_at = _aware(last.created_at) if last else None
        tickers.append({
            "ticker": t,
            "last_run_at": last_at.isoformat() if last_at else None,
            "last_status": last.status if last else None,
            "next_due_at": (last_at + interval).isoformat() if last_at else now.isoformat(),
            "market_open": is_market_open(t, sched),
        })

    running = db.query(TaskResult).filter(
        TaskResult.user_id == owner.id, TaskResult.status.in_(("queued", "running"))
    ).order_by(TaskResult.created_at.desc()).first()

    end_at = _parse_iso(ap.get("end_at"))
    return {
        "enabled": bool(sched.get("enabled")),
        "state": ("stopped" if ap.get("stopped_reason") else "running" if sched.get("enabled") else "paused"),
        "stopped_reason": ap.get("stopped_reason"),
        "stopped_at": ap.get("stopped_at"),
        "running_ticker": running.ticker if running else None,
        "last_tick_at": _last_tick_at.isoformat() if _last_tick_at else None,
        "last_error": _last_error,
        "interval_minutes": sched.get("interval_minutes"),
        "watchlist": sched.get("watchlist", []),
        "tickers": tickers,
        "market": _market_label(exec_cfg),
        "broker": exec_cfg.get("broker"),
        "exchange": exec_cfg.get("exchange"),
        "market_type": exec_cfg.get("market_type"),
        "mode": exec_cfg.get("mode"),
        "require_confirmation": bool(exec_cfg.get("require_confirmation", True)),
        "auto_execute": bool(sched.get("auto_execute", True)),
        "goals": {
            "target_profit_pct": ap.get("target_profit_pct"),
            "max_loss_pct": ap.get("max_loss_pct"),
            "end_at": ap.get("end_at"),
        },
        "progress": {
            "started_at": ap.get("started_at"),
            "start_equity": start_eq,
            "equity": equity,
            "change_pct": change_pct,
            "seconds_left": max(0, int((end_at - now).total_seconds())) if end_at else None,
        },
    }


def decisions(db: Session, limit: int = 20) -> List[Dict[str, Any]]:
    from api.routers.analysis import _parse_decision
    import json

    owner = get_or_create_owner(db)
    rows = (
        db.query(TaskResult).filter(TaskResult.user_id == owner.id)
        .order_by(TaskResult.created_at.desc()).limit(max(1, min(int(limit), 100))).all()
    )
    out = []
    for r in rows:
        item: Dict[str, Any] = {
            "task_id": r.task_id, "ticker": r.ticker, "status": r.status, "error": r.error,
            "created_at": _aware(r.created_at).isoformat() if r.created_at else None,
            "decision": None, "order_result": None,
        }
        if r.result_json:
            try:
                payload = json.loads(r.result_json)
                d = _parse_decision(payload.get("decision"))
                item["decision"] = d.model_dump() if d is not None else None
                item["order_result"] = payload.get("order_result")
            except (ValueError, TypeError):
                pass
        out.append(item)
    return out


# ── The loop ──────────────────────────────────────────────────────────

def _stop(db: Session, owner_id: int, reason: str, cfg: Dict[str, Any]) -> None:
    save_user_config(db, owner_id, {
        "scheduler": {"enabled": False},
        "autopilot": {"stopped_reason": reason, "stopped_at": _now().isoformat()},
    })
    logger.warning("Autopilot stopped: %s", reason)
    try:
        from tradingagents.notifications.notifier import Notifier
        n = Notifier(cfg)
        if n.enabled:
            n.send_custom("Autopilot stopped", f"Reason: {reason}. No new analyses; open positions keep their stops.")
    except Exception as e:  # a notification problem must never block stopping
        logger.error("Autopilot stop notification failed: %s", e)


def _expire_stale(db: Session, owner_id: int, timeout_seconds: int) -> None:
    """A task left queued/running by a crashed process would block the loop forever."""
    cutoff = _now() - timedelta(seconds=max(int(timeout_seconds) * 3, 1800))
    for t in db.query(TaskResult).filter(
        TaskResult.user_id == owner_id, TaskResult.status.in_(("queued", "running"))
    ).all():
        if _aware(t.updated_at or t.created_at) < cutoff:
            t.status, t.error = "failed", "Marked failed by autopilot: stale after restart/timeout."
    db.commit()


def _trades_today(db: Session, owner_id: int) -> int:
    ps = db.query(PortfolioState).filter(PortfolioState.user_id == owner_id).first()
    if ps is None:
        return 0
    start_of_day = _now().replace(hour=0, minute=0, second=0, microsecond=0)
    return db.query(Trade).filter(Trade.portfolio_id == ps.id, Trade.fill_time >= start_of_day).count()


def run_tick(now: Optional[datetime] = None) -> Dict[str, Any]:
    """One pass: check goals, then analyze each due ticker (sequentially). Safe to call often."""
    global _running_ticker, _last_tick_at, _last_error
    from tradingagents.scheduler.scheduler import is_market_open
    from api.tasks import _do_analysis

    if not _tick_lock.acquire(blocking=False):
        return {"skipped": "tick already running"}
    ran: List[str] = []
    try:
        now = now or _now()
        _last_tick_at = now
        with SessionLocal() as db:
            owner = get_or_create_owner(db)
            cfg = get_user_config(db, owner.id)
            sched, ap = cfg["scheduler"], cfg["autopilot"]
            if not sched.get("enabled"):
                return {"skipped": "disabled"}

            if not ap.get("start_equity"):  # enabled from AI Config without start(): set the baseline
                save_user_config(db, owner.id, {"autopilot": {
                    "start_equity": _equity(db, owner.id), "started_at": now.isoformat()}})
                cfg = get_user_config(db, owner.id)
                ap = cfg["autopilot"]

            _expire_stale(db, owner.id, sched.get("analysis_timeout_seconds", 300))
            if db.query(TaskResult).filter(
                TaskResult.user_id == owner.id, TaskResult.status.in_(("queued", "running"))
            ).first():
                return {"skipped": "an analysis is already running"}

            reason = evaluate_goals(ap, _equity(db, owner.id), now)
            if reason:
                _stop(db, owner.id, reason, cfg)
                return {"stopped": reason}

            interval = timedelta(minutes=int(sched.get("interval_minutes", 60)))
            max_trades = int(sched.get("max_trades_per_day", 10))
            owner_id = owner.id
            watchlist = list(sched.get("watchlist", []))
            auto_execute = bool(sched.get("auto_execute", True))

        for ticker in watchlist:
            with SessionLocal() as db:
                cfg = get_user_config(db, owner_id)
                if not cfg["scheduler"].get("enabled"):
                    break  # paused mid-tick
                if _trades_today(db, owner_id) >= max_trades:
                    break
                if not is_market_open(ticker, cfg["scheduler"], now):
                    continue
                last = _last_task(db, owner_id, ticker)
                if last is not None and _aware(last.created_at) > now - interval:
                    continue
                reason = evaluate_goals(cfg["autopilot"], _equity(db, owner_id))
                if reason:
                    _stop(db, owner_id, reason, cfg)
                    return {"stopped": reason, "ran": ran}
                task_id = str(uuid4())
                db.add(TaskResult(task_id=task_id, user_id=owner_id, ticker=ticker, status="queued"))
                db.commit()
            _running_ticker = ticker
            try:
                _do_analysis(task_id, owner_id, ticker, now.strftime("%Y-%m-%d"), auto_execute)
                ran.append(ticker)
            finally:
                _running_ticker = None
        _last_error = None
        return {"ran": ran}
    except Exception as e:
        _last_error = f"{type(e).__name__}: {e}"
        logger.exception("Autopilot tick failed")
        return {"error": _last_error, "ran": ran}
    finally:
        _tick_lock.release()
