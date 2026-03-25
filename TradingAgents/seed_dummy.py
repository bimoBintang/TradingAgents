import os
import random
from datetime import datetime, timezone, timedelta

from api.database import SessionLocal, engine
from api.models import Base, User, PortfolioState, Position, Trade
from api.auth import hash_password

def seed():
    print("🚀 Creating database tables...")
    Base.metadata.create_all(bind=engine)
    
    db = SessionLocal()
    
    # 1. Seed Admin User
    admin_email = "admin@tradingagents.ai"
    if not db.query(User).filter(User.email == admin_email).first():
        db.add(User(
            email=admin_email,
            name="Admin User",
            hashed_password=hash_password("admin123")
        ))
        print("✅ Seeded Admin User.")
        
    # 2. Seed Portfolio State
    ps = db.query(PortfolioState).first()
    if not ps:
        ps = PortfolioState(
            cash_balance=35000.0,
            total_equity=125500.0,
            total_pnl=25500.0,
            daily_pnl=1240.50,
            win_rate=0.68,
            max_drawdown_pct=0.12,
            total_trades=45
        )
        db.add(ps)
        db.commit()
        db.refresh(ps)
        print("✅ Seeded Portfolio State.")
    
    # Clear old data for clean insert
    db.query(Position).delete()
    db.query(Trade).delete()
    
    # 3. Seed Open Positions
    positions = [
        Position(portfolio_id=ps.id, ticker="BTC-USD", side="BUY", quantity=0.5, entry_price=64000.0, current_price=66500.0, unrealized_pnl=1250.0),
        Position(portfolio_id=ps.id, ticker="ETH-USD", side="BUY", quantity=10.0, entry_price=3300.0, current_price=3500.0, unrealized_pnl=2000.0),
        Position(portfolio_id=ps.id, ticker="NVDA", side="SELL", quantity=50.0, entry_price=135.0, current_price=130.0, unrealized_pnl=250.0),
        Position(portfolio_id=ps.id, ticker="TSLA", side="BUY", quantity=100.0, entry_price=180.0, current_price=175.0, unrealized_pnl=-500.0),
    ]
    db.add_all(positions)
    print(f"✅ Seeded {len(positions)} Open Positions.")
    
    # 4. Seed Journal Trades (Past 30 days)
    now = datetime.now(timezone.utc)
    tickers = ["BTC-USD", "ETH-USD", "SOL-USD", "NVDA", "AAPL", "MSFT", "TSLA"]
    actions = ["BUY", "SELL"]
    
    trades = []
    for i in range(45):
        days_ago = random.randint(1, 30)
        t_time = now - timedelta(days=days_ago, hours=random.randint(0, 23))
        ticker = random.choice(tickers)
        action = random.choice(actions)
        
        is_win = random.random() < 0.68  # math matching the win_rate
        pnl = random.uniform(50.0, 800.0) if is_win else random.uniform(-400.0, -50.0)
        
        price = random.uniform(100.0, 60000.0)
        qty = random.uniform(0.1, 50.0)
        
        trades.append(Trade(
            portfolio_id=ps.id,
            ticker=ticker,
            action=action,
            filled_qty=round(qty, 4),
            fill_price=round(price, 2),
            realized_pnl=round(pnl, 2),
            status="FILLED",
            fill_time=t_time,
            created_at=t_time
        ))
        
    db.add_all(trades)
    db.commit()
    print(f"✅ Seeded {len(trades)} Historical Trades.")
    
    db.close()
    print("🎉 Dummy data successfully generated in SQLite!")

if __name__ == "__main__":
    seed()
