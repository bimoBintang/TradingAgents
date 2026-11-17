"""Autopilot control + AI decision feed (logic in api/services/autopilot.py)."""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.auth import get_current_user
from api.database import get_db
from api.models import User
from api.services import autopilot

router = APIRouter(prefix="/api", tags=["Autopilot"])


class StartRequest(BaseModel):
    target_profit_pct: Optional[float] = Field(None, gt=0, description="Stop when equity is up this % since start")
    max_loss_pct: Optional[float] = Field(None, gt=0, description="Stop when equity is down this % since start")
    end_at: Optional[str] = Field(None, description="ISO timestamp (UTC) at which the run ends")


class WatchlistRequest(BaseModel):
    tickers: List[str]


def _call(fn, db, *args, **kwargs):
    try:
        return fn(db, *args, **kwargs)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/autopilot")
async def get_autopilot(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return autopilot.status(db)


@router.post("/autopilot/start")
async def start_autopilot(body: StartRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _call(autopilot.start, db, body.target_profit_pct, body.max_loss_pct, body.end_at)


@router.post("/autopilot/pause")
async def pause_autopilot(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _call(autopilot.pause, db)


@router.post("/autopilot/resume")
async def resume_autopilot(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _call(autopilot.resume, db)


@router.put("/autopilot/watchlist")
async def put_watchlist(body: WatchlistRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _call(autopilot.set_watchlist, db, body.tickers)


@router.get("/decisions")
async def get_decisions(limit: int = 20, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return autopilot.decisions(db, limit)
