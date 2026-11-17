"""Entry point CLI PantauBerita.

Contoh:
    python scraping.py
    python scraping.py --keyword "banjir jogja"
    python scraping.py --backfill 7
    python scraping.py --laporan
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from pathlib import Path

from rich.console import Console
from rich.table import Table

from pantauberita import pipeline, reports
from pantauberita.analysis import metrics
from pantauberita.collector.feeds import kode_topik
from pantauberita.config import ATRIBUSI, TOPIK, WIB, Config, load_config
from pantauberita.logging_setup import setup_logging
from pantauberita.storage.repo import Repo

log = logging.getLogger("scraping")


def _tanggal(teks: str) -> date:
    try:
        return date.fromisoformat(teks)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"format tanggal harus YYYY-MM-DD: {teks!r}") from exc


def _topik(teks: str) -> str:
    try:
        return TOPIK[kode_topik(teks)]
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _positif(teks: str) -> int:
    n = int(teks)
    if n <= 0:
        raise argparse.ArgumentTypeError("harus bilangan bulat > 0")
    return n


def buat_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="scraping.py",
        description="PantauBerita: scraping metadata berita dari RSS & news sitemap resmi media Indonesia.",
        epilog=ATRIBUSI,
    )
    p.add_argument("--topik", action="append", type=_topik, metavar="NAMA",
                   help=f"hanya satu topik (boleh diulang): {', '.join(TOPIK.values())}")
    p.add_argument("--keyword", action="append", metavar="TEKS", help="cari keyword di artikel run ini + riwayat DB (boleh diulang)")
    p.add_argument("--simpan-keyword", action="store_true", help="simpan keyword ke DB agar ikut jadwal")
    p.add_argument("--semua", action="store_true", help="utama + topik + semua keyword aktif")
    bf = p.add_mutually_exclusive_group()
    bf.add_argument("--backfill", type=_positif, metavar="HARI", help="isi N hari ke belakang dari news sitemap media")
    bf.add_argument("--sejak", type=_tanggal, metavar="YYYY-MM-DD", help="backfill mulai tanggal ini s.d. kemarin")
    p.add_argument("--tampilkan", type=_positif, metavar="N", help="cetak N berita terbaru per feed")
    p.add_argument("--laporan", action="store_true", help="buat Excel + PDF + grafik")
    p.add_argument("--ekspor", choices=["csv"], help="ekspor tabel artikel")
    p.add_argument("--jadwal", action="store_true", help="jalan tiap SCRAPE_SETIAP_JAM jam + laporan harian")
    p.add_argument("--simpan-mentah", action="store_true", help="simpan XML mentah ke tests/fixtures/mentah/")
    p.add_argument("--init-db", action="store_true", help="buat database kosong")
    p.add_argument("--hapus-sebelum", type=_tanggal, metavar="YYYY-MM-DD",
                   help="hapus artikel yang terbit sebelum tanggal ini")
    return p


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    args = buat_parser().parse_args(argv)
    if args.simpan_keyword and not args.keyword:
        buat_parser().error("--simpan-keyword butuh --keyword")
    return args


def perlu_scrape(args: argparse.Namespace) -> bool:
    """Scrape dijalankan jika ada argumen scraping, atau jika tidak ada aksi lain sama sekali."""
    if args.jadwal or args.backfill or args.sejak:
        return False
    eksplisit = bool(args.topik or args.keyword or args.semua or args.simpan_mentah)
    aksi_lain = bool(args.tampilkan or args.laporan or args.ekspor or args.init_db or args.hapus_sebelum)
    return eksplisit or not aksi_lain


# ---------------------------------------------------------------------- tampilan
def tampilkan_hasil(console: Console, hasil: pipeline.HasilRun, cfg: Config) -> None:
    console.print(f"[bold]PantauBerita[/] · {datetime.now(WIB):%d %b %Y %H:%M} WIB · mode {hasil.mode}")
    tabel = Table(show_edge=False, header_style="bold")
    tabel.add_column("Feed")
    tabel.add_column("Media")
    tabel.add_column("Diambil", justify="right")
    tabel.add_column("Baru", justify="right")
    tabel.add_column("Keterangan")
    for f in hasil.feeds:
        tabel.add_row(f.feed, f.media, str(f.diambil), str(f.baru), f"[red]{f.error[:60]}[/]" if f.error else "")
    for kw, n in hasil.keyword.items():
        tabel.add_row(f"keyword:{kw}", "(pencocokan)", str(n), "-", "")
    if hasil.feeds or hasil.keyword:
        console.print(tabel)
    if hasil.cakupan:
        isi = ", ".join(f"{t:%d %b}: {n}" for t, n in hasil.cakupan.items())
        console.print(f"Cakupan backfill per tanggal terbit: {isi}")
        kosong = [t for t, n in hasil.cakupan.items() if n == 0]
        if kosong:
            console.print(
                f"[yellow]{len(kosong)} hari tanpa data[/]: sitemap media hanya memuat beberapa hari terakhir."
            )
    warna = {"sukses": "green", "sebagian": "yellow", "gagal": "red"}.get(hasil.status, "white")
    console.print(
        f"Selesai dalam {hasil.durasi:.0f} detik · {hasil.artikel_baru} artikel baru · "
        f"status: [{warna}]{hasil.status}[/]"
    )
    if hasil.mode != "backfill" and hasil.status != "gagal":
        with Repo(cfg.db_path) as repo:
            df = metrics.siapkan_df(repo.artikel_df(sejak=metrics.hari_ini() - timedelta(days=8)))
        tren = metrics.kata_trending(df, metrics.hari_ini(), n=8)
        if not tren.empty:
            console.print("Trending: " + ", ".join(tren["kata"]) + ", ...")


def tampilkan_terbaru(console: Console, cfg: Config, n: int) -> None:
    with Repo(cfg.db_path) as repo:
        repo.init_db()
        feeds = repo.daftar_feed()
        if not feeds:
            console.print("Belum ada data. Jalankan [bold]python scraping.py[/] dulu.")
            return
        for feed in feeds:
            tabel = Table(title=feed, title_justify="left", show_edge=False, header_style="bold")
            tabel.add_column("Terbit", no_wrap=True)
            tabel.add_column("Media", no_wrap=True)
            tabel.add_column("Judul")
            for a in repo.artikel_terbaru(feed, n):
                tabel.add_row(a["terbit"][:16].replace("T", " "), a["media"], a["judul"])
            console.print(tabel)
    console.print(f"[dim]{ATRIBUSI}[/]")


def ekspor_csv(cfg: Config) -> Path:
    with Repo(cfg.db_path) as repo:
        repo.init_db()
        df = repo.ekspor_artikel_df()
    path = cfg.output_dir / f"artikel_{datetime.now(WIB).date().isoformat()}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return path


def buat_laporan(console: Console, cfg: Config) -> None:
    hasil = reports.buat_laporan(cfg)
    console.print("Laporan dibuat:")
    for nama, path in hasil.items():
        console.print(f"  {nama:10s} {path}")


# ---------------------------------------------------------------------- jadwal
def jalankan_jadwal(console: Console, cfg: Config) -> int:
    """Loop `schedule`: scrape tiap N jam mulai JAM_MULAI_SCRAPE, laporan harian di JAM_LAPORAN (WIB)."""
    import schedule

    def tugas_scrape() -> None:
        try:
            tampilkan_hasil(console, pipeline.run(cfg, mode="jadwal", semua=True), cfg)
        except Exception:
            log.exception("Scrape terjadwal gagal")

    def tugas_laporan() -> None:
        try:
            buat_laporan(console, cfg)
        except Exception:
            log.exception("Laporan terjadwal gagal")

    for jam in jam_scrape(cfg):
        schedule.every().day.at(jam, "Asia/Jakarta").do(tugas_scrape)
    schedule.every().day.at(cfg.jam_laporan.strftime("%H:%M"), "Asia/Jakarta").do(tugas_laporan)
    console.print(
        f"Mode jadwal aktif: scrape pukul {', '.join(jam_scrape(cfg))} WIB, "
        f"laporan pukul {cfg.jam_laporan:%H:%M} WIB. Tekan Ctrl+C untuk berhenti."
    )
    try:
        while True:
            schedule.run_pending()
            time.sleep(30)
    except KeyboardInterrupt:
        console.print("Jadwal dihentikan.")
    return 0


def jam_scrape(cfg: Config) -> list[str]:
    """Daftar jam 'HH:MM' tiap SCRAPE_SETIAP_JAM mulai JAM_MULAI_SCRAPE dalam sehari."""
    mulai = cfg.jam_mulai_scrape.hour * 60 + cfg.jam_mulai_scrape.minute
    langkah = cfg.scrape_setiap_jam * 60
    menit = sorted({(mulai + i * langkah) % 1440 for i in range(1440 // langkah)})
    return [f"{m // 60:02d}:{m % 60:02d}" for m in menit]


# ---------------------------------------------------------------------- main
def main(argv: Sequence[str] | None = None, cfg: Config | None = None, console: Console | None = None) -> int:
    args = parse_args(argv)
    cfg = cfg or load_config()
    setup_logging(cfg.log_dir)
    console = console or Console()
    kode = 0

    if args.init_db:
        with Repo(cfg.db_path) as repo:
            repo.init_db()
        console.print(f"Database siap: {cfg.db_path}")

    if args.hapus_sebelum:
        with Repo(cfg.db_path) as repo:
            n = repo.hapus_artikel_sebelum(args.hapus_sebelum)
            sisa = repo.jumlah_artikel()
        console.print(f"Dihapus {n} artikel yang terbit sebelum {args.hapus_sebelum:%d %b %Y}; sisa {sisa} artikel.")

    if args.jadwal:
        return jalankan_jadwal(console, cfg)

    if args.backfill or args.sejak:
        hasil = pipeline.run_backfill(
            cfg, hari=args.backfill, sejak=args.sejak, keywords=args.keyword, simpan_mentah=args.simpan_mentah
        )
        tampilkan_hasil(console, hasil, cfg)
        kode = max(kode, hasil.exit_code)
    elif perlu_scrape(args):
        hasil = pipeline.run(
            cfg,
            mode="manual",
            semua=args.semua,
            topik=args.topik,
            keywords=args.keyword,
            simpan_keyword=args.simpan_keyword,
            simpan_mentah=args.simpan_mentah,
        )
        tampilkan_hasil(console, hasil, cfg)
        kode = max(kode, hasil.exit_code)

    if args.tampilkan:
        tampilkan_terbaru(console, cfg, args.tampilkan)
    if args.laporan:
        buat_laporan(console, cfg)
    if args.ekspor == "csv":
        console.print(f"Diekspor ke {ekspor_csv(cfg)}")
    return kode


if __name__ == "__main__":
    sys.exit(main())
