# PantauBerita

Agregator dan bot pemantau berita harian Indonesia berbasis **RSS dan news sitemap resmi media**. PantauBerita mengumpulkan berita terbaru (lintas topik maupun berdasarkan keyword tertentu), menyimpannya secara terstruktur di SQLite, menganalisis tren serta sentimen judul, lalu menyajikannya melalui CLI, laporan Excel/PDF, bot Telegram, dan dashboard Streamlit.

## Fitur Utama

- **Multi-sumber & Multi-topik**: Mengumpulkan berita utama dan 8 kategori topik (`nasional`, `dunia`, `bisnis`, `teknologi`, `hiburan`, `olahraga`, `sains`, `kesehatan`) dari media nasional Indonesia.
- **Kepatuhan `robots.txt` & Rate Limiting**: Memeriksa `robots.txt` per host pada setiap sesi scrape, menerapkan jeda minimal `1,5` detik antar-request, dan melakukan retry dengan exponential backoff.
- **Penyimpanan Idempoten**: Artikel didefinisikan berdasarkan hash SHA-1 dari URL yang dinormalisasi sehingga artikel yang sama dari banyak feed tidak tersimpan ganda, sementara kemunculannya tetap tercatat di relasi feed.
- **Pemantauan Keyword & Pencarian Arsip**: Pencocokan keyword lokal berbasis kata utuh pada seluruh arsip database maupun berita yang baru masuk, lengkap dengan sistem pantauan dan notifikasi otomatis.
- **Backfill Historis**: Mengisi arsip beberapa hari ke belakang menggunakan news sitemap resmi media yang mendukung.
- **Analisis Tren & Sentimen**: Menghitung kata/isu yang sedang naik (*trending*), media paling aktif, serta skor sentimen harian berbasis kamus bahasa Indonesia.
- **Laporan Otomatis**: Ekspor data ke CSV dan pembuatan laporan berkala dalam format Excel (`.xlsx`), PDF (`.pdf`), dan visualisasi grafik (`.png` + wordcloud).
- **Bot Telegram & Dashboard Interaktif**: Akses berita, pencarian instan, grafik, laporan PDF, dan notifikasi keyword via Telegram, serta eksplorasi data visual lewat Streamlit.

## Sumber Berita & Topik

Pengumpulan data hanya mengambil **metadata** dari feed resmi (judul, media, waktu terbit, tautan, dan ringkasan `description` RSS maksimal 300 karakter) tanpa mengunduh atau meng-scrape halaman isi artikel.

| Feed | Sumber |
| --- | --- |
| `utama` | ANTARA (terkini), CNN Indonesia, detikNews, CNBC Indonesia, VIVA, Republika, JPNN |
| `topik:nasional` | CNN Indonesia Nasional, detikNews Berita, VIVA Berita |
| `topik:dunia` | CNN Indonesia Internasional, detikNews Internasional, VIVA Dunia |
| `topik:bisnis` | CNN Indonesia Ekonomi, detikFinance, CNBC Indonesia Market, VIVA Bisnis |
| `topik:teknologi` | CNN Indonesia Teknologi, detikInet, CNBC Indonesia Tech, VIVA Digital |
| `topik:hiburan` | CNN Indonesia Hiburan, detikHot, VIVA Showbiz |
| `topik:olahraga` | CNN Indonesia Olahraga, detikSport, VIVA Sport |
| `topik:sains` | detikEdu, ANTARA Warta Bumi |
| `topik:kesehatan` | detikHealth, CNN Indonesia Gaya Hidup |
| `backfill` | News sitemap `detik.com`, `cnnindonesia.com`, `cnbcindonesia.com`, `viva.co.id` |

> Daftar lengkap URL feed dan aturan pemetaan topik tersedia di [`pantauberita/collector/feeds.py`](pantauberita/collector/feeds.py).

## Arsitektur & Struktur Proyek

```
   ┌──────────────────────────────────────────────┐
   │ RSS resmi media (utama + 8 topik)            │  ← scrape reguler / jadwal
   │ News sitemap resmi media (judul + tanggal)   │  ← backfill historis
   └──────────────────────┬───────────────────────┘
                          │ HTTP (requests, retry, jeda ≥ 1,5 dtk, cek robots.txt)
                          ▼
 scraping.py ──► collector ──► parser ──► storage (SQLite) ◄──┬── analysis ──► reports (Excel, PDF, PNG)
 (CLI)            feeds.py     rss.py       repo.py           │
                                                              ├── bot.py (Telegram + jadwal)
 Task Scheduler / cron ──► scraping.py                        └── dashboard/app.py (Streamlit)
```

- `pantauberita/pipeline.py` (`run`, `run_backfill`, `cari_lokal`) menjadi titik orkestrasi tunggal untuk CLI, penjadwalan, dan bot Telegram.
- Kegagalan pada salah satu feed tidak menghentikan feed lain (run akan ditandai berstatus `sebagian`).
- Database SQLite menggunakan mode WAL dan *foreign keys* aktif agar bot, scraper, dan dashboard dapat membaca/menulis secara bersamaan.

```text
pantau-berita/
├── scraping.py                 # Entrypoint CLI & scheduler standalone
├── bot.py                      # Entrypoint Bot Telegram + jadwal terintegrasi
├── dashboard/
│   └── app.py                  # Dashboard interaktif Streamlit
├── pantauberita/
│   ├── config.py               # Pembacaan .env dan konstanta konfigurasi
│   ├── logging_setup.py        # Konfigurasi logging aplikasi
│   ├── pipeline.py             # Orkestrasi scraping, backfill, dan pencarian lokal
│   ├── reports.py              # Generator laporan Excel, PDF, dan ekspor CSV
│   ├── collector/
│   │   ├── http.py             # HTTP session, retry, rate-limit, dan cek robots.txt
│   │   └── feeds.py            # Katalog feed RSS dan news sitemap media
│   ├── parser/
│   │   └── rss.py              # Parser RSS dan news sitemap
│   ├── storage/
│   │   ├── schema.sql          # Skema tabel SQLite
│   │   └── repo.py             # Layer akses database
│   ├── analysis/
│   │   ├── text.py             # Normalisasi teks, tokenisasi, dan skor sentimen
│   │   ├── metrics.py          # Agregasi metrik topik, media, dan kata trending
│   │   └── charts.py           # Pembuatan grafik dan wordcloud
│   └── telegram/
│       ├── handlers.py         # Handler perintah bot Telegram
│       ├── jobs.py             # Job terjadwal & pengiriman notifikasi keyword
│       └── messages.py         # Formatter pesan Telegram
├── data/
│   ├── stopwords_id.txt        # Daftar stopword bahasa Indonesia
│   ├── kata_positif.txt        # Kamus kata sentimen positif
│   └── kata_negatif.txt        # Kamus kata sentimen negatif
├── tests/
│   ├── fixtures/               # Fixture XML RSS & sitemap untuk pengujian offline
│   └── test_*.py               # Suite unit & integration test
├── .env.example
├── pytest.ini
└── requirements.txt
```

## Instalasi & Konfigurasi

### 1. Clone & Siapkan Environment

```bash
git clone https://github.com/vnz626/pantauberita-bot.git
cd pantauberita-bot

python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux / macOS
source .venv/bin/activate

pip install -r requirements.txt
```

### 2. Inisialisasi Konfigurasi & Database

```bash
cp .env.example .env          # Windows: copy .env.example .env
python scraping.py --init-db
```

Sesuaikan nilai pada `.env`. Mode CLI (`scraping.py`) dapat berjalan tanpa token Telegram, sedangkan `bot.py` membutuhkan `BOT_TOKEN` dan `ADMIN_IDS`.

| Variabel | Default | Keterangan |
| --- | --- | --- |
| `BOT_TOKEN` | – | Token bot Telegram dari `@BotFather` |
| `ADMIN_IDS` | – | Daftar `chat_id` admin, dipisahkan dengan koma |
| `DB_PATH` | `data/berita.db` | Path file database SQLite |
| `SCRAPE_SETIAP_JAM` | `3` | Interval scrape dalam jam (minimal `3`) |
| `JAM_MULAI_SCRAPE` | `06:00` | Jam mulai jadwal scrape (WIB) |
| `JAM_LAPORAN` | `07:00` | Jam pengiriman laporan harian (WIB) |
| `JEDA_DETIK` | `1.5` | Jeda antar-request HTTP dalam detik (minimal `1.5`) |
| `TOPIK_AKTIF` | 8 topik | `NATION,WORLD,BUSINESS,TECHNOLOGY,ENTERTAINMENT,SPORTS,SCIENCE,HEALTH` |
| `MEDIA_BACKFILL` | 4 media | Pilihan: `detik.com,cnnindonesia.com,cnbcindonesia.com,viva.co.id` |

## Penggunaan

### CLI (`scraping.py`)

```bash
# Jalankan scrape feed utama + semua topik aktif
python scraping.py

# Ambil satu atau beberapa topik tertentu
python scraping.py --topik teknologi
python scraping.py --topik bisnis --topik nasional

# Cari keyword pada berita baru maupun seluruh arsip database
python scraping.py --keyword "banjir jogja"

# Simpan keyword ke database agar ikut dipantau pada jadwal otomatis
python scraping.py --keyword "ekonomi digital" --simpan-keyword

# Jalankan scrape lengkap (utama + topik + seluruh keyword aktif)
python scraping.py --semua

# Backfill berita hari-hari sebelumnya dari news sitemap
python scraping.py --backfill 7
python scraping.py --backfill 7 --keyword "ikn"
python scraping.py --sejak 2026-11-01

# Tampilkan berita terbaru, buat laporan, atau ekspor CSV
python scraping.py --tampilkan 10
python scraping.py --laporan
python scraping.py --ekspor csv

# Mode scheduler bawaan (berjalan terus sesuai interval .env)
python scraping.py --jadwal

# Utilitas pemeliharaan
python scraping.py --simpan-mentah              # simpan XML mentah ke tests/fixtures/mentah/
python scraping.py --init-db                    # inisialisasi skema database
python scraping.py --hapus-sebelum 2026-11-14   # hapus artikel sebelum tanggal tertentu
```

Exit code CLI: `0` sukses, `1` sebagian berhasil, `2` gagal total.

#### Pencocokan Keyword & Backfill

- **Pencocokan Keyword**: Keyword dicocokkan secara lokal terhadap judul dan cuplikan deskripsi (case-insensitive, seluruh kata keyword harus muncul sebagai kata utuh). Pencarian lewat `--keyword` atau `/cari` juga langsung menyisir seluruh riwayat di SQLite.
- **Backfill Historis**: Mengambil arsip dari news sitemap resmi media untuk rentang tanggal yang diminta. Karena news sitemap media umumnya hanya menyimpan berita 2–4 hari terakhir, kedalaman backfill bergantung pada ketersediaan masing-masing media.

### Bot Telegram (`bot.py`)

```bash
python bot.py
```

Selain melayani perintah interaktif, `bot.py` menjalankan penjadwalan otomatis (scrape berkala sesuai `SCRAPE_SETIAP_JAM`, pengiriman notifikasi keyword untuk artikel ≤ 48 jam terakhir tanpa duplikasi, serta pengiriman laporan harian pada `JAM_LAPORAN`). Hindari menjalankan `bot.py` dan `scraping.py --jadwal` secara bersamaan pada database yang sama.

| Perintah | Deskripsi |
| --- | --- |
| `/start`, `/bantuan` | Sapaan, panduan singkat, dan atribusi sumber data |
| `/hariini` | 10 berita utama terbaru |
| `/topik [nama]` | 10 berita terbaru untuk topik tertentu (menampilkan tombol pilihan jika tanpa argumen) |
| `/trending` | 10 kata/isu yang sedang naik beserta ringkasan temuan |
| `/cari <keyword>` | Pencarian instan keyword di seluruh arsip database |
| `/pantau <keyword>` | Tambahkan keyword ke daftar pantauan notifikasi otomatis |
| `/berhenti_pantau <keyword>` | Hapus keyword dari daftar pantauan |
| `/pantauanku` | Daftar keyword yang sedang dipantau beserta jumlah artikel 24 jam terakhir |
| `/media` | 10 media paling aktif dalam 7 hari terakhir |
| `/grafik` | Kirim grafik tren topik dan wordcloud terbaru |
| `/laporan` | Kirim file laporan PDF terbaru |
| `/langganan`, `/stop` | Aktifkan atau hentikan laporan harian otomatis |
| `/status` | Informasi waktu scrape terakhir, status, dan total artikel tersimpan |
| `/perbarui` | *(Khusus admin)* Jalankan pipeline scrape secara manual |

### Dashboard Streamlit

```bash
streamlit run dashboard/app.py
```

Dashboard menyediakan filter rentang tanggal, topik, media, dan pencarian judul pada sidebar, serta tab **Tren**, **Media**, **Trending** (grafik batang + wordcloud), **Keyword**, dan **Data** (tabel + unduh CSV).

### Penjadwalan Otomatis (Opsional)

Jika memilih menjalankan `scraping.py` melalui scheduler sistem operasi alih-alih `bot.py` atau `scraping.py --jadwal`:

**Windows (Task Scheduler):**

```cmd
schtasks /Create /TN "PantauBerita" /SC HOURLY /MO 3 /ST 06:00 /TR "\"C:\path\to\pantauberita\.venv\Scripts\python.exe\" \"C:\path\to\pantauberita\scraping.py\" --semua"
schtasks /Create /TN "PantauBerita Laporan" /SC DAILY /ST 07:00 /TR "\"C:\path\to\pantauberita\.venv\Scripts\python.exe\" \"C:\path\to\pantauberita\scraping.py\" --laporan"
```

**Linux / macOS (`crontab -e`, asumsi zona waktu server WIB):**

```cron
0 6-23/3,0,3 * * * cd /path/to/pantauberita && .venv/bin/python scraping.py --semua >> logs/cron.log 2>&1
0 7 * * *          cd /path/to/pantauberita && .venv/bin/python scraping.py --laporan >> logs/cron.log 2>&1
```

## Pengujian

Seluruh pengujian berjalan secara offline menggunakan fixture XML di `tests/fixtures/` dan database SQLite sementara:

```bash
python -m pytest -q
```

## Atribusi

Sumber berita berasal dari RSS dan news sitemap resmi masing-masing media (detikcom, CNN Indonesia, CNBC Indonesia, VIVA, ANTARA, Republika, JPNN). Seluruh hak cipta konten dan artikel tetap dimiliki oleh masing-masing penerbit media terkait.
