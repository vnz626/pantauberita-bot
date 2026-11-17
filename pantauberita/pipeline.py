"""Orkestrasi satu kali jalan. `run`, `run_backfill`, dan `cari_lokal` dipakai oleh CLI, jadwal, dan bot."""

from __future__ import annotations

import logging
import re
import time
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Protocol

from pantauberita.analysis.text import cocok_keyword, sentimen
from pantauberita.collector.feeds import (
    SITEMAP_BACKFILL,
    Feed,
    bangun_feeds,
    bangun_feeds_backfill,
    daftar_tanggal_backfill,
    label_dari_url,
    normalisasi_keyword,
)
from pantauberita.collector.http import HttpClient
from pantauberita.config import FIXTURE_DIR, WIB, Config
from pantauberita.parser.rss import Artikel, parse_feed, parse_sitemap
from pantauberita.storage.repo import Repo

log = logging.getLogger(__name__)

EXIT_CODE = {"sukses": 0, "sebagian": 1, "gagal": 2}
FOLDER_MENTAH = FIXTURE_DIR / "mentah"


class Pengambil(Protocol):
    """Antarmuka minimal klien HTTP (memudahkan tes tanpa internet)."""

    def ambil(self, url: str) -> bytes: ...

    def cek_robots(self, urls: Sequence[str]) -> dict[str, bool]: ...


@dataclass(frozen=True)
class HasilFeed:
    feed: str
    media: str
    diambil: int
    baru: int
    error: str | None = None


@dataclass
class HasilRun:
    run_id: int
    mode: str
    status: str
    feeds: list[HasilFeed] = field(default_factory=list)
    keyword: dict[str, int] = field(default_factory=dict)  # keyword -> jumlah artikel cocok (run ini + riwayat)
    cakupan: dict[date, int] = field(default_factory=dict)  # backfill: tanggal -> jumlah artikel
    durasi: float = 0.0
    pesan_error: str | None = None

    @property
    def artikel_baru(self) -> int:
        return sum(f.baru for f in self.feeds)

    @property
    def exit_code(self) -> int:
        return EXIT_CODE.get(self.status, 2)


def tentukan_status(jumlah_feed: int, jumlah_gagal: int) -> str:
    """sukses jika tidak ada yang gagal, gagal jika semua gagal, selain itu sebagian."""
    if jumlah_gagal == 0:
        return "sukses"
    if jumlah_gagal >= jumlah_feed:
        return "gagal"
    return "sebagian"


def saring_rentang(artikel: list[Artikel], rentang: tuple[date, date] | None) -> list[Artikel]:
    """Untuk backfill: buang item yang tanggal terbit (WIB) di luar rentang."""
    if rentang is None:
        return artikel
    awal, akhir = rentang
    return [a for a in artikel if awal <= a.terbit.astimezone(WIB).date() <= akhir]


def kelompokkan_label(artikel: Iterable[Artikel]) -> dict[str, list[Artikel]]:
    """Fungsi murni: kelompokkan artikel sitemap per label topik dari URL (urutan dipertahankan)."""
    hasil: dict[str, list[Artikel]] = {}
    for a in artikel:
        hasil.setdefault(label_dari_url(a.link), []).append(a)
    return hasil


def cocokkan(baris: Iterable[dict[str, Any]], keyword: str) -> list[str]:
    """Fungsi murni: id artikel yang judul/ringkasannya memuat semua kata keyword."""
    return [b["id"] for b in baris if cocok_keyword(f"{b.get('judul') or ''} {b.get('ringkasan') or ''}", keyword)]


def _nama_file(feed: Feed) -> str:
    dasar = re.sub(r"[^a-zA-Z0-9]+", "_", f"{feed.label}_{feed.media}").strip("_").lower()
    return f"{feed.jenis}_{dasar}.xml"


def _jalankan(
    repo: Repo,
    client: Pengambil,
    run_id: int,
    feeds: list[Feed],
    simpan_mentah: Path | None = None,
    hanya_cocok: Sequence[str] | None = None,
) -> tuple[list[HasilFeed], list[str], list[Artikel]]:
    """Ambil + simpan semua feed. Kembalikan (hasil per feed, daftar error, artikel yang disimpan)."""
    izin = client.cek_robots([f.url for f in feeds]) if feeds else {}
    hasil: list[HasilFeed] = []
    error: list[str] = []
    tersimpan: list[Artikel] = []
    for feed in feeds:
        if not izin.get(feed.url, True):
            pesan = "diblokir robots.txt"
            error.append(f"{feed.label} ({feed.media}): {pesan}")
            hasil.append(HasilFeed(feed.label, feed.media, 0, 0, pesan))
            continue
        try:
            xml = client.ambil(feed.url)
            if simpan_mentah is not None:
                simpan_mentah.mkdir(parents=True, exist_ok=True)
                (simpan_mentah / _nama_file(feed)).write_bytes(xml)
            if feed.jenis == "sitemap":
                artikel = parse_sitemap(xml, feed.media)
            else:
                artikel = parse_feed(xml, feed.media)
            artikel = saring_rentang(artikel, feed.rentang)
            if hanya_cocok:
                artikel = [a for a in artikel if any(cocok_keyword(f"{a.judul} {a.ringkasan}", k) for k in hanya_cocok)]
            if feed.jenis == "sitemap":
                baru = 0
                for label, kelompok in kelompokkan_label(artikel).items():
                    baru += repo.simpan_feed(run_id, label, kelompok, [sentimen(a.judul) for a in kelompok])
            else:
                baru = repo.simpan_feed(run_id, feed.label, artikel, [sentimen(a.judul) for a in artikel])
            hasil.append(HasilFeed(feed.label, feed.media, len(artikel), baru))
            tersimpan += artikel
        except Exception as exc:  # satu feed gagal tidak menggagalkan feed lain
            log.warning("Feed %s (%s) gagal: %s", feed.label, feed.url, exc)
            error.append(f"{feed.label} ({feed.media}): {type(exc).__name__}: {exc}")
            hasil.append(HasilFeed(feed.label, feed.media, 0, 0, f"{type(exc).__name__}: {exc}"))
    return hasil, error, tersimpan


def _tandai_keywords(
    repo: Repo, run_id: int, artikel_run: list[Artikel], keyword_run: Iterable[str], keyword_riwayat: Iterable[str]
) -> dict[str, int]:
    """Tandai artikel cocok ke feed keyword:*.

    - `keyword_run`: dicocokkan dengan artikel yang diambil pada run ini.
    - `keyword_riwayat`: dicocokkan dengan SELURUH artikel di database (keyword baru dicari).
    """
    baris_run = [{"id": a.id, "judul": a.judul, "ringkasan": a.ringkasan} for a in artikel_run]
    riwayat = list(dict.fromkeys(keyword_riwayat))
    baris_db = repo.artikel_untuk_pencarian() if riwayat else []
    hasil: dict[str, int] = {}
    for kw in dict.fromkeys([*keyword_run, *riwayat]):
        ids = set(cocokkan(baris_run, kw))
        if kw in riwayat:
            ids |= set(cocokkan(baris_db, kw))
        repo.tandai_keyword(run_id, kw, sorted(ids))
        hasil[kw] = len(ids)
    return hasil


def _selesai(repo: Repo, hasil: HasilRun, jumlah_feed: int, error: list[str], mulai: float) -> HasilRun:
    hasil.status = tentukan_status(jumlah_feed, len(error)) if jumlah_feed else "sukses"
    hasil.pesan_error = "\n".join(error) or None
    repo.selesai_run(hasil.run_id, hasil.status, jumlah_feed, hasil.artikel_baru, hasil.pesan_error)
    hasil.durasi = time.monotonic() - mulai
    log.info("Run #%s (%s) selesai: %s, %d artikel baru", hasil.run_id, hasil.mode, hasil.status, hasil.artikel_baru)
    return hasil


def _client_bawaan(cfg: Config, client: Pengambil | None) -> Pengambil:
    return client if client is not None else HttpClient(jeda_detik=cfg.jeda_detik)


def run(
    cfg: Config,
    *,
    mode: str = "manual",
    semua: bool = False,
    topik: Sequence[str] | None = None,
    keywords: Sequence[str] | None = None,
    simpan_keyword: bool = False,
    simpan_mentah: bool = False,
    client: Pengambil | None = None,
    repo: Repo | None = None,
) -> HasilRun:
    """Satu kali scraping RSS.

    - default / `semua=True`: utama + semua topik aktif; keyword aktif dicocokkan pada artikel run ini.
    - `topik`: hanya feed topik tersebut.
    - `keywords`: dicari pada artikel yang diambil run ini DAN seluruh riwayat database.
    """
    tutup = repo is None
    repo = repo or Repo(cfg.db_path)
    try:
        mulai = time.monotonic()
        kw = list(dict.fromkeys(normalisasi_keyword(k) for k in (keywords or []) if k.strip()))
        for k in kw:
            repo.tambah_keyword(k, aktif=simpan_keyword, dari_cli=simpan_keyword)
        feeds = bangun_feeds(topik_aktif=cfg.topik_aktif, topik=None if semua else topik)
        run_id = repo.mulai_run(mode)
        hasil = HasilRun(run_id=run_id, mode=mode, status="berjalan")
        hasil.feeds, error, artikel = _jalankan(
            repo, _client_bawaan(cfg, client), run_id, feeds, FOLDER_MENTAH if simpan_mentah else None
        )
        hasil.keyword = _tandai_keywords(repo, run_id, artikel, repo.keyword_aktif(), kw)
        return _selesai(repo, hasil, len(feeds), error, mulai)
    finally:
        if tutup:
            repo.close()


def run_backfill(
    cfg: Config,
    *,
    hari: int | None = None,
    sejak: date | None = None,
    keywords: Sequence[str] | None = None,
    hari_ini: date | None = None,
    simpan_mentah: bool = False,
    client: Pengambil | None = None,
    repo: Repo | None = None,
) -> HasilRun:
    """Isi data hari-hari sebelumnya dari news sitemap resmi media (tanggal terbit asli).

    Tanpa `keywords`: semua artikel sitemap dalam rentang disimpan dengan label topik dari URL-nya
    ('topik:bisnis', dst.; 'utama' bila tak dikenali); keyword aktif ditandai.
    Dengan `keywords`: hanya artikel yang cocok dengan keyword itu yang disimpan.
    Kedalaman data bergantung pada sitemap tiap media (umumnya 2-4 hari terakhir).
    """
    hari_ini = hari_ini or datetime.now(WIB).date()
    tanggal = daftar_tanggal_backfill(hari_ini, hari=hari, sejak=sejak)
    tutup = repo is None
    repo = repo or Repo(cfg.db_path)
    try:
        mulai = time.monotonic()
        kw = list(dict.fromkeys(normalisasi_keyword(k) for k in (keywords or []) if k.strip()))
        for k in kw:
            repo.tambah_keyword(k, aktif=False)
        tak_dikenal = [d for d in cfg.media_backfill if d not in SITEMAP_BACKFILL]
        if tak_dikenal:
            log.warning(
                "MEDIA_BACKFILL berisi domain tanpa sitemap yang didukung (diabaikan): %s. Pilihan: %s",
                ", ".join(tak_dikenal), ", ".join(SITEMAP_BACKFILL),
            )
        feeds = bangun_feeds_backfill(tanggal, cfg.media_backfill)
        log.info("Backfill %s s.d. %s: %d sitemap", tanggal[0] if tanggal else "-", tanggal[-1] if tanggal else "-", len(feeds))
        run_id = repo.mulai_run("backfill")
        hasil = HasilRun(run_id=run_id, mode="backfill", status="berjalan")
        hasil.feeds, error, artikel = _jalankan(
            repo, _client_bawaan(cfg, client), run_id, feeds, FOLDER_MENTAH if simpan_mentah else None, kw or None
        )
        hasil.keyword = _tandai_keywords(repo, run_id, artikel, kw or repo.keyword_aktif(), [])
        per_hari = Counter(a.terbit.astimezone(WIB).date() for a in {a.id: a for a in artikel}.values())
        hasil.cakupan = {t: per_hari.get(t, 0) for t in tanggal}
        return _selesai(repo, hasil, len(feeds), error, mulai)
    finally:
        if tutup:
            repo.close()


def cari_lokal(cfg: Config, keyword: str, mode: str = "bot", repo: Repo | None = None) -> HasilRun:
    """Cari keyword di seluruh riwayat database tanpa request jaringan (untuk /cari)."""
    tutup = repo is None
    repo = repo or Repo(cfg.db_path)
    try:
        mulai = time.monotonic()
        kw = normalisasi_keyword(keyword)
        repo.tambah_keyword(kw, aktif=False)
        run_id = repo.mulai_run(mode)
        hasil = HasilRun(run_id=run_id, mode=mode, status="berjalan")
        hasil.keyword = _tandai_keywords(repo, run_id, [], [], [kw])
        return _selesai(repo, hasil, 0, [], mulai)
    finally:
        if tutup:
            repo.close()


def migrasi_label_backfill(repo: Repo) -> int:
    """Ubah kemunculan lama berlabel 'backfill:*' menjadi label topik dari URL artikel."""
    baris = repo.kemunculan_dengan_prefix("backfill:")
    for b in baris:
        repo.ganti_label_kemunculan(b["artikel_id"], b["feed"], b["run_id"], label_dari_url(b["link"]))
    return len(baris)
