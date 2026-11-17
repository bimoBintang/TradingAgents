> **Panduan lengkap deploy (RTX 5090, disk 130 GB, LLM lokal): lihat [PANDUAN.md](PANDUAN.md).**

> **API tanpa autentikasi.** Login sudah dihapus: siapa pun yang dapat menjangkau port 8000 dapat
> approve order live, membaca saldo, dan mengubah config. Jangan buka port itu ke internet; akses lewat
> SSH tunnel/VPN, atau pasang proteksi di depannya (firewall, reverse proxy dengan auth).

# Deploy backend + MetaTrader 5 (Wine) di Vast.ai

Satu container: Xvfb + terminal MT5 (Wine) + jembatan RPyC (`mt5linux`) + backend FastAPI.
**Belum pernah di-build atau dijalankan** (ditulis tanpa akses Docker/Wine). Perkirakan penyesuaian pada build pertama.

## Peringatan keamanan
- Mesin Vast.ai milik pihak ketiga; host dapat membaca env dan memori container. **Pakai akun demo dulu**, lalu akun modal kecil dengan password yang hanya boleh trading.
- Jembatan RPyC (port 18812) tidak punya autentikasi. Di sini ia hanya listen di `127.0.0.1`. Jangan menambahkannya ke daftar port Vast.ai.
- `common.ini` berisi password di disk container (mode 600).

## Build
```bash
docker build -f deploy/vast/Dockerfile -t <user>/tradingagents-mt5:latest .
docker push <user>/tradingagents-mt5:latest
```

## Template Vast.ai
- Image: `<user>/tradingagents-mt5:latest`; launch mode: entrypoint (bukan SSH-only).
- Port: `8000` (API). Disk: ≥ 20 GB (Wine + Python Windows + terminal).
- Env wajib: `MT5_LOGIN`, `MT5_PASSWORD`, `MT5_SERVER`, `MT5_SETUP_URL` (installer `mt5setup.exe` dari broker Anda).
- Env opsional: `MT5_SYMBOL_SUFFIX` (mis. `.m`), `DATABASE_URL`, `FERNET_KEY` (wajib untuk menyimpan kredensial), kunci LLM.
- Instance mahal tidak diperlukan: MT5 dan backend tidak memakai GPU. RTX 5090 hanya berguna bila Anda menjalankan LLM lokal.

## Setelah jalan
1. Simpan konfigurasi `execution.broker = "mt5"` lewat API config (`mode` otomatis `live` bila env MT5 lengkap).
2. `POST /api/config/test-broker` dengan `{"broker": "mt5"}` harus mengembalikan saldo.
3. Coba satu order demo 0.01 lot, dan pastikan SL tampil di terminal.

## Yang perlu diverifikasi sendiri
- Flag CLI `python3 -m mt5linux` pada versi yang terpasang (`--help`) dan sintaks perintah Python Wine.
- Versi `MetaTrader5` yang tersedia untuk Python 3.10 di Wine.
- Tombol AutoTrading di terminal harus aktif; `common.ini` meminta itu tetapi perilakunya di Wine belum terbukti.
- Installer MT5 sering butuh dialog; `/auto` bisa gagal pada broker tertentu. Alternatif: install sekali, lalu simpan `WINEPREFIX` di volume.

## Analisis otonom (autopilot)

AI otonom berjalan **di dalam API** (job tiap 60 detik) dan dikendalikan dari dashboard (kartu Autopilot di Overview, AI Config,
Settings) atau lewat MCP. Config yang dipakai adalah config pemilik di database, jadi pengaturan dashboard benar-benar berlaku.
Jangan menjalankan loop CLI (`tradingagents.cli --schedule`) bersamaan: dua loop akan menggandakan trade.

- **Berhenti sendiri:** saat memulai, isi target profit %, batas rugi %, dan/atau waktu selesai. Begitu salah satu tercapai AI tidak
  membuka analisis baru; posisi terbuka tetap dijaga stop di broker dan exit monitor.
- **Default aman:** autopilot mati sampai dimulai; mode konfirmasi order aktif (order menunggu persetujuan di dashboard atau MCP).
- **Pasar:** pilih di Settings: bursa kripto (spot/futures), Alpaca (saham), atau MetaTrader 5 (forex). Satu akun, satu broker.

### Forex (MT5)

Set `MT5_LOGIN/PASSWORD/SERVER` (akun **DEMO**), pilih "MetaTrader 5" di Settings, watchlist `EURUSD` di AI Config. Analis forex,
data `EURUSD=X`, dan jam pasar Senin-Jumat dipakai otomatis. Jalur MT5 belum pernah diuji pada terminal sungguhan.

### MCP (AI apa pun)

Program `mcp` menjalankan server MCP streamable-http di `127.0.0.1:8765`, **tanpa autentikasi**. Akses lewat SSH tunnel
(`ssh -L 8765:127.0.0.1:8765 ...`), jangan membuka port. Tool: status/mulai/jeda/lanjut autopilot, watchlist, keputusan AI,
portfolio, analisis, daftar/setujui/tolak order, dan kontrol chart. Klien harus mendukung MCP.

### AI lokal (Open WebUI + Ollama) lewat mcpo

Ollama dan sebagian besar klien lokal tidak berbicara MCP, jadi program `mcpo` mengubah server MCP di atas menjadi REST/OpenAPI di
`127.0.0.1:8100` (dokumen: `/openapi.json`, 27 endpoint, satu per tool). Sudah diuji: status, watchlist, mulai (tanpa target ditolak),
jeda, dan keputusan AI memberi hasil yang sama dengan API dashboard.

- Tunnel: `ssh -L 8100:127.0.0.1:8100 ...`, lalu di Open WebUI: Settings > Tools > tambah **Tool Server** `http://localhost:8100`.
- **Model harus mendukung function-calling:** `qwen2.5:7b` / `qwen3:8b` ya; `deepseek-r1` **tidak** (pakai untuk debat di dalam, bukan untuk chat bertool).
- mcpo wajib `--host 127.0.0.1` (bawaannya `0.0.0.0`; API dan MCP tanpa autentikasi). Versi mcpo 0.0.20 perlu `mcp<2` dan `fastapi<0.125`
  (sudah dipin di `supervisord.conf`); tanpa pin ia gagal start. Open WebUI sendiri belum diuji, dan kualitas pemanggilan tool oleh
  model 7B belum diukur.
