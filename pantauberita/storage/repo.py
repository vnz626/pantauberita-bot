"""Akses database SQLite. SEMUA query SQL proyek ada di modul ini dan memakai parameter (?)."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Sequence
from datetime import date, datetime
from pathlib import Path
from types import TracebackType
from typing import Any

import pandas as pd

from pantauberita.config import WIB
from pantauberita.parser.rss import Artikel

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
KOLOM_DF = ["id", "judul", "media", "domain", "link", "terbit", "sentimen", "feed"]


def sekarang() -> str:
    """Waktu sekarang WIB, ISO 8601 (detik)."""
    return datetime.now(WIB).isoformat(timespec="seconds")


def _iso(waktu: datetime) -> str:
    return waktu.astimezone(WIB).isoformat(timespec="seconds")


class Repo:
    """Pembungkus koneksi SQLite (skema otomatis dibuat). Pakai sebagai context manager."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path) if str(db_path) != ":memory:" else db_path
        if isinstance(self.db_path, Path):
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path), timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.init_db()

    def __enter__(self) -> Repo:
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        self.close()

    def close(self) -> None:
        self.conn.close()

    def _semua(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    # ------------------------------------------------------------------ skema
    def init_db(self) -> None:
        """Buat semua tabel (idempoten)."""
        self.conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        kolom = {r["name"] for r in self.conn.execute("PRAGMA table_info(keyword)")}
        if "dari_cli" not in kolom:  # migrasi DB lama
            self.conn.execute("ALTER TABLE keyword ADD COLUMN dari_cli INTEGER NOT NULL DEFAULT 0")
        self.conn.commit()

    def tabel(self) -> list[str]:
        return [r["name"] for r in self.conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]

    # ------------------------------------------------------------------ run
    def mulai_run(self, mode: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO scrape_run (mulai, mode, status) VALUES (?, ?, 'berjalan')", (sekarang(), mode)
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def selesai_run(
        self, run_id: int, status: str, jumlah_feed: int, artikel_baru: int, pesan_error: str | None = None
    ) -> None:
        self.conn.execute(
            "UPDATE scrape_run SET selesai = ?, status = ?, jumlah_feed = ?, artikel_baru = ?, pesan_error = ? "
            "WHERE id = ?",
            (sekarang(), status, jumlah_feed, artikel_baru, pesan_error, run_id),
        )
        self.conn.commit()

    def ambil_run(self, run_id: int) -> dict[str, Any] | None:
        rows = self._semua("SELECT * FROM scrape_run WHERE id = ?", (run_id,))
        return rows[0] if rows else None

    def run_terakhir(self, mode: str | None = None) -> dict[str, Any] | None:
        if mode:
            rows = self._semua("SELECT * FROM scrape_run WHERE mode = ? ORDER BY id DESC LIMIT 1", (mode,))
        else:
            rows = self._semua("SELECT * FROM scrape_run ORDER BY id DESC LIMIT 1")
        return rows[0] if rows else None

    def ringkasan_backfill(self) -> list[dict[str, Any]]:
        """Per run backfill: tanggal run dan rentang tanggal terbit artikel yang diambil."""
        return self._semua(
            "SELECT r.id, r.mulai, MIN(substr(a.terbit, 1, 10)) AS dari, MAX(substr(a.terbit, 1, 10)) AS sampai, "
            "COUNT(DISTINCT a.id) AS jumlah "
            "FROM scrape_run r JOIN kemunculan k ON k.run_id = r.id JOIN artikel a ON a.id = k.artikel_id "
            "WHERE r.mode = 'backfill' GROUP BY r.id ORDER BY r.id"
        )

    # ------------------------------------------------------------------ artikel
    def simpan_feed(
        self, run_id: int, feed: str, artikel: Sequence[Artikel], sentimen: Sequence[float] | None = None
    ) -> int:
        """Simpan artikel satu feed + catat kemunculannya. Kembalikan jumlah artikel baru."""
        if sentimen is not None and len(sentimen) != len(artikel):
            raise ValueError("Panjang sentimen harus sama dengan artikel")
        baru = 0
        waktu = sekarang()
        with self.conn:
            for i, a in enumerate(artikel):
                cur = self.conn.execute(
                    "INSERT INTO artikel (id, judul, media, domain, link, terbit, ringkasan, sentimen, pertama_dilihat) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO NOTHING",
                    (
                        a.id,
                        a.judul,
                        a.media,
                        a.domain,
                        a.link,
                        _iso(a.terbit),
                        a.ringkasan,
                        None if sentimen is None else float(sentimen[i]),
                        waktu,
                    ),
                )
                baru += cur.rowcount
                self.conn.execute(
                    "INSERT OR IGNORE INTO kemunculan (artikel_id, feed, run_id, peringkat) VALUES (?, ?, ?, ?)",
                    (a.id, feed, run_id, i + 1),
                )
        return baru

    def tandai_keyword(self, run_id: int, keyword: str, artikel_ids: Iterable[str]) -> int:
        """Catat kemunculan artikel di feed 'keyword:{keyword}'. Kembalikan jumlah baris baru."""
        feed = f"keyword:{keyword}"
        baru = 0
        with self.conn:
            for aid in artikel_ids:
                cur = self.conn.execute(
                    "INSERT OR IGNORE INTO kemunculan (artikel_id, feed, run_id, peringkat) VALUES (?, ?, ?, NULL)",
                    (aid, feed, run_id),
                )
                baru += cur.rowcount
        return baru

    def artikel_untuk_pencarian(
        self, sejak: date | None = None, ids: Sequence[str] | None = None
    ) -> list[dict[str, Any]]:
        """Kolom id, judul, ringkasan, terbit untuk pencocokan keyword (seluruh riwayat atau id tertentu)."""
        if ids is not None:
            hasil: list[dict[str, Any]] = []
            daftar = list(ids)
            for i in range(0, len(daftar), 500):
                potong = daftar[i : i + 500]
                tanda = ",".join("?" * len(potong))
                hasil += self._semua(
                    f"SELECT id, judul, ringkasan, terbit FROM artikel WHERE id IN ({tanda})", potong
                )
            return hasil
        if sejak is not None:
            return self._semua(
                "SELECT id, judul, ringkasan, terbit FROM artikel WHERE substr(terbit, 1, 10) >= ?",
                (sejak.isoformat(),),
            )
        return self._semua("SELECT id, judul, ringkasan, terbit FROM artikel")

    def kemunculan_dengan_prefix(self, prefix: str) -> list[dict[str, Any]]:
        """Kemunculan yang feed-nya diawali `prefix`, beserta link artikelnya."""
        return self._semua(
            "SELECT k.artikel_id, k.feed, k.run_id, a.link FROM kemunculan k JOIN artikel a ON a.id = k.artikel_id "
            "WHERE k.feed LIKE ? ESCAPE '\\'",
            (_escape_like(prefix) + "%",),
        )

    def ganti_label_kemunculan(self, artikel_id: str, feed_lama: str, run_id: int, feed_baru: str) -> None:
        """Ganti label feed satu kemunculan (abaikan jika label baru sudah ada untuk run itu)."""
        with self.conn:
            self.conn.execute(
                "UPDATE OR IGNORE kemunculan SET feed = ? WHERE artikel_id = ? AND feed = ? AND run_id = ?",
                (feed_baru, artikel_id, feed_lama, run_id),
            )
            self.conn.execute(
                "DELETE FROM kemunculan WHERE artikel_id = ? AND feed = ? AND run_id = ?",
                (artikel_id, feed_lama, run_id),
            )

    def hapus_artikel_sebelum(self, tanggal: date) -> int:
        """Hapus artikel yang terbit sebelum `tanggal` (WIB) beserta kemunculan & catatan notifikasinya."""
        batas = tanggal.isoformat()
        with self.conn:
            self.conn.execute(
                "DELETE FROM kemunculan WHERE artikel_id IN (SELECT id FROM artikel WHERE substr(terbit, 1, 10) < ?)",
                (batas,),
            )
            self.conn.execute(
                "DELETE FROM notifikasi_terkirim WHERE artikel_id IN "
                "(SELECT id FROM artikel WHERE substr(terbit, 1, 10) < ?)",
                (batas,),
            )
            cur = self.conn.execute("DELETE FROM artikel WHERE substr(terbit, 1, 10) < ?", (batas,))
        self.conn.execute("VACUUM")
        return cur.rowcount

    def jumlah_artikel(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM artikel").fetchone()[0])

    def jumlah_kemunculan(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM kemunculan").fetchone()[0])

    def daftar_feed(self) -> list[str]:
        return [r["feed"] for r in self.conn.execute("SELECT DISTINCT feed FROM kemunculan ORDER BY feed")]

    def artikel_terbaru(self, feed: str | None = None, limit: int = 10, prefix: bool = False) -> list[dict[str, Any]]:
        """Artikel terbaru (urut terbit) dari satu feed, prefix feed, atau semua."""
        if feed is None:
            return self._semua("SELECT * FROM artikel ORDER BY terbit DESC LIMIT ?", (limit,))
        kondisi = "k.feed LIKE ? ESCAPE '\\'" if prefix else "k.feed = ?"
        nilai = _escape_like(feed) + "%" if prefix else feed
        return self._semua(
            "SELECT a.* FROM artikel a WHERE a.id IN "
            f"(SELECT k.artikel_id FROM kemunculan k WHERE {kondisi}) "
            "ORDER BY a.terbit DESC LIMIT ?",
            (nilai, limit),
        )

    def artikel_run_feed(self, run_id: int, feed: str, limit: int = 10) -> list[dict[str, Any]]:
        """Artikel satu feed pada satu run, urut peringkat."""
        return self._semua(
            "SELECT a.*, k.peringkat FROM kemunculan k JOIN artikel a ON a.id = k.artikel_id "
            "WHERE k.run_id = ? AND k.feed = ? ORDER BY k.peringkat LIMIT ?",
            (run_id, feed, limit),
        )

    def artikel_df(self, sejak: date | None = None) -> pd.DataFrame:
        """Satu baris per pasangan (artikel, feed). `terbit` masih string ISO."""
        sql = (
            "SELECT a.id, a.judul, a.media, a.domain, a.link, a.terbit, a.sentimen, k.feed "
            "FROM artikel a JOIN (SELECT DISTINCT artikel_id, feed FROM kemunculan) k ON k.artikel_id = a.id"
        )
        params: tuple[Any, ...] = ()
        if sejak is not None:
            sql += " WHERE substr(a.terbit, 1, 10) >= ?"
            params = (sejak.isoformat(),)
        rows = self._semua(sql, params)
        return pd.DataFrame(rows, columns=KOLOM_DF)

    def ekspor_artikel_df(self) -> pd.DataFrame:
        """Seluruh tabel artikel + daftar feed (dipisah ';')."""
        rows = self._semua(
            "SELECT a.id, a.judul, a.media, a.domain, a.link, a.terbit, a.ringkasan, a.sentimen, a.pertama_dilihat, "
            "(SELECT group_concat(feed, ';') FROM (SELECT DISTINCT feed FROM kemunculan k WHERE k.artikel_id = a.id)) "
            "AS feed FROM artikel a ORDER BY a.terbit DESC"
        )
        kolom = ["id", "judul", "media", "domain", "link", "terbit", "ringkasan", "sentimen", "pertama_dilihat", "feed"]
        return pd.DataFrame(rows, columns=kolom)

    # ------------------------------------------------------------------ keyword
    def tambah_keyword(self, teks: str, aktif: bool = True, dari_cli: bool = False) -> None:
        """Tambah keyword (sudah dinormalisasi). Keyword lama: aktif/dari_cli hanya bisa dinaikkan."""
        with self.conn:
            self.conn.execute(
                "INSERT INTO keyword (teks, aktif, dibuat_pada, dari_cli) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(teks) DO UPDATE SET aktif = MAX(aktif, excluded.aktif), "
                "dari_cli = MAX(dari_cli, excluded.dari_cli)",
                (teks, int(aktif), sekarang(), int(dari_cli)),
            )

    def keyword_aktif(self) -> list[str]:
        return [r["teks"] for r in self.conn.execute("SELECT teks FROM keyword WHERE aktif = 1 ORDER BY teks")]

    def semua_keyword(self) -> list[dict[str, Any]]:
        return self._semua("SELECT * FROM keyword ORDER BY teks")

    def rapikan_keyword(self) -> int:
        """Nonaktifkan keyword yang tidak dipantau siapa pun dan bukan dari --simpan-keyword."""
        with self.conn:
            cur = self.conn.execute(
                "UPDATE keyword SET aktif = 0 WHERE aktif = 1 AND dari_cli = 0 "
                "AND teks NOT IN (SELECT keyword FROM pantauan)"
            )
        return cur.rowcount

    def jumlah_artikel_feed_sejak(self, feed: str, sejak: datetime) -> int:
        row = self.conn.execute(
            "SELECT COUNT(DISTINCT a.id) FROM artikel a JOIN kemunculan k ON k.artikel_id = a.id "
            "WHERE k.feed = ? AND a.terbit >= ?",
            (feed, _iso(sejak)),
        ).fetchone()
        return int(row[0])

    # ------------------------------------------------------------------ pengguna
    def daftar_pengguna(self, chat_id: int, nama: str | None) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO pengguna (chat_id, nama, dibuat_pada) VALUES (?, ?, ?) "
                "ON CONFLICT(chat_id) DO UPDATE SET nama = excluded.nama",
                (chat_id, nama, sekarang()),
            )

    def set_langganan(self, chat_id: int, aktif: bool) -> None:
        with self.conn:
            self.conn.execute("UPDATE pengguna SET laporan_harian = ? WHERE chat_id = ?", (int(aktif), chat_id))

    def pelanggan_laporan(self) -> list[int]:
        return [r["chat_id"] for r in self.conn.execute("SELECT chat_id FROM pengguna WHERE laporan_harian = 1")]

    def tambah_pantauan(self, chat_id: int, keyword: str) -> bool:
        """Tambah pantauan; False bila sudah ada."""
        self.tambah_keyword(keyword, aktif=True)
        with self.conn:
            cur = self.conn.execute(
                "INSERT OR IGNORE INTO pantauan (chat_id, keyword) VALUES (?, ?)", (chat_id, keyword)
            )
        return cur.rowcount == 1

    def hapus_pantauan(self, chat_id: int, keyword: str) -> bool:
        with self.conn:
            cur = self.conn.execute("DELETE FROM pantauan WHERE chat_id = ? AND keyword = ?", (chat_id, keyword))
        self.rapikan_keyword()
        return cur.rowcount == 1

    def pantauan_pengguna(self, chat_id: int) -> list[str]:
        return [
            r["keyword"]
            for r in self.conn.execute("SELECT keyword FROM pantauan WHERE chat_id = ? ORDER BY keyword", (chat_id,))
        ]

    def semua_pantauan(self) -> list[tuple[int, str]]:
        return [
            (r["chat_id"], r["keyword"])
            for r in self.conn.execute("SELECT chat_id, keyword FROM pantauan ORDER BY chat_id, keyword")
        ]

    def nonaktifkan_pengguna(self, chat_id: int) -> None:
        """Pengguna memblokir bot: matikan laporan harian dan hapus pantauannya."""
        with self.conn:
            self.conn.execute("UPDATE pengguna SET laporan_harian = 0 WHERE chat_id = ?", (chat_id,))
            self.conn.execute("DELETE FROM pantauan WHERE chat_id = ?", (chat_id,))
        self.rapikan_keyword()

    # ------------------------------------------------------------------ notifikasi
    def artikel_belum_dinotifikasi(
        self, chat_id: int, keyword: str, run_id: int, sejak: datetime | None = None
    ) -> list[dict[str, Any]]:
        """Artikel feed keyword pada run ini (terbit >= sejak) yang belum pernah dikirim ke chat_id."""
        batas = _iso(sejak) if sejak is not None else ""
        return self._semua(
            "SELECT a.*, k.peringkat FROM kemunculan k JOIN artikel a ON a.id = k.artikel_id "
            "WHERE k.run_id = ? AND k.feed = ? AND a.terbit >= ? AND a.id NOT IN "
            "(SELECT artikel_id FROM notifikasi_terkirim WHERE chat_id = ?) ORDER BY a.terbit DESC",
            (run_id, f"keyword:{keyword}", batas, chat_id),
        )

    def tandai_terkirim(self, chat_id: int, artikel_ids: Iterable[str]) -> None:
        waktu = sekarang()
        with self.conn:
            self.conn.executemany(
                "INSERT OR IGNORE INTO notifikasi_terkirim (chat_id, artikel_id, dikirim_pada) VALUES (?, ?, ?)",
                [(chat_id, aid, waktu) for aid in artikel_ids],
            )


def _escape_like(teks: str) -> str:
    return teks.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
