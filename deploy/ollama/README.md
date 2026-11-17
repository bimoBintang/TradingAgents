# LLM lokal dengan Ollama (3 tingkat)

| Tingkat | Model | Dipakai untuk |
|---|---|---|
| deep | `deepseek-r1:32b` | Bull, Bear, Trader (`<TRADE_DECISION>`), research/risk manager, optimizer, synthesizer |
| smart | `qwen2.5:7b` | analis quant/macro_geo/correlation, debator risiko, reflector |
| fast | `qwen2.5:7b` | analis lain (paralel), ekstraksi JSON akhir |

`deepseek-r1` tidak mendukung tool-calling di Ollama, jadi hanya boleh di tingkat deep; backend menolak start jika ia dipasang di smart/fast.

## Menjalankan
```bash
set -a; source deploy/ollama/ollama.env; set +a
ollama serve &                     # Ollama baru diperlukan untuk OLLAMA_CONTEXT_LENGTH
deploy/ollama/setup_models.sh      # pull + warm-up + cek 100% GPU
export TRADINGAGENTS_LLM_PRESET=ollama
# opsional: export OLLAMA_BASE_URL=http://host:11434/v1
PYTHONPATH=$PWD:$PWD/TradingAgents python deploy/ollama/smoke_test.py
```

## VRAM (RTX 5090, 32 GB) — perkiraan, belum diukur
Smart dan fast memakai bobot yang sama (`qwen2.5:7b`), jadi hanya tiga model fisik bila vision ikut (di image Vast vision opsional: `TA_PULL_VISION=1`; `OLLAMA_MAX_LOADED_MODELS` bawaan kini 2): r1 ±20 GB + qwen2.5 ±5 GB + `qwen2.5vl:7b` ±5 GB
(ChartVision, `vision_llm`), ditambah KV cache. Totalnya ±30 GB: pas di 32 GB tetapi belum diukur.
`setup_models.sh` akan memberi peringatan bila ada model yang tidak 100% di GPU. Cadangan: `OLLAMA_NUM_PARALLEL=1`, konteks lebih kecil,
atau ubah `vision_llm`. Tanpa TradingView Desktop/screenshot, ChartVision melapor "UNAVAILABLE" (tidak membutuhkan model vision).

## Analis berurutan dan ChartVision
Preset ini memakai `analyst_execution = "sequential"`: analis jalan satu per satu (satu model aktif sekaligus), jadi total waktu
memanjang. Kembalikan ke `"parallel"` bila GPU cukup. Tanpa screenshot TradingView, ChartVision memberi laporan dari indikator
(`mode=FALLBACK_QUANTITATIVE_TA`, tren saja; pola dan level `None`). `ICT` (tanpa LLM, butuh OHLC nyata) dan `ChartVision` (`vision_llm`) kini node graph dan masuk ke Synthesizer; tanpa data mereka melapor "unavailable".

## Kecepatan
r1:32b menulis ribuan token "berpikir" per jawaban, dan di preset ini ia menangani debat, trader, dan para manajer.
Turunkan `max_debate_rounds` dan `max_risk_discuss_rounds` bila satu analisis terlalu lama. `llm_timeout` = 900 detik per panggilan.

## Mengembalikan ke Anthropic
Hapus `TRADINGAGENTS_LLM_PRESET`. Default tidak berubah.
