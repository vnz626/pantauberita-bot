"""Format teks balasan bot (fungsi murni, parse_mode=HTML)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from html import escape
from typing import Any

from pantauberita.config import ATRIBUSI_SINGKAT, TOPIK, WIB

MAKS_BERITA = 10
MAKS_PANJANG = 4000  # batas Telegram 4096
SUMBER = f"<i>{ATRIBUSI_SINGKAT}</i>"
BULAN = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]

PERINTAH: tuple[tuple[str, str], ...] = (
    ("/hariini", "10 berita utama terbaru"),
    ("/topik <nama>", "10 berita terbaru satu topik"),
    ("/trending", "kata/isu yang sedang naik"),
    ("/cari <keyword>", "cari keyword di arsip berita"),
    ("/pantau <keyword>", "pantau keyword, dapat notifikasi"),
    ("/berhenti_pantau <keyword>", "hapus pantauan"),
    ("/pantauanku", "daftar keyword yang dipantau"),
    ("/media", "10 media paling aktif (7 hari)"),
    ("/grafik", "grafik topik + wordcloud"),
    ("/laporan", "PDF laporan terbaru"),
    ("/langganan, /stop", "laporan harian otomatis on/off"),
    ("/status", "status scraping dan database"),
    ("/perbarui", "jalankan scraping sekarang (admin)"),
)


def _waktu(terbit: str | datetime, sekarang: datetime | None = None) -> str:
    """'14:20' jika hari ini, selain itu '16 Nov 14:20'."""
    t = datetime.fromisoformat(terbit) if isinstance(terbit, str) else terbit
    t = t.astimezone(WIB)
    sekarang = (sekarang or datetime.now(WIB)).astimezone(WIB)
    if t.date() == sekarang.date():
        return f"{t:%H:%M}"
    return f"{t.day} {BULAN[t.month - 1]} {t:%H:%M}"


def format_berita(item: Mapping[str, Any], sekarang: datetime | None = None) -> str:
    """• Judul (Media, 14:20) dengan judul sebagai tautan."""
    link = escape(str(item["link"]), quote=True)
    judul = escape(str(item["judul"]))
    media = escape(str(item["media"]))
    return f'• <a href="{link}">{judul}</a> ({media}, {_waktu(item["terbit"], sekarang)})'


def pesan_kosong(konteks: str = "") -> str:
    tambahan = f" untuk {escape(konteks)}" if konteks else ""
    return (
        f"Belum ada berita{tambahan} di database. 🙏\n"
        "Tunggu jadwal scraping berikutnya, atau minta admin menjalankan /perbarui."
    )


def format_daftar_berita(
    judul: str, items: Sequence[Mapping[str, Any]], konteks_kosong: str = "", sekarang: datetime | None = None
) -> str:
    """Header + maksimal 10 berita + sumber. Dipotong agar < 4096 karakter."""
    if not items:
        return pesan_kosong(konteks_kosong) + "\n\n" + SUMBER
    baris = [f"<b>{escape(judul)}</b>", ""]
    panjang = sum(len(b) + 1 for b in baris) + len(SUMBER) + 2
    for item in list(items)[:MAKS_BERITA]:
        b = format_berita(item, sekarang)
        if panjang + len(b) + 1 > MAKS_PANJANG:
            break
        baris.append(b)
        panjang += len(b) + 1
    return "\n".join(baris) + "\n\n" + SUMBER


def pesan_bantuan(nama: str | None = None) -> str:
    sapa = f"Halo, {escape(nama)}! 👋" if nama else "Halo! 👋"
    daftar = "\n".join(f"{escape(c)} — {escape(d)}" for c, d in PERINTAH)
    topik = ", ".join(TOPIK.values())
    return (
        f"{sapa}\nSaya <b>PantauBerita</b>, bot pemantau berita harian Indonesia.\n\n"
        f"<b>Perintah</b>\n{daftar}\n\n<b>Topik</b>: {topik}\n\n"
        "Data berupa metadata (judul, media, waktu, tautan) dari RSS & sitemap resmi media; "
        "hak cipta milik masing-masing media.\n" + SUMBER
    )


def format_trending(trending: Sequence[tuple[str, int, float]], temuan: Sequence[str]) -> str:
    """trending: (kata, jumlah_hari_ini, skor)."""
    if not trending and not temuan:
        return pesan_kosong("hari ini") + "\n\n" + SUMBER
    baris = ["<b>🔥 Trending hari ini</b>"]
    if trending:
        baris += [f"{i}. {escape(k)} — {n} judul (skor {s:.1f})" for i, (k, n, s) in enumerate(trending[:10], 1)]
    else:
        baris.append("Belum ada kata yang menonjol.")
    if temuan:
        baris += ["", "<b>Temuan</b>"] + [f"• {escape(t)}" for t in temuan[:3]]
    return "\n".join(baris) + "\n\n" + SUMBER


def format_media(media: Sequence[tuple[str, int]]) -> str:
    if not media:
        return pesan_kosong("7 hari terakhir") + "\n\n" + SUMBER
    baris = ["<b>📰 10 media paling aktif (7 hari)</b>"]
    baris += [f"{i}. {escape(m)} — {n} berita" for i, (m, n) in enumerate(media[:10], 1)]
    return "\n".join(baris) + "\n\n" + SUMBER


def format_pantauanku(daftar: Sequence[tuple[str, int]]) -> str:
    if not daftar:
        return "Anda belum memantau keyword apa pun.\nContoh: <code>/pantau banjir jogja</code>"
    baris = ["<b>👀 Keyword pantauan Anda</b> (artikel 24 jam terakhir)"]
    baris += [f"• {escape(k)} — {n} artikel" for k, n in daftar]
    return "\n".join(baris)


def format_status(run: Mapping[str, Any] | None, total: int, jumlah_keyword: int = 0) -> str:
    if run is None:
        return f"Belum pernah scraping. Artikel di database: {total}."
    waktu = escape(str(run.get("selesai") or run.get("mulai") or "-"))[:16].replace("T", " ")
    return (
        "<b>ℹ️ Status PantauBerita</b>\n"
        f"Scrape terakhir: {waktu} WIB\n"
        f"Mode: {escape(str(run['mode']))} · Status: <b>{escape(str(run['status']))}</b>\n"
        f"Artikel baru pada run itu: {run.get('artikel_baru') or 0}\n"
        f"Total artikel di database: {total}\n"
        f"Keyword aktif: {jumlah_keyword}"
    )


def format_notifikasi(
    keyword: str, items: Sequence[Mapping[str, Any]], sisa: int, lonjakan: bool, sekarang: datetime | None = None
) -> str:
    baris = [f"<b>🔔 Berita baru: {escape(keyword)}</b>"]
    if lonjakan:
        baris.append("⚠️ <b>Isu ini sedang ramai</b> (≥2× rata-rata 7 hari).")
    baris.append("")
    baris += [format_berita(i, sekarang) for i in items]
    if sisa > 0:
        baris.append(f"+{sisa} berita lain")
    return "\n".join(baris) + "\n\n" + SUMBER


def format_laporan_harian(
    tanggal: str,
    temuan: Sequence[str],
    trending: Sequence[str],
    topik: Sequence[tuple[str, int]],
    keyword: Sequence[tuple[str, int]],
) -> str:
    baris = [f"<b>🗞️ Laporan harian PantauBerita — {escape(tanggal)}</b>", ""]
    baris += [f"• {escape(t)}" for t in temuan] or ["• Belum ada data."]
    if trending:
        baris += ["", "<b>Trending</b>: " + escape(", ".join(trending[:10]))]
    if topik:
        baris += ["", "<b>Top topik</b>"] + [f"{escape(t)}: {n}" for t, n in topik[:5]]
    if keyword:
        baris += ["", "<b>Keyword pantauan Anda (24 jam)</b>"] + [f"• {escape(k)}: {n} artikel" for k, n in keyword]
    return "\n".join(baris) + "\n\n" + SUMBER


def pesan_khusus_admin() -> str:
    return "Maaf, perintah ini hanya untuk admin."
