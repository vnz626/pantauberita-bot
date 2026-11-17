# PantauBerita

Bot pemantau berita harian Indonesia dari **RSS dan news sitemap resmi media** (detikcom, CNN Indonesia, CNBC Indonesia, VIVA, ANTARA, Republika, JPNN). Bisa jalan **tanpa keyword** (berita utama + 8 topik) atau **dengan keyword** (memantau isu tertentu). Hasilnya disimpan sebagai riwayat di SQLite, dianalisis trennya, lalu disajikan lewat terminal, laporan Excel/PDF, bot Telegram, dan dashboard Streamlit.

> **Kenapa bukan Google News RSS?** Dokumen desain awal memakai Google News RSS. Namun pada 17 Nov 2026 `robots.txt` news.google.com melarang `/rss`, `/rss/headlines/...`, dan `/rss/search` untuk semua user-agent (`User-agent: * / Disallow: /`). Sesuai aturan etika proyek ("jika path diblokir, hentikan"), sumber diganti ke RSS/sitemap resmi media yang `robots.txt`-nya mengizinkan. Lihat [Keputusan teknis](#7-keputusan-teknis).

## 1. Arsitektur

```
   ┌────────────────────────────────────────────┐
   │ RSS resmi media (utama + topik)             │   ← run biasa / jadwal
   │ News sitemap resmi media (judul + tanggal)  │   ← backfill
   └──────────────────────┬─────────────────────┘
                          │ HTTP (requests, retry, jeda 1,5 dtk, cek robots.txt per host)
                          ▼
 scraping.py ──► collector ──► parser ──► storage (SQLite) ◄──┬── analysis ──► reports (Excel, PDF, PNG)
 (CLI)            feeds.py     rss.py       repo.py           │
                                                              ├── bot.py (Telegram + jadwal)
 Task Scheduler / cron ──► scraping.py                        └── dashboard/app.py (Streamlit)
```

- `pantauberita/pipeline.py` → `run(...)`, `run_backfill(...)`, dan `cari_lokal(...)` adalah satu-satunya orkestrasi; dipakai CLI, jadwal, dan bot.
- Idempoten: satu berita yang muncul di banyak feed / banyak kali jalan tetap **satu baris** di tabel `artikel` (ID = sha1 dari link yang dinormalisasi); setiap kemunculan dicatat di `kemunculan`.
- Satu feed gagal tidak menggagalkan feed lain (status run `sebagian`).

```
pantauberita/
├── scraping.py  bot.py  dashboard/app.py
├── pantauberita/
│   ├── config.py  logging_setup.py  pipeline.py  reports.py
│   ├── collector/  http.py (session, retry, jeda, robots)  feeds.py (daftar sumber & feed)
│   ├── parser/     rss.py (RSS / sitemap -> Artikel, murni)
│   ├── storage/    schema.sql  repo.py (SEMUA query SQL)
│   ├── analysis/   text.py  metrics.py (murni)  charts.py
│   └── telegram/   handlers.py  jobs.py  messages.py (murni)
├── data/  stopwords_id.txt  kata_positif.txt  kata_negatif.txt
└── tests/ fixtures/*.xml  test_*.py
```

## 2. Sumber data, etika, dan atribusi

Semua sumber dicek `robots.txt`-nya pada 17 Nov 2026: user-agent umum (`*`) diizinkan mengakses path RSS/sitemap di bawah ini. Daftar lengkap ada di `pantauberita/collector/feeds.py`.

| Feed | Sumber |
| --- | --- |
| `utama` | ANTARA (terkini), CNN Indonesia, detikNews, CNBC Indonesia, VIVA, Republika, JPNN |
| `topik:nasional` | CNN Indonesia nasional, detikNews berita, VIVA berita |
| `topik:dunia` | CNN Indonesia internasional, detikNews internasional, VIVA dunia |
| `topik:bisnis` | CNN Indonesia ekonomi, detikFinance, CNBC Indonesia market, VIVA bisnis |
| `topik:teknologi` | CNN Indonesia teknologi, detikInet, CNBC Indonesia tech, VIVA digital |
| `topik:hiburan` | CNN Indonesia hiburan, detikHot, VIVA showbiz |
| `topik:olahraga` | CNN Indonesia olahraga, detikSport, VIVA sport |
| `topik:sains` | detikEdu, ANTARA Warta Bumi (pendekatan: belum ada RSS "sains" murni yang aktif) |
| `topik:kesehatan` | detikHealth, CNN Indonesia gaya hidup |
| backfill → `topik:*` | news sitemap detik.com, cnnindonesia.com, cnbcindonesia.com, viva.co.id; topik ditebak dari URL artikel |

Etika:

- **Hanya metadata**: judul, media, waktu terbit, tautan, dan cuplikan `description` RSS (maks. 300 karakter). Halaman artikel **tidak** dibuka/diunduh.
- User-Agent jujur: `PantauBerita/1.0 (proyek kuliah)`; jeda ≥ 1,5 detik antar-request; retry 3× dengan exponential backoff untuk error jaringan/5xx/429; jadwal minimal tiap 3 jam. Satu kali jalan ≈ 31 feed RSS (± 1–2,5 menit).
- `robots.txt` dicek **per host** setiap kali jalan. Feed yang path-nya dilarang tidak diambil sama sekali dan ditandai `diblokir robots.txt`; jika semua dilarang, status run `gagal`.
- Atribusi "**Sumber: RSS & sitemap berita resmi media, hak cipta milik masing-masing media**" tercantum di terminal, bot, laporan, grafik, dan dashboard.

## 3. Instalasi

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# Mac/Linux
source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env          # Windows: copy .env.example .env
python scraping.py --init-db
```

Isi `.env` (hanya `BOT_TOKEN` dan `ADMIN_IDS` yang wajib untuk bot; `scraping.py` berjalan tanpa token).

| Variabel | Default | Keterangan |
| --- | --- | --- |
| `BOT_TOKEN` | – | token dari @BotFather |
| `ADMIN_IDS` | – | chat_id admin, pisahkan koma |
| `DB_PATH` | `data/berita.db` | lokasi database |
| `SCRAPE_SETIAP_JAM` | 3 | minimal 3 |
| `JAM_MULAI_SCRAPE` | 06:00 | jadwal pertama (WIB) |
| `JAM_LAPORAN` | 07:00 | laporan harian (WIB) |
| `JEDA_DETIK` | 1.5 | minimal 1,5 |
| `TOPIK_AKTIF` | 8 topik | `NATION,WORLD,BUSINESS,TECHNOLOGY,ENTERTAINMENT,SPORTS,SCIENCE,HEALTH` |
| `MEDIA_BACKFILL` | 4 media | pilihan: `detik.com,cnnindonesia.com,cnbcindonesia.com,viva.co.id` |

> Jika Anda menyalin `.env` dari versi lama (Google News), hapus baris `BAHASA`/`NEGARA` dan ganti `MEDIA_BACKFILL` dengan daftar di atas. Domain lain diabaikan dengan peringatan.

## 4. Cara menjalankan

### CLI (`scraping.py`)

```bash
python scraping.py                              # utama + semua topik; keyword aktif dicocokkan
python scraping.py --topik teknologi            # hanya satu topik (boleh diulang)
python scraping.py --keyword "banjir jogja"     # ambil semua feed lalu cari keyword (+ riwayat DB)
python scraping.py --keyword "UNY" --simpan-keyword   # simpan keyword ke DB agar ikut jadwal
python scraping.py --semua                      # utama + topik + semua keyword aktif (default jadwal)
python scraping.py --backfill 7                 # isi 7 hari ke belakang dari news sitemap media
python scraping.py --backfill 7 --keyword "UNY" # backfill, simpan hanya artikel yang cocok keyword
python scraping.py --sejak 2026-11-01           # backfill mulai tanggal tertentu sampai kemarin
python scraping.py --tampilkan 10               # cetak 10 berita terbaru per feed di terminal
python scraping.py --laporan                    # buat Excel + PDF + grafik dari data yang ada
python scraping.py --ekspor csv                 # ekspor tabel artikel ke output/artikel_YYYY-MM-DD.csv
python scraping.py --jadwal                     # jalan tiap SCRAPE_SETIAP_JAM jam + laporan harian
python scraping.py --simpan-mentah              # simpan XML mentah ke tests/fixtures/mentah/
python scraping.py --init-db                    # buat database kosong
python scraping.py --hapus-sebelum 2026-11-14   # hapus artikel yang terbit sebelum tanggal itu
```

Contoh keluaran nyata (17 Nov 2026, dipotong):

```
PantauBerita · 17 Nov 2026 23:56 WIB · mode manual
 Feed            │ Media          │ Diambil │ Baru
 utama           │ ANTARA         │      50 │   50
 utama           │ CNN Indonesia  │     100 │  100
 topik:teknologi │ detikInet      │     100 │  100
 keyword:harga beras │ (pencocokan) │     2 │    -
 ...
Selesai dalam 144 detik · 2422 artikel baru · status: sukses
Trending: penyadapan, polri, eko hadi, irjen, dasco, ...
```

Exit code: `0` sukses, `1` sebagian, `2` gagal total.

### Cara kerja keyword

RSS media tidak menyediakan pencarian, jadi keyword dicari dari artikel yang **sudah dikumpulkan**:

- Artikel cocok jika **semua kata** keyword muncul sebagai kata utuh di judul atau cuplikan (tidak peka huruf besar). Contoh: `banjir jogja` cocok dengan "Banjir Rendam Rumah di Sleman, Jogja".
- Setiap run, keyword aktif dicocokkan dengan artikel yang baru diambil → dicatat sebagai feed `keyword:{teks}`.
- Keyword yang diberikan lewat `--keyword` atau `/cari` juga dicari di **seluruh riwayat database**, sehingga langsung punya data historis.
- Keterbatasan: berita yang tidak masuk feed utama/topik mana pun tidak akan tertangkap; sinonim ("Yogyakarta" vs "Jogja") perlu dipantau sebagai keyword terpisah.

### Backfill (data asli hari-hari sebelumnya)

Data lampau diambil dari **news sitemap** resmi media (format standar Google News sitemap: `loc`, `news:title`, `news:publication_date`). Sitemap memang disediakan untuk crawler dan tercantum di `robots.txt` media.

- Hanya item dengan tanggal terbit (WIB) di dalam rentang yang disimpan. Artikel **tidak** diberi label khusus backfill: topiknya ditebak dari URL (subdomain/segmen path, mis. `finance.detik.com` → bisnis, `/berita/dunia/` → dunia, `/sport/` → olahraga) lalu disimpan sebagai `topik:*`; yang tidak dikenali masuk `utama`. Asal backfill tetap tercatat di `scrape_run.mode = 'backfill'`. Analisis memakai `artikel.terbit` (tanggal terbit asli).
- **Kedalaman terbatas**: news sitemap umumnya hanya memuat 2–4 hari terakhir. Hasil uji 17 Nov 2026 untuk `--backfill 7`: 13–16 Nov terisi (38–614 artikel/hari), 10–12 Nov kosong. CLI selalu mencetak cakupan per tanggal, jadi kekosongan terlihat jelas.
- Feed RSS biasa juga sering memuat berita beberapa hari ke belakang (mis. VIVA digital ±2 minggu), sehingga run pertama sudah mengisi beberapa hari sebelumnya.
- **Data hari-hari awal timpang.** RSS dan sitemap hanya menyimpan sejumlah artikel *terbaru* (RSS ±100, sitemap ±100–1000), bukan jumlah hari tertentu. Hari scraping pertama tertangkap hampir lengkap, sedangkan hari-hari sebelumnya hanya tertangkap ekornya. Contoh database 18 Nov: 14 Nov 335, 15 Nov 379, 16 Nov 802, 17 Nov 1.393 artikel. Hari berjalan (mis. 18 Nov dini hari) juga selalu terlihat turun karena belum selesai. Setelah jadwal tiap 3 jam berjalan beberapa hari, setiap hari tertangkap penuh dan grafik menjadi sebanding.
- Run backfill tercatat `mode = 'backfill'`, dan laporan PDF/Excel otomatis memuat catatan transparansi, mis. *"Data 13 Nov 2026 – 16 Nov 2026 diambil secara backfill pada 17 Nov 2026 dari news sitemap resmi media (tanggal terbit asli)."*

### Bot Telegram

```bash
python bot.py
```

Bot sekaligus menjalankan jadwal: scrape tiap `SCRAPE_SETIAP_JAM` jam mulai `JAM_MULAI_SCRAPE` (06:00, 09:00, …, 03:00 WIB), notifikasi keyword setelah tiap scrape, dan laporan harian pukul `JAM_LAPORAN`. Jangan menjalankan `bot.py` dan `scraping.py --jadwal` bersamaan (scraping jadi dobel).

### Dashboard

```bash
streamlit run dashboard/app.py
```

Sidebar: rentang tanggal, topik, media, keyword, cari judul. Metrik: total artikel, artikel hari ini, jumlah media, sentimen rata-rata. Tab: Tren, Media, Trending (bar + wordcloud), Keyword, Data (tabel + unduh CSV).

### Penjadwalan otomatis

**Windows – Task Scheduler** (tiap 3 jam mulai 06:00):

```bash
schtasks /Create /TN "PantauBerita" /SC HOURLY /MO 3 /ST 06:00 /TR "\"E:\Kuliah\Scripting\pantau-berita\.venv\Scripts\python.exe\" \"E:\Kuliah\Scripting\pantau-berita\scraping.py\" --semua"
```

```bash
schtasks /Create /TN "PantauBerita Laporan" /SC DAILY /ST 07:00 /TR "\"E:\Kuliah\Scripting\pantau-berita\.venv\Scripts\python.exe\" \"E:\Kuliah\Scripting\pantau-berita\scraping.py\" --laporan"
```

**Mac/Linux – cron** (`crontab -e`, zona waktu server diasumsikan WIB):

```
0 6-23/3,0,3 * * *  cd /path/pantauberita && .venv/bin/python scraping.py --semua >> logs/cron.log 2>&1
0 7 * * *           cd /path/pantauberita && .venv/bin/python scraping.py --laporan >> logs/cron.log 2>&1
```

## 5. Perintah bot

| Perintah | Fungsi |
| --- | --- |
| `/start`, `/bantuan` | sapaan, daftar perintah, sumber data |
| `/hariini` | 10 berita utama terbaru |
| `/topik <nama>` | 10 berita terbaru satu topik; tanpa argumen → tombol pilihan topik |
| `/trending` | 10 kata/isu trending + 3 temuan |
| `/cari <keyword>` | cari keyword di seluruh arsip (instan, tanpa request baru), simpan, tampilkan 10 terbaru |
| `/pantau <keyword>` | tambah keyword ke pantauan |
| `/berhenti_pantau <keyword>` | hapus pantauan |
| `/pantauanku` | daftar keyword + jumlah artikel 24 jam |
| `/media` | 10 media paling aktif 7 hari |
| `/grafik` | grafik topik + wordcloud |
| `/laporan` | PDF laporan terbaru |
| `/langganan`, `/stop` | laporan harian otomatis on/off |
| `/status` | waktu scrape terakhir, status, jumlah artikel |
| `/perbarui` | **admin saja**: jalankan pipeline sekarang |

Notifikasi keyword: hanya artikel yang terbit ≤ 48 jam terakhir, maks. 5 berita per keyword per kiriman (sisanya "+N berita lain"), tidak pernah dobel (tabel `notifikasi_terkirim`), dan diberi peringatan "Isu ini sedang ramai" bila jumlah hari ini ≥ 2× rata-rata 7 hari dan ≥ 5 artikel. Jika pengguna memblokir bot, langganan dan pantauannya dihapus otomatis.

## 6. Pertanyaan analisis dan contoh temuan

1. Topik apa yang paling banyak diberitakan dan bagaimana trennya selama 7/30 hari? → grafik garis per topik, sheet *Per Topik*.
2. Media mana yang paling produktif, dan apakah berbeda per topik? → `top_media`, sheet *Top Media*, tab Media (bisa difilter per topik).
3. Isu/kata apa yang sedang naik hari ini, dan bagaimana sentimen beritanya? → `kata_trending` (skor = (hari_ini+1)/(rata-rata 7 hari+1), minimal 3×), `sentimen_harian`.

Contoh temuan otomatis dari uji coba nyata 17 Nov 2026:

- Total 1170 berita terbit hari ini dari 13 media.
- Topik terbanyak hari ini: nasional (282 berita).
- Media paling aktif hari ini: CNN Indonesia (257 berita).
- Sentimen rata-rata judul berita cenderung netral (−0,02).

Catatan: "jumlah per media" mencerminkan berapa banyak berita yang masuk feed RSS yang dipantau, bukan total produksi media tersebut.

## 7. Keputusan teknis

- **Sumber diganti dari Google News RSS ke RSS + news sitemap resmi media** karena robots.txt Google News melarang `/rss`. GDELT DOC API sempat dicoba untuk keyword/backfill, tetapi terus membalas HTTP 429 sehingga tidak dipakai. Kompas, Tempo, Liputan6, Tribunnews, dan Suara tidak dipakai karena RSS-nya tidak tersedia, 403, atau 404 saat dicek.
- **robots.txt dicek per host** di awal setiap run (satu request per host). Path yang dilarang tidak diambil (status `sebagian`/`gagal`). Robots 404 → diizinkan; 401/403 → dianggap melarang; error jaringan → diizinkan + `WARNING`.
- **ID artikel** = sha1 dari link yang dinormalisasi (tanpa query `?utm_...`, fragment, dan `/` di akhir), supaya artikel yang sama dari RSS dan sitemap tetap satu baris.
- **Media** diambil dari nama sumber di daftar feed (mis. `detikInet`), atau `<source>` / judul channel bila ada; sufiks " - Media" / " | Media" di judul dihapus bila cocok dengan nama media.
- **Keyword** dicocokkan secara lokal (lihat *Cara kerja keyword*). Akibatnya `--keyword` tetap mengambil semua feed (sebagai ruang pencarian) dan `/cari` menjadi pencarian arsip yang instan. Ini menyimpang dari desain awal (feed pencarian Google News).
- **Backfill** memakai news sitemap per media (lihat di atas). `--backfill N --keyword X` hanya menyimpan artikel sitemap yang cocok dengan X.
- **Kolom tambahan `keyword.dari_cli`**: skema dokumen tidak punya cara membedakan keyword dari `--simpan-keyword`. Kolom ini (default 0) dipakai agar keyword CLI tidak dinonaktifkan otomatis. `--keyword` tanpa `--simpan-keyword` dan `/cari` mencatat keyword dengan `aktif = 0` (tidak ikut jadwal).
- **`--simpan-mentah`** menyimpan XML ke `tests/fixtures/mentah/` (bukan menimpa fixture sintetis), supaya tes tetap deterministik.
- **Tanggal analisis** memakai `artikel.terbit` (WIB), bukan waktu scrape. `terbit` disimpan ISO 8601 dengan offset `+07:00`.
- **Hitungan artikel** selalu unik per `artikel.id`; satu artikel di feed `utama` dan `topik:bisnis` dihitung sekali untuk total, tetapi tetap dihitung di topiknya.
- **Kata trending**: satu judul menyumbang paling banyak 1 untuk tiap kata/bigram; rata-rata 7 hari sebelumnya memperhitungkan hari tanpa data sebagai 0.
- **Sentimen**: kamus sederhana (±150 kata positif/negatif, disusun manual untuk konteks judul berita), dihitung dari judul saat artikel pertama disimpan. Tidak menangani negasi ("tidak aman"); keterbatasan ini disengaja agar tetap sederhana.
- **Waktu di pesan bot**: `14:20` jika terbit hari ini, `16 Nov 14:20` jika hari lain (agar tidak ambigu). Pesan dipotong supaya < 4096 karakter (batas Telegram).
- **Jadwal**: bot memakai `JobQueue.run_daily` untuk tiap slot jam (06:00, 09:00, …) zona `Asia/Jakarta`; `scraping.py --jadwal` memakai `schedule` dengan zona yang sama (butuh `pytz`). Laporan harian pukul 07:00 merangkum **hari sebelumnya**.
- **Pipeline di bot** dijalankan dengan `asyncio.to_thread` agar bot tetap responsif.
- **Repo** membuat skema otomatis saat dibuka (idempoten), mengaktifkan `foreign_keys` dan mode WAL agar bot & dashboard bisa membaca bersamaan.
- **XML rusak** dideteksi dari flag `bozo` feedparser (kecuali peringatan encoding yang tidak berbahaya) atau `ParseError` untuk sitemap → list kosong + log `ERROR`.

## 8. Pengujian

```bash
python -m pytest -q
```

78 tes, semuanya tanpa internet (fixture XML sintetis bergaya RSS media dan news sitemap di `tests/fixtures/`) dan tanpa Telegram; database dibuat di folder sementara. Cakupan: parser RSS & sitemap, daftar feed & backfill, robots per host, repo (deduplikasi, SQL injection), pencocokan keyword, teks & sentimen, metrik, format pesan, notifikasi tidak dobel, pipeline (status sebagian/gagal, robots diblokir, backfill), CLI (argparse, exit code), laporan Excel/PDF.

## 9. Pembagian peran anggota

| Nama | NIM | Peran |
| --- | --- | --- |
| | | |
| | | |
| | | |

## 10. Pernyataan penggunaan AI

Kode, tes, kamus kata, dan dokumentasi proyek ini disusun dengan bantuan asisten AI (Claude) berdasarkan dokumen desain tim. Tim bertanggung jawab meninjau, menguji, dan memahami seluruh kode sebelum dikumpulkan.

---

Sumber: RSS & sitemap berita resmi media; hak cipta milik masing-masing media.
