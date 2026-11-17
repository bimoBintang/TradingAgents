# Panduan deploy ke Vast.ai (RTX 5090, disk 130 GB, LLM lokal)

> **Status jujur:** image dan seluruh alur ini **belum pernah dibangun atau dijalankan** (ditulis tanpa Docker, GPU, atau Vast).
> Angka VRAM, disk, dan waktu di bawah adalah **perkiraan**. Perlakukan boot pertama sebagai uji coba, dan jalankan hanya dengan
> **paper trading atau akun demo** sampai semuanya terbukti. Jangan taruh uang sungguhan dulu.

## 1. Apa yang akan berjalan

Satu container (Vast tidak menyediakan docker-compose) menjalankan semuanya lewat supervisord:

| Program | Fungsi | Port (hanya `127.0.0.1`) |
|---|---|---|
| `ollama` | server LLM lokal di GPU | 11434 |
| `ollama_models` | sekali jalan: unduh model, panaskan, cek 100% GPU | - |
| `backend` | API + autopilot + job latar | 8000 |
| `mcp` | server MCP untuk AI/klien lain | 8765 |
| `mcpo` | MCP → REST/OpenAPI (Open WebUI) | 8100 |
| `xvfb`, `mt5terminal`, `mt5bridge` | hanya bila `MT5_LOGIN` diisi (forex) | 18812 |

Semua port terikat ke `127.0.0.1` karena API dan MCP **tidak punya autentikasi**. Anda mengaksesnya lewat **SSH tunnel** (bagian 6).

### Tiga peran model

| Tier | Model | Dipakai untuk | Ukuran (Q4, perkiraan) |
|---|---|---|---|
| deep | `deepseek-r1:32b` | debat Bull/Bear, Trader (`<TRADE_DECISION>`), manajer, risk judge | ±20 GB |
| smart + fast | `qwen2.5:7b` | semua analis (satu model melayani dua tier) | ±4,7 GB |
| vision (opsional) | `qwen2.5vl:7b` | ChartVision, hanya bila ada screenshot chart | ±6 GB |

Vision **tidak diunduh secara default**: server tanpa layar tidak punya screenshot TradingView, dan ChartVision otomatis memakai fallback
indikator. Aktifkan dengan `TA_PULL_VISION=1` bila perlu.

### Anggaran (perkiraan, belum diukur)

- **VRAM 32 GB:** r1 ±20 GB + KV cache ±2 GB, qwen2.5:7b ±5 GB → **±27 GB**, muat. Dengan vision ±33 GB: **tidak muat**; set
  `OLLAMA_NUM_PARALLEL=1` dan `OLLAMA_MAX_LOADED_MODELS=3` dan terima bahwa Ollama akan bongkar-muat model.
- **Disk 130 GB:** model ±25 GB (±31 GB dengan vision) + Ollama dan pustaka CUDA ±4 GB + image (Wine, Python, dependensi) ±10-15 GB +
  data/log. Sisa lebih dari 70 GB. Disk Vast **tidak bisa diubah ukurannya** setelah instance dibuat; 130 GB cukup.
- **Kecepatan:** r1:32b menulis ribuan token "berpikir" per jawaban. Satu analisis bisa memakan **puluhan menit** (bagian 8).

## 2. Persiapan (di laptop)

1. Akun Vast.ai, kredit, dan **SSH key** terdaftar di akun.
2. Akun registry (mis. Docker Hub).
3. Buat `FERNET_KEY` dan **simpan di tempat aman** (tanpanya kunci bursa yang tersimpan tidak terbaca lagi):
   ```
   python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```
4. Bangun dan unggah image dari root repo (tambahkan `--platform linux/amd64` bila laptop Anda Apple Silicon):
   ```
   docker build -f deploy/vast/Dockerfile -t USERNAME/tradingagents:0.1 .
   docker push USERNAME/tradingagents:0.1
   ```
   Build pertama hampir pasti butuh perbaikan (versi paket Wine, installer Python Windows, `mt5linux`, skrip instal Ollama).
   Bila Anda tidak memakai forex, bagian Wine/MT5 tetap terpasang tetapi tidak dijalankan.

## 3. Sewa instance di Vast

Filter pencarian:
- GPU **RTX 5090**, jumlah 1.
- **Disk 130 GB**.
- **CUDA ≥ 12.8 / driver NVIDIA ≥ 570** (RTX 5090 = Blackwell; driver atau Ollama yang terlalu lama tidak akan memakai GPU-nya).
- Kecepatan internet unduh tinggi (unduhan model ±25 GB), reliabilitas host tinggi, tipe **on-demand** (bukan interruptible, karena
  instance yang diambil alih membuat autopilot berhenti di tengah posisi).

Template/instance:
- **Image:** `USERNAME/tradingagents:0.1`.
- **Launch mode:** pilih mode yang menjalankan `ENTRYPOINT` image. Bila Vast hanya menawarkan mode SSH/Jupyter (yang tidak menjalankan
  ENTRYPOINT), isi **On-start script** dengan: `nohup /entrypoint.sh > /var/log/tradingagents.log 2>&1 &` (opsi berbeda di tiap
  versi UI Vast; periksa dokumentasinya).
- **Port:** jangan memetakan port apa pun (`-p` kosong). Semua layanan hanya loopback dan diakses lewat SSH.
- **Environment variables:**

| Variabel | Wajib? | Keterangan |
|---|---|---|
| `FERNET_KEY` | **Ya** | dari langkah 2.3. `ENVIRONMENT=production` (bawaan) membuat backend menolak start tanpa ini |
| `TRADINGAGENTS_LLM_PRESET` | tidak | bawaan `ollama` |
| `TA_PULL_VISION` | tidak | `1` untuk ikut mengunduh `qwen2.5vl:7b` |
| `OLLAMA_NUM_PARALLEL`, `OLLAMA_MAX_LOADED_MODELS`, `OLLAMA_CONTEXT_LENGTH` | tidak | menimpa `deploy/ollama/ollama.env` |
| `ANTHROPIC_API_KEY` dll. | tidak | hanya bila Anda mengganti preset ke model awan |
| `MT5_LOGIN`, `MT5_PASSWORD`, `MT5_SERVER`, `MT5_SETUP_URL` | hanya forex | **akun DEMO**; mengaktifkan Wine/MT5 |
| `DATABASE_URL` | tidak | bawaan SQLite di `/workspace/tradingagents/app.db` |

Data yang perlu bertahan ada di `/workspace` (model Ollama, database, hasil). Itu bertahan saat instance **dihentikan lalu dijalankan
lagi**, tetapi **hilang bila instance dihancurkan**. Cadangkan `app.db` dan `FERNET_KEY` Anda.

## 4. Boot pertama

Boot pertama mengunduh model; tunggu ±10-40 menit tergantung kecepatan host. Masuk lewat SSH (perintah ada di tombol Connect Vast):

```
ssh -p PORT root@IP_VAST
supervisorctl status            # semua RUNNING; ollama_models berstatus EXITED (exit 0) setelah selesai
tail -f /var/log/supervisor/ollama_models*.log     # progres unduhan
```

Daftar periksa (semuanya harus lolos sebelum lanjut):
1. `nvidia-smi` menampilkan RTX 5090.
2. `ollama ps` menampilkan model dengan **PROCESSOR 100% GPU** (skrip setup juga memperingatkan bila ada yang tumpah ke CPU).
3. `curl -s localhost:8000/api/health` → `{"status":"ok",...}`.
4. Uji model: `PYTHONPATH=/app:/app/TradingAgents python3 /app/deploy/ollama/smoke_test.py` (memastikan tidak ada `<think>` bocor dan
   tool-calling qwen2.5 bekerja).
5. `supervisorctl status backend` tidak berulang restart (cek `FERNET_KEY` bila gagal).

## 5. Akses dari laptop (SSH tunnel)

```
ssh -p PORT root@IP_VAST -L 8010:127.0.0.1:8000 -L 8100:127.0.0.1:8100 -L 8765:127.0.0.1:8765
```

(Memakai 8010 di laptop bila port 8000 Anda sudah dipakai proyek lain; ganti sesuai kebutuhan.) Biarkan sesi ini terbuka.

Dashboard dijalankan **di laptop** (image tidak menyajikan dashboard) dan menunjuk ke tunnel:

```
cd dashboard
echo "VITE_API_URL=http://localhost:8010" > .env.local
npm ci && npm run dev -- --port 5173      # CORS backend hanya menerima localhost:5173 dan :3000
```

Buka `http://localhost:5173`; sidebar harus menampilkan **API ONLINE**.

## 6. Konfigurasi dan mulai (di dashboard)

1. **Settings → API Management:** pilih pasar/broker (bursa kripto + API key, Alpaca untuk saham, atau MetaTrader 5 untuk forex).
   Nyalakan **Testnet/Sandbox** lebih dulu, lalu **Test Connection**.
2. **Settings → Execution:** spot atau futures, leverage, dan biarkan **Require Trade Confirmation** aktif (order menunggu persetujuan Anda).
3. **AI Config:** watchlist (`BTC-USD`, `NVDA`, atau `EURUSD`), interval, batas trade/hari.
4. **Jangan menyimpan pengaturan di "AI Language Models" tanpa memeriksa**: nilainya bisa menimpa preset Ollama yang datang dari env.
5. **Percepat percobaan pertama** (r1 sangat lambat): turunkan ronde debat lewat API (tidak ada di UI):
   ```
   curl -X PUT localhost:8010/api/config -H 'Content-Type: application/json' \
     -d '{"updates":{"max_debate_rounds":1,"max_risk_discuss_rounds":1}}'
   ```
6. Di kartu **AI Autopilot** (Overview) tekan **Analisis sekarang** untuk satu ticker dan tunggu; lihat hasilnya di panel **Keputusan AI**.
   Bila sukses, isi **target profit / batas rugi / waktu selesai**, lalu **Mulai autopilot**.

## 7. Biaya dan operasional

- Vast menagih per jam selama instance **berjalan**; instance yang **dihentikan** masih menagih penyimpanan disk, jauh lebih murah.
  Hentikan instance saat tidak dipakai (model tetap di disk). **Hancurkan** hanya bila siap kehilangan data.
- Autopilot berhenti sendiri saat target tercapai, tetapi instance tetap menyala dan menagih; matikan manual.
- Setelah restart, supervisord menyalakan ulang semua layanan; autopilot melanjutkan dari baseline di database.

## 8. Masalah umum

| Gejala | Kemungkinan penyebab / tindakan |
|---|---|
| `ollama ps` bukan 100% GPU | VRAM kurang: `OLLAMA_NUM_PARALLEL=1`, `OLLAMA_CONTEXT_LENGTH=4096`, atau jangan unduh vision |
| Ollama memakai CPU saja | driver < 570 / CUDA < 12.8 pada host, atau versi Ollama terlalu lama: sewa host lain atau bangun ulang image |
| Backend terus restart | `FERNET_KEY` kosong (`ENVIRONMENT=production`); lihat `/var/log/supervisor/backend*.log` |
| `ollama_models` gagal | host kehabisan disk/jaringan; jalankan ulang `supervisorctl start ollama_models` |
| Analisis sangat lambat atau timeout | normal untuk r1; kurangi ronde debat (bagian 6 langkah 5), `llm_timeout` bawaan 900 dtk |
| Dashboard OFFLINE | tunnel putus atau port salah; `VITE_API_URL` harus sama dengan port lokal tunnel |
| Instal MT5 gagal | installer sering butuh dialog; coba `MT5_SETUP_URL` dari broker, atau instal sekali dan simpan `WINEPREFIX` di `/workspace` |
| Autopilot tidak menganalisis | harus **dimulai** (kartu Autopilot), pasar harus buka (forex Sen-Jum), dan interval belum jatuh tempo |

## 9. Keamanan

- API, MCP, dan mcpo **tanpa autentikasi** dan hanya di loopback. **Jangan** memetakan portnya di Vast dan jangan mengubah bind ke `0.0.0.0`.
- Jangan membagikan `FERNET_KEY`; simpan kunci bursa dengan izin **trade saja, tanpa izin withdraw**, dan batasi IP bila bursa mendukung.
- Mulai dengan paper/testnet/demo; live hanya setelah berminggu-minggu berjalan baik, dengan ukuran sangat kecil.

## 10. Yang belum teruji

Build image, Wine/MT5, instal Ollama di image, unduhan dan pemanasan model pada RTX 5090, angka VRAM/disk/waktu di atas, analisis penuh dengan
r1 + qwen2.5, jalur live apa pun, dan Open WebUI lewat mcpo. Laporkan apa pun yang gagal agar panduan ini bisa dikoreksi.
