#!/bin/bash
# Pull the models, load each one, and check that they all sit on the GPU.
set -euo pipefail

MODELS=("deepseek-r1:32b" "qwen2.5:7b")  # deep / smart+fast (the same qwen2.5:7b serves both tiers)
# Vision (ChartVision) is only used when a chart screenshot exists; a headless server has none. Opt in with TA_PULL_VISION=1.
[ "${TA_PULL_VISION:-0}" = "1" ] && MODELS+=("qwen2.5vl:7b")
HOST="${OLLAMA_HOST:-http://127.0.0.1:11434}"
case "$HOST" in http*) ;; *) HOST="http://$HOST" ;; esac
export OLLAMA_HOST="$HOST"

echo "Waiting for Ollama at $HOST ..."
for _ in $(seq 1 60); do curl -sf "$HOST/api/version" >/dev/null && break; sleep 2; done
curl -sf "$HOST/api/version" >/dev/null || { echo "Ollama is not reachable at $HOST" >&2; exit 1; }

for m in "${MODELS[@]}"; do ollama pull "$m"; done

# One tiny request per model so every one is resident before the first analysis.
for m in "${MODELS[@]}"; do
  echo "Warming $m ..."
  curl -sf "$HOST/api/generate" -d "{\"model\":\"$m\",\"prompt\":\"ok\",\"stream\":false,\"options\":{\"num_predict\":1}}" >/dev/null
done

echo; ollama ps; echo
if ollama ps | tail -n +2 | grep -qv "100% GPU"; then
  echo "WARNING: at least one model is not 100% on GPU (spilled to CPU = very slow)." >&2
  echo "Fixes: OLLAMA_NUM_PARALLEL=1, a smaller OLLAMA_CONTEXT_LENGTH, or do not pull the vision model." >&2
  exit 2
fi
echo "All models fully on GPU."
