# ── Stage 1: Builder ──────────────────────────────────────────────────
FROM python:3.10-slim AS builder

WORKDIR /build

# System deps for psycopg2 compilation
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

# Install Python deps first (layer caching)
COPY pyproject.toml ./
COPY api/requirements.txt ./api/requirements.txt
RUN pip install --no-cache-dir --prefix=/install \
    -e ".[crypto,stocks]" \
    -r api/requirements.txt

# ── Stage 2: Production ──────────────────────────────────────────────
FROM python:3.10-slim

WORKDIR /app

# Runtime deps only (no gcc)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 curl && \
    rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application code
COPY . .

# Non-root user for security
RUN useradd --create-home appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
