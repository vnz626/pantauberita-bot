CREATE TABLE IF NOT EXISTS artikel (
    id            TEXT PRIMARY KEY,
    judul         TEXT NOT NULL,
    media         TEXT NOT NULL,
    domain        TEXT,
    link          TEXT NOT NULL,
    terbit        TEXT NOT NULL,          -- ISO 8601 WIB
    ringkasan     TEXT,
    sentimen      REAL,                   -- -1..1, dihitung saat simpan
    pertama_dilihat TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_artikel_terbit ON artikel(terbit);
CREATE INDEX IF NOT EXISTS ix_artikel_media  ON artikel(media);

CREATE TABLE IF NOT EXISTS scrape_run (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    mulai         TEXT NOT NULL,
    selesai       TEXT,
    mode          TEXT NOT NULL,          -- 'manual' | 'jadwal' | 'bot' | 'backfill'
    status        TEXT NOT NULL,          -- 'berjalan' | 'sukses' | 'sebagian' | 'gagal'
    jumlah_feed   INTEGER DEFAULT 0,
    artikel_baru  INTEGER DEFAULT 0,
    pesan_error   TEXT
);

-- Satu artikel bisa muncul di banyak feed (utama, topik, keyword)
CREATE TABLE IF NOT EXISTS kemunculan (
    artikel_id  TEXT NOT NULL REFERENCES artikel(id),
    feed        TEXT NOT NULL,            -- 'utama' | 'topik:teknologi' | 'keyword:banjir jogja'
    run_id      INTEGER NOT NULL REFERENCES scrape_run(id),
    peringkat   INTEGER,                  -- urutan di feed (1 = teratas)
    PRIMARY KEY (artikel_id, feed, run_id)
);
CREATE INDEX IF NOT EXISTS ix_kemunculan_feed ON kemunculan(feed);
CREATE INDEX IF NOT EXISTS ix_kemunculan_run  ON kemunculan(run_id);

CREATE TABLE IF NOT EXISTS keyword (
    teks          TEXT PRIMARY KEY,       -- dinormalisasi: lowercase, spasi tunggal
    aktif         INTEGER NOT NULL DEFAULT 1,
    dibuat_pada   TEXT NOT NULL,
    dari_cli      INTEGER NOT NULL DEFAULT 0  -- 1 jika disimpan via --simpan-keyword (tidak dinonaktifkan otomatis)
);

CREATE TABLE IF NOT EXISTS pengguna (
    chat_id         INTEGER PRIMARY KEY,
    nama            TEXT,
    laporan_harian  INTEGER NOT NULL DEFAULT 0,
    dibuat_pada     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pantauan (
    chat_id   INTEGER NOT NULL REFERENCES pengguna(chat_id),
    keyword   TEXT NOT NULL REFERENCES keyword(teks),
    PRIMARY KEY (chat_id, keyword)
);

-- Mencegah notifikasi artikel yang sama dikirim dua kali
CREATE TABLE IF NOT EXISTS notifikasi_terkirim (
    chat_id     INTEGER NOT NULL,
    artikel_id  TEXT NOT NULL,
    dikirim_pada TEXT NOT NULL,
    PRIMARY KEY (chat_id, artikel_id)
);
