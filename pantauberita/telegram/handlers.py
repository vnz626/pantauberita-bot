"""Handler perintah bot (tipis: ambil data -> format -> balas)."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from pantauberita import pipeline, reports
from pantauberita.analysis import charts, metrics
from pantauberita.collector.feeds import kode_topik, normalisasi_keyword
from pantauberita.config import ATRIBUSI_SINGKAT, TOPIK, WIB, Config
from pantauberita.storage.repo import Repo
from pantauberita.telegram import jobs, messages

log = logging.getLogger(__name__)

MAKS_KEYWORD = 60


def _cfg(context: ContextTypes.DEFAULT_TYPE) -> Config:
    return context.application.bot_data["cfg"]


async def _balas(update: Update, teks: str, **kwargs: object) -> None:
    pesan = update.effective_message
    if pesan is not None:
        await pesan.reply_text(teks, parse_mode=ParseMode.HTML, disable_web_page_preview=True, **kwargs)


def _argumen(context: ContextTypes.DEFAULT_TYPE) -> str:
    return normalisasi_keyword(" ".join(context.args or []))


def _daftarkan_pengguna(update: Update, cfg: Config) -> None:
    chat, user = update.effective_chat, update.effective_user
    if chat is None:
        return
    with Repo(cfg.db_path) as repo:
        repo.daftar_pengguna(chat.id, user.full_name if user else None)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _daftarkan_pengguna(update, _cfg(context))
    user = update.effective_user
    await _balas(update, messages.pesan_bantuan(user.first_name if user else None))


async def hariini(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    with Repo(_cfg(context).db_path) as repo:
        items = repo.artikel_terbaru("utama", messages.MAKS_BERITA)
    await _balas(update, messages.format_daftar_berita("📰 Berita utama terbaru", items, "berita utama"))


def _keyboard_topik() -> InlineKeyboardMarkup:
    label = list(TOPIK.values())
    baris = [
        [InlineKeyboardButton(t.capitalize(), callback_data=f"topik:{t}") for t in label[i : i + 2]]
        for i in range(0, len(label), 2)
    ]
    return InlineKeyboardMarkup(baris)


def _teks_topik(cfg: Config, label: str) -> str:
    with Repo(cfg.db_path) as repo:
        items = repo.artikel_terbaru(f"topik:{label}", messages.MAKS_BERITA)
    return messages.format_daftar_berita(f"🗂️ Topik: {label}", items, f"topik {label}")


async def topik(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    nama = _argumen(context)
    if not nama:
        await _balas(update, "Pilih topik:", reply_markup=_keyboard_topik())
        return
    try:
        label = TOPIK[kode_topik(nama)]
    except ValueError:
        await _balas(update, f"Topik tidak dikenal. Pilihan: {', '.join(TOPIK.values())}", reply_markup=_keyboard_topik())
        return
    await _balas(update, _teks_topik(_cfg(context), label))


async def tombol_topik(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or not query.data:
        return
    await query.answer()
    label = query.data.removeprefix("topik:")
    if label not in TOPIK.values():
        return
    await query.edit_message_text(_teks_topik(_cfg(context), label), parse_mode=ParseMode.HTML,
                                  disable_web_page_preview=True)


async def trending(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    tanggal = metrics.hari_ini()
    with Repo(_cfg(context).db_path) as repo:
        df = metrics.siapkan_df(repo.artikel_df(sejak=tanggal - timedelta(days=8)))
    tren = metrics.kata_trending(df, tanggal, n=10)
    baris = [(r.kata, int(r.hari_ini), float(r.skor)) for r in tren.itertuples()] if not tren.empty else []
    temuan = metrics.temuan(df, tanggal) if not df.empty else []
    await _balas(update, messages.format_trending(baris, temuan))


async def cari(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    kw = _argumen(context)
    if not kw:
        await _balas(update, "Contoh: <code>/cari harga beras</code>")
        return
    if len(kw) > MAKS_KEYWORD:
        await _balas(update, f"Keyword terlalu panjang (maks {MAKS_KEYWORD} karakter).")
        return
    cfg = _cfg(context)
    hasil = await asyncio.to_thread(pipeline.cari_lokal, cfg, kw)
    with Repo(cfg.db_path) as repo:
        items = repo.artikel_terbaru(f"keyword:{kw}", messages.MAKS_BERITA)
        run = repo.run_terakhir()
    terakhir = f" (data per {run['mulai'][:16].replace('T', ' ')} WIB)" if run else ""
    judul = f"🔎 Hasil: {kw} — {hasil.keyword.get(kw, 0)} artikel{terakhir}"
    await _balas(update, messages.format_daftar_berita(judul, items, f"keyword \"{kw}\""))


async def pantau(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    kw = _argumen(context)
    if not kw:
        await _balas(update, "Contoh: <code>/pantau banjir jogja</code>")
        return
    if len(kw) > MAKS_KEYWORD:
        await _balas(update, f"Keyword terlalu panjang (maks {MAKS_KEYWORD} karakter).")
        return
    cfg = _cfg(context)
    _daftarkan_pengguna(update, cfg)
    with Repo(cfg.db_path) as repo:
        baru = repo.tambah_pantauan(update.effective_chat.id, kw)
    if baru:
        teks = f"✅ Keyword <b>{messages.escape(kw)}</b> dipantau. Notifikasi dikirim setelah tiap scraping."
    else:
        teks = f"Keyword <b>{messages.escape(kw)}</b> sudah Anda pantau."
    await _balas(update, teks)


async def berhenti_pantau(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    kw = _argumen(context)
    if not kw:
        await _balas(update, "Contoh: <code>/berhenti_pantau banjir jogja</code>")
        return
    with Repo(_cfg(context).db_path) as repo:
        ok = repo.hapus_pantauan(update.effective_chat.id, kw)
    await _balas(update, f"🗑️ Berhenti memantau <b>{messages.escape(kw)}</b>." if ok
                 else f"Anda tidak sedang memantau <b>{messages.escape(kw)}</b>.")


async def pantauanku(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    sejak = datetime.now(WIB) - timedelta(hours=24)
    with Repo(_cfg(context).db_path) as repo:
        daftar = [(k, repo.jumlah_artikel_feed_sejak(f"keyword:{k}", sejak))
                  for k in repo.pantauan_pengguna(update.effective_chat.id)]
    await _balas(update, messages.format_pantauanku(daftar))


async def media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    tanggal = metrics.hari_ini()
    with Repo(_cfg(context).db_path) as repo:
        df = metrics.siapkan_df(repo.artikel_df(sejak=tanggal - timedelta(days=7)))
    top = metrics.top_media(df, 10, 7, tanggal)
    await _balas(update, messages.format_media([(str(m), int(n)) for m, n in top.items()]))


async def grafik(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg = _cfg(context)
    tanggal = metrics.hari_ini()
    with Repo(cfg.db_path) as repo:
        df = metrics.siapkan_df(repo.artikel_df(sejak=tanggal - timedelta(days=15)))
    if df.empty:
        await _balas(update, messages.pesan_kosong())
        return
    akhir = f"{tanggal.isoformat()}.png"
    p_topik = await asyncio.to_thread(charts.grafik_topik, df, cfg.output_dir / f"grafik_topik_{akhir}", tanggal)
    p_wc = await asyncio.to_thread(charts.wordcloud_judul, df, tanggal, cfg.output_dir / f"wordcloud_{akhir}")
    pesan = update.effective_message
    for path, caption in ((p_topik, "Tren topik 14 hari"), (p_wc, "Wordcloud judul hari ini")):
        with path.open("rb") as f:
            await pesan.reply_photo(f, caption=f"{caption} · {ATRIBUSI_SINGKAT}")


async def laporan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg = _cfg(context)
    path = reports.laporan_pdf_terbaru(cfg.output_dir)
    if path is None:
        await _balas(update, "Membuat laporan, mohon tunggu...")
        path = (await asyncio.to_thread(reports.buat_laporan, cfg))["pdf"]
    with path.open("rb") as f:
        await update.effective_message.reply_document(f, filename=path.name, caption=f"Laporan PantauBerita · {ATRIBUSI_SINGKAT}")


async def langganan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg = _cfg(context)
    _daftarkan_pengguna(update, cfg)
    with Repo(cfg.db_path) as repo:
        repo.set_langganan(update.effective_chat.id, True)
    await _balas(update, f"✅ Laporan harian aktif, dikirim pukul {cfg.jam_laporan:%H:%M} WIB. Matikan dengan /stop.")


async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    with Repo(_cfg(context).db_path) as repo:
        repo.set_langganan(update.effective_chat.id, False)
    await _balas(update, "Laporan harian dimatikan. Aktifkan lagi dengan /langganan.")


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    with Repo(_cfg(context).db_path) as repo:
        teks = messages.format_status(repo.run_terakhir(), repo.jumlah_artikel(), len(repo.keyword_aktif()))
    await _balas(update, teks)


async def perbarui(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg = _cfg(context)
    user = update.effective_user
    if user is None or user.id not in cfg.admin_ids:
        await _balas(update, messages.pesan_khusus_admin())
        return
    await _balas(update, "⏳ Menjalankan scraping...")
    hasil = await jobs.scrape_dan_notifikasi(context.bot, cfg, mode="bot")
    await _balas(update, f"Selesai: status <b>{hasil.status}</b>, {hasil.artikel_baru} artikel baru, "
                         f"{len(hasil.feeds)} feed, {hasil.durasi:.0f} detik.")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.error("Error saat memproses update", exc_info=context.error)


def daftarkan(app: Application) -> None:
    """Daftarkan semua handler perintah."""
    perintah = {
        "start": start,
        "bantuan": start,
        "hariini": hariini,
        "topik": topik,
        "trending": trending,
        "cari": cari,
        "pantau": pantau,
        "berhenti_pantau": berhenti_pantau,
        "pantauanku": pantauanku,
        "media": media,
        "grafik": grafik,
        "laporan": laporan,
        "langganan": langganan,
        "stop": stop,
        "status": status,
        "perbarui": perbarui,
    }
    for nama, fungsi in perintah.items():
        app.add_handler(CommandHandler(nama, fungsi))
    app.add_handler(CallbackQueryHandler(tombol_topik, pattern=r"^topik:"))
    app.add_error_handler(error_handler)
