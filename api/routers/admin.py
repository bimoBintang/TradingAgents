"""Admin-only API endpoints.

All routes protected by `get_current_admin_user` (403 if not admin).
"""

import logging
from datetime import timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func

from api.database import get_db
from api.models import User, PortfolioState, Position, Trade
from api.auth import get_current_admin_user
from api.schemas import AdminUserItem, AdminSystemStats, AdminRoleUpdate, AdminConfig, AdminConfigUpdate

logger = logging.getLogger("api.admin")

router = APIRouter(prefix="/api/admin", tags=["admin"])


# ── GET /api/admin/stats ──────────────────────────────────────────────

@router.get("/stats", response_model=AdminSystemStats)
async def get_admin_stats(
    _admin: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    """Return global platform statistics (admin only)."""
    total_users = db.query(func.count(User.id)).scalar() or 0
    admin_users = db.query(func.count(User.id)).filter(User.is_admin == True).scalar() or 0

    total_trades = db.query(func.count(Trade.id)).scalar() or 0
    total_volume = db.query(func.sum(Trade.fill_price * Trade.filled_qty)).scalar() or 0.0

    ps = db.query(PortfolioState).first()
    total_equity = ps.total_equity if ps else 0.0

    active_positions = db.query(func.count(Position.id)).scalar() or 0

    return AdminSystemStats(
        total_users=total_users,
        admin_users=admin_users,
        total_trades=total_trades,
        total_platform_volume=round(total_volume, 2),
        total_equity=round(total_equity, 2),
        active_positions=active_positions,
    )


# ── GET /api/admin/users ──────────────────────────────────────────────

@router.get("/users", response_model=list[AdminUserItem])
async def get_admin_users(
    _admin: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    """List all registered users (admin only)."""
    users = db.query(User).order_by(User.created_at.desc()).all()
    return [
        AdminUserItem(
            id=u.id,
            email=u.email,
            name=u.name,
            is_admin=u.is_admin or False,
            created_at=u.created_at.isoformat() if u.created_at else "",
            status="active",
        )
        for u in users
    ]


# ── GET /api/admin/users/{user_id}/details ────────────────────────────

@router.get("/users/{user_id}/details")
async def get_admin_user_details(
    user_id: int,
    _admin: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    """Get deep details, portfolio stats, and metics for a specific user."""
    from api.schemas import AdminUserDetailsResponse
    user = db.query(User).filter(User.id == user_id).first()
    
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        
    portfolio = db.query(PortfolioState).filter(PortfolioState.user_id == user.id).first()
    # legacy fallback for dummy admin if they own the global block:
    if not portfolio and user.is_admin:
         portfolio = db.query(PortfolioState).filter(PortfolioState.user_id == None).first()
         
    active_positions_count = 0
    if portfolio:
         active_positions_count = db.query(func.count(Position.id)).filter(Position.portfolio_id == portfolio.id).scalar() or 0
         
    return AdminUserDetailsResponse(
        id=user.id,
        email=user.email,
        name=user.name,
        is_admin=user.is_admin or False,
        created_at=user.created_at.isoformat() if user.created_at else "",
        portfolio_balance=portfolio.cash_balance if portfolio else 0.0,
        total_equity=portfolio.total_equity if portfolio else 0.0,
        total_pnl=portfolio.total_pnl if portfolio else 0.0,
        win_rate=portfolio.win_rate if portfolio else 0.0,
        total_trades=portfolio.total_trades if portfolio else 0,
        max_drawdown_pct=portfolio.max_drawdown_pct if portfolio else 0.0,
        active_positions_count=active_positions_count
    )

# ── PUT /api/admin/users/{user_id}/role ───────────────────────────────

@router.put("/users/{user_id}/role")
async def update_user_role(
    user_id: int,
    body: AdminRoleUpdate,
    _admin: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    """Promote or demote a user's admin role (admin only)."""
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # Prevent self-demotion
    if target.id == _admin.id and not body.is_admin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot revoke your own admin role",
        )

    target.is_admin = body.is_admin
    db.commit()
    logger.info(f"Admin role for user {target.email} set to {body.is_admin}")
    return {"status": "ok", "user_id": user_id, "is_admin": body.is_admin}


# ── GET /api/admin/config ──────────────────────────────────────────────

@router.get("/config", response_model=AdminConfig)
async def get_admin_config(
    _admin: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    """Get global platform configuration (admin only)."""
    from api.models import PlatformConfig
    config = db.query(PlatformConfig).first()
    if not config:
        config = PlatformConfig(id=1, maintenance_mode=False, allow_registration=True, global_max_leverage=50)
        db.add(config)
        db.commit()
        db.refresh(config)
    
    return AdminConfig(
        maintenance_mode=config.maintenance_mode,
        allow_registration=config.allow_registration,
        global_max_leverage=config.global_max_leverage
    )

# ── PUT /api/admin/config ──────────────────────────────────────────────

@router.put("/config", response_model=AdminConfig)
async def update_admin_config(
    body: AdminConfigUpdate,
    _admin: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    """Update global platform configuration (admin only)."""
    from api.models import PlatformConfig
    config = db.query(PlatformConfig).first()
    if not config:
        config = PlatformConfig(id=1, maintenance_mode=False, allow_registration=True, global_max_leverage=50)
        db.add(config)
    
    if body.maintenance_mode is not None:
        config.maintenance_mode = body.maintenance_mode
    if body.allow_registration is not None:
        config.allow_registration = body.allow_registration
    if body.global_max_leverage is not None:
        config.global_max_leverage = body.global_max_leverage
        
    db.commit()
    db.refresh(config)
    
    logger.warning(f"Admin {_admin.email} updated platform config: Maint={config.maintenance_mode}, Reg={config.allow_registration}, MaxLev={config.global_max_leverage}")
    
    return AdminConfig(
        maintenance_mode=config.maintenance_mode,
        allow_registration=config.allow_registration,
        global_max_leverage=config.global_max_leverage
    )
