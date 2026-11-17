# Backend + MetaTrader5 (under Wine) in ONE container, for Vast.ai (no docker-compose there).
# Build from the repo root:  docker build -f deploy/vast/Dockerfile -t tradingagents-mt5 .
#
# UNTESTED: written without access to Docker/Wine. Expect to adjust package versions
# on first build. The GPU is used by Ollama (local LLMs).
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive \
    WINEARCH=win64 \
    WINEPREFIX=/opt/wineprefix \
    WINEDEBUG=-all \
    DISPLAY=:99 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app:/app/TradingAgents

RUN dpkg --add-architecture i386 \
 && apt-get update \
 && apt-get install -y --no-install-recommends \
      wget curl ca-certificates zstd gnupg2 xvfb xauth cabextract supervisor git \
      python3.10 python3-pip python3.10-venv build-essential libpq-dev \
 && rm -rf /var/lib/apt/lists/*

# WineHQ stable
RUN mkdir -pm755 /etc/apt/keyrings \
 && wget -O /etc/apt/keyrings/winehq-archive.key https://dl.winehq.org/wine-builds/winehq.key \
 && wget -NP /etc/apt/sources.list.d/ https://dl.winehq.org/wine-builds/ubuntu/dists/jammy/winehq-jammy.sources \
 && apt-get update \
 && apt-get install -y --install-recommends winehq-stable \
 && rm -rf /var/lib/apt/lists/*

# Windows Python inside Wine: the MetaTrader5 package only exists for Windows.
# 3.10.11 is the last 3.10 release that ships a binary installer.
ARG WIN_PYTHON_URL=https://www.python.org/ftp/python/3.10.11/python-3.10.11-amd64.exe
RUN xvfb-run -a sh -c "wineboot -i && \
      wget -q -O /tmp/pywin.exe ${WIN_PYTHON_URL} && \
      wine /tmp/pywin.exe /quiet InstallAllUsers=1 PrependPath=1 && \
      wineserver -w" \
 && rm -f /tmp/pywin.exe

# Pin both sides to the same rpyc/mt5linux so the bridge protocol matches.
ARG MT5LINUX_VERSION=0.1.9
RUN xvfb-run -a wine python -m pip install --no-cache-dir MetaTrader5 "mt5linux==${MT5LINUX_VERSION}" rpyc numpy plumbum \
 && wineserver -w

# Backend (Linux Python)
COPY orchestrator /app/orchestrator
COPY TradingAgents /app/TradingAgents
WORKDIR /app/TradingAgents
RUN pip3 install --no-cache-dir --upgrade pip \
 && pip3 install --no-cache-dir -e ".[api,forex,mcp]" "mt5linux==${MT5LINUX_VERSION}"

# uv runs mcpo in its own Python 3.11 env (mcpo needs >=3.11, the image Python is 3.10). Warm the cache at build time.
RUN pip3 install --no-cache-dir uv && uvx --python 3.11 --with "mcp<2" --with "fastapi<0.125" mcpo --help >/dev/null
# Ollama (local LLM server). Needs a recent version for the RTX 5090 (Blackwell, CUDA 12.8+).
RUN curl -fsSL https://ollama.com/install.sh | sh
COPY deploy/ollama /app/deploy/ollama
RUN chmod +x /app/deploy/ollama/setup_models.sh
COPY deploy/vast/supervisord.conf /etc/supervisor/conf.d/tradingagents.conf
COPY deploy/vast/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Only the API is meant to be reachable. The rpyc bridge (18812) has NO authentication
# and is bound to 127.0.0.1 in supervisord.conf; never publish it.
# The API is bound to 127.0.0.1 inside the container; reach it through an SSH tunnel.
EXPOSE 8000
ENTRYPOINT ["/entrypoint.sh"]
