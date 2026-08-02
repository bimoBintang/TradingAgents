# ── Backend Dockerfile for TradingAgents FastAPI & Orchestrator ──
FROM python:3.10-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy project root orchestrator and TradingAgents codebase
COPY orchestrator /app/orchestrator
COPY TradingAgents /app/TradingAgents

# Set working directory to TradingAgents backend
WORKDIR /app/TradingAgents

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir uvicorn fastapi sqlalchemy slowapi pytest pytest-asyncio pydantic requests websockets Pillow psycopg2-binary pgvector redis && \
    pip install --no-cache-dir -e .

# Environment variables
ENV PYTHONPATH="/app:/app/TradingAgents"
ENV DATABASE_URL="sqlite:///./trading_agents.db"
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:8000/api/tradingview/mcp-status || exit 1

# Start FastAPI server
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
