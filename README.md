# TradingAgents Monorepo

Selamat datang di repository resmi **TradingAgents**. Repository ini menggunakan struktur *Monorepo*, yang mencakup *Backend AI Engine* maupun *Frontend Dashboard* di dalam satu tempat yang tertata rapi.

Sistem kami adalah platform trading algoritma otonom berbasis Multi-Agent LLM (Large Language Model) yang dirancang layaknya tim Hedge Fund profesional.

## 📂 Struktur Direktori

```text
/
├── TradingAgents/   # Backend Engine (Python, FastAPI, AI Agents)
└── dashboard/       # Frontend UI (React, Vite, TailwindCSS)
```

## 🧠 Komponen Utama

### 1. Backend (`/TradingAgents`)
Otak dari sistem ini. Menggunakan bahasa Python dengan performa tinggi.
- **Multi-Agent System**: Terdiri dari 10 agen ahli (Technical, Quant, Macro, On-Chain, News, Debater, Risk Manager, dll).
- **Data Integrations**: Terhubung langsung ke Messari, CoinGecko, AlphaVantage, dan yfinance.
- **Risk Management**: Pengawas volatilitas (ATR) & batas paparan modal.
- **Live Trading**: Koneksi terenkripsi ke Binance API via `ccxt`.

### 2. Frontend (`/dashboard`)
Panel kendali visual untuk berinteraksi dengan AI. Diciptakan menggunakan React & Vite.
- **Trade Confirmation**: Sistem otorisasi manual (Approve/Reject) sebelum AI menggunakan uang sesungguhnya.
- **Live Portfolio**: Angka PnL dan visualisasi *equity curve* secara real-time.
- **Pattern Radar**: Deteksi otomatis pola grafik koin kripto di seluruh pasar.

## 🚀 Cara Menekan (Instalasi)

Proyek ini dikonfigurasi dengan `uv` (Fast Python Package Manager).

**1. Menjalankan Backend:**
```bash
cd TradingAgents
uv sync
uv run uvicorn api.main:app --reload --port 8000
```

**2. Menjalankan Dashboard:**
```bash
cd dashboard
npm install
npm run dev
```

---

*Hak Cipta © 2026. TradingAgents.*
