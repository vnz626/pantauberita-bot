"""Job terjadwal bot: scrape, notifikasi keyword, dan laporan harian."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

import pandas as pd
from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import Forbidden, TelegramError
from telegram.ext import Application, ContextTypes

from pantauberita import pipeline, reports
from pantauberita.analysis import metrics
from pantauberita.config import WIB, Config
from pantauberita.storage.repo import Repo
from pantauberita.telegram import messages

log = logging.getLogger(__name__)

MAKS_PER_KEYWORD = 5


@dataclass(frozen=True)
class Notifikasi:
    chat_id: int
    keyword: str
    items: list[dict[str, Any]]
    sisa: int
    lonjakan: bool
    ids: list[str]  # semua artikel yang dianggap terkirim (termasuk yang diringkas "+N")


def kumpulkan_notifikasi(
    repo: Repo,
    run_id: int,
    df: pd.DataFrame | None = None,
    tanggal: date | None = None,
    sejak: datetime | None = None,
) -> list[Notifikasi]:
    """Untuk tiap (pengguna, keyword): artikel run ini (terbit >= sejak) yang belum pernah dikirim."""
    tanggal = tanggal or metrics.hari_ini()
    if df is None:
        df = metrics.siapkan_df(repo.artikel_df(sejak=tanggal - timedelta(days=8)))
    hasil = []
    for chat_id, keyword in repo.semua_pantauan():
        baru = repo.artikel_belum_dinotifikasi(chat_id, keyword, run_id, sejak)
        if not baru:
            continue
        hasil.append(
            Notifikasi(
                chat_id=chat_id,
                keyword=keyword,
                items=baru[:MAKS_PER_KEYWORD],
                sisa=max(0, len(baru) - MAKS_PER_KEYWORD),
                lonjakan=metrics.lonjakan_keyword(df, keyword, tanggal),
                ids=[a["id"] for a in baru],
            )
        )
    return hasil


async def kirim_aman(bot: Bot, cfg: Config, chat_id: int, teks: str) -> bool:
    """Kirim pesan HTML; jika pengguna memblokir bot, matikan langganan & hapus pantauannya."""
    try:
        await bot.send_message(chat_id, teks, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        return True
    except Forbidden:
        log.info("Chat %s memblokir bot; langganan dimatikan", chat_id)
        with Repo(cfg.db_path) as repo:
            repo.nonaktifkan_pengguna(chat_id)
    except TelegramError:
        log.exception("Gagal mengirim pesan ke %s", chat_id)
    return False


async def kirim_notifikasi(bot: Bot, cfg: Config, run_id: int) -> int:
    """Kirim notifikasi keyword setelah scrape. Kembalikan jumlah pesan terkirim."""
    with Repo(cfg.db_path) as repo:
        daftar = kumpulkan_notifikasi(repo, run_id, sejak=datetime.now(WIB) - timedelta(hours=48))
    terkirim = 0
    for n in daftar:
        teks = messages.format_notifikasi(n.keyword, n.items, n.sisa, n.lonjakan)
        if await kirim_aman(bot, cfg, n.chat_id, teks):
            with Repo(cfg.db_path) as repo:
                repo.tandai_terkirim(n.chat_id, n.ids)
            terkirim += 1
    return terkirim


async def kabari_admin(bot: Bot, cfg: Config, teks: str) -> None:
    for admin in cfg.admin_ids:
        await kirim_aman(bot, cfg, admin, teks)


async def scrape_dan_notifikasi(bot: Bot, cfg: Config, mode: str = "bot") -> pipeline.HasilRun:
    """Jalankan pipeline di thread terpisah, lalu kirim notifikasi / kabari admin bila gagal."""
    hasil = await asyncio.to_thread(pipeline.run, cfg, mode=mode, semua=True)
    if hasil.status == "gagal":
        await kabari_admin(
            bot, cfg, f"⚠️ Scraping run #{hasil.run_id} <b>gagal total</b>.\n<code>{(hasil.pesan_error or '')[:500]}</code>"
        )
    else:
        await kirim_notifikasi(bot, cfg, hasil.run_id)
    return hasil


def susun_laporan_harian(repo: Repo, chat_id: int, tanggal: date) -> str:
    """Teks laporan harian untuk satu pengguna."""
    df = metrics.siapkan_df(repo.artikel_df(sejak=tanggal - timedelta(days=8)))
    trending = metrics.kata_trending(df, tanggal, n=10)
    topik = metrics.distribusi_topik(df, tanggal)
    sejak = datetime.now(WIB) - timedelta(hours=24)
    kw = [(k, repo.jumlah_artikel_feed_sejak(f"keyword:{k}", sejak)) for k in repo.pantauan_pengguna(chat_id)]
    return messages.format_laporan_harian(
        reports.tgl_id(tanggal),
        metrics.temuan(df, tanggal),
        list(trending["kata"]) if not trending.empty else [],
        [(str(t), int(n)) for t, n in topik.items()],
        kw,
    )


async def job_scrape(context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg: Config = context.application.bot_data["cfg"]
    try:
        await scrape_dan_notifikasi(context.bot, cfg)
    except Exception as exc:
        log.exception("Job scrape gagal")
        await kabari_admin(context.bot, cfg, f"⚠️ Job scrape error: <code>{type(exc).__name__}</code>")


async def job_laporan(context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg: Config = context.application.bot_data["cfg"]
    # Laporan pagi merangkum hari sebelumnya bila jam laporan sebelum siang.
    sekarang = datetime.now(WIB)
    tanggal = sekarang.date() - timedelta(days=1) if sekarang.hour < 12 else sekarang.date()
    try:
        await asyncio.to_thread(reports.buat_laporan, cfg, tanggal)
    except Exception:
        log.exception("Gagal membuat file laporan")
    with Repo(cfg.db_path) as repo:
        pelanggan = repo.pelanggan_laporan()
        teks = {c: susun_laporan_harian(repo, c, tanggal) for c in pelanggan}
    for chat_id, isi in teks.items():
        await kirim_aman(context.bot, cfg, chat_id, isi)


def jam_jadwal(mulai: time, setiap_jam: int) -> list[time]:
    """Jam-jam scrape dalam sehari (WIB) tiap `setiap_jam` mulai `mulai`."""
    awal = mulai.hour * 60 + mulai.minute
    langkah = setiap_jam * 60
    menit = sorted({(awal + i * langkah) % 1440 for i in range(1440 // langkah)})
    return [time(m // 60, m % 60, tzinfo=WIB) for m in menit]


def jadwalkan(app: Application, cfg: Config) -> None:
    """Daftarkan job scrape dan laporan harian ke JobQueue (zona Asia/Jakarta)."""
    jq = app.job_queue
    if jq is None:
        raise RuntimeError('JobQueue tidak tersedia. Instal: pip install "python-telegram-bot[job-queue]"')
    for t in jam_jadwal(cfg.jam_mulai_scrape, cfg.scrape_setiap_jam):
        jq.run_daily(job_scrape, time=t, name=f"scrape-{t:%H%M}")
    jq.run_daily(job_laporan, time=cfg.jam_laporan.replace(tzinfo=WIB), name="laporan-harian")
    log.info("Jadwal bot: scrape %s, laporan %s WIB",
             ", ".join(f"{t:%H:%M}" for t in jam_jadwal(cfg.jam_mulai_scrape, cfg.scrape_setiap_jam)),
             f"{cfg.jam_laporan:%H:%M}")
