"""Laporan Excel dan PDF dari data di database."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

import pandas as pd
from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from pantauberita.analysis import charts, metrics
from pantauberita.config import ATRIBUSI, WIB, Config
from pantauberita.storage.repo import Repo

log = logging.getLogger(__name__)

BULAN = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]


def tgl_id(t: date) -> str:
    """17 Nov 2026."""
    return f"{t.day} {BULAN[t.month - 1]} {t.year}"


def catatan_backfill(ringkasan: list[dict[str, Any]]) -> list[str]:
    """Kalimat transparansi untuk tiap run backfill (fungsi murni)."""
    hasil = []
    for r in ringkasan:
        if not r.get("dari"):
            continue
        dari, sampai = date.fromisoformat(r["dari"]), date.fromisoformat(r["sampai"])
        diambil = datetime.fromisoformat(r["mulai"]).date()
        rentang = tgl_id(dari) if dari == sampai else f"{tgl_id(dari)} – {tgl_id(sampai)}"
        hasil.append(
            f"Data {rentang} diambil secara backfill pada {tgl_id(diambil)} "
            "dari news sitemap resmi media (tanggal terbit asli)."
        )
    return list(dict.fromkeys(hasil))  # run dengan rentang & tanggal sama cukup ditulis sekali


@dataclass(frozen=True)
class DataLaporan:
    df: pd.DataFrame
    tanggal: date
    keywords: list[str]
    catatan: list[str]
    total_db: int


def kumpulkan_data(repo: Repo, tanggal: date, hari: int = 30) -> DataLaporan:
    """Ambil data 30 hari terakhir + info pendukung dari repo."""
    df = metrics.siapkan_df(repo.artikel_df(sejak=tanggal - timedelta(days=hari)))
    keywords = sorted({k["teks"] for k in repo.semua_keyword()})
    return DataLaporan(df, tanggal, keywords, catatan_backfill(repo.ringkasan_backfill()), repo.jumlah_artikel())


def artikel_hari_ini(df: pd.DataFrame, tanggal: date) -> pd.DataFrame:
    """Artikel unik yang terbit pada `tanggal`, terbaru dulu, dengan kolom daftar feed."""
    if df.empty:
        return pd.DataFrame(columns=["terbit", "judul", "media", "feed", "sentimen", "link"])
    hari = df[df["tanggal"] == tanggal]
    feed = hari.groupby("id")["feed"].agg(lambda s: ", ".join(sorted(set(s))))
    u = metrics.unik(hari).set_index("id")
    u["feed"] = feed
    u = u.sort_values("terbit", ascending=False)
    u["terbit"] = u["terbit"].dt.strftime("%Y-%m-%d %H:%M")
    return u[["terbit", "judul", "media", "feed", "sentimen", "link"]].reset_index(drop=True)


def berita_utama(df: pd.DataFrame, tanggal: date, n: int = 10) -> pd.DataFrame:
    """10 berita utama hari itu (feed 'utama'); jika kosong pakai semua feed."""
    semua = artikel_hari_ini(df, tanggal)
    utama = semua[semua["feed"].str.contains(r"\butama\b", regex=True)] if not semua.empty else semua
    return (utama if not utama.empty else semua).head(n)


# ---------------------------------------------------------------------- Excel
def _bersih(nilai: Any) -> Any:
    if isinstance(nilai, str):
        return ILLEGAL_CHARACTERS_RE.sub("", nilai)
    if isinstance(nilai, float) and pd.isna(nilai):
        return None
    return nilai


def _tulis_sheet(ws: Worksheet, data: pd.DataFrame, kolom_link: str | None = None) -> None:
    kolom = list(data.columns)
    ws.append(kolom)
    for baris in data.itertuples(index=False):
        ws.append([_bersih(v) for v in baris])
    for c in ws[1]:
        c.font = Font(bold=True)
    ws.freeze_panes = "A2"
    if data.shape[0] > 0:
        ws.auto_filter.ref = ws.dimensions
    if kolom_link and kolom_link in kolom:
        idx = kolom.index(kolom_link) + 1
        for (cell,) in ws.iter_rows(min_row=2, min_col=idx, max_col=idx):
            if cell.value:
                cell.hyperlink = str(cell.value)
                cell.style = "Hyperlink"
    for i, nama in enumerate(kolom, start=1):
        terpanjang = max([len(str(nama))] + [len(str(v)) for v in data.iloc[:200, i - 1]]) if len(data) else len(nama)
        ws.column_dimensions[get_column_letter(i)].width = min(70, max(10, terpanjang + 2))


def buat_excel(data: DataLaporan, path: Path) -> Path:
    """Excel dengan sheet Ringkasan, Artikel Hari Ini, Per Topik, Top Media, Trending, Keyword."""
    df, tgl = data.df, data.tanggal
    hari = artikel_hari_ini(df, tgl)
    wb = Workbook()
    ws = wb.active
    ws.title = "Ringkasan"
    ringkasan = pd.DataFrame(
        [
            ("Tanggal laporan", tgl.isoformat()),
            ("Artikel hari ini", len(hari)),
            ("Media hari ini", hari["media"].nunique() if not hari.empty else 0),
            ("Total artikel di database", data.total_db),
            ("Sentimen rata-rata hari ini", round(float(hari["sentimen"].mean()), 3) if not hari.empty else None),
        ]
        + [(f"Temuan {i}", t) for i, t in enumerate(metrics.temuan(df, tgl), start=1)]
        + [("Catatan", c) for c in data.catatan]
        + [("Sumber", ATRIBUSI)],
        columns=["Butir", "Nilai"],
    )
    _tulis_sheet(ws, ringkasan)

    _tulis_sheet(wb.create_sheet("Artikel Hari Ini"), hari, "link")

    per_topik = metrics.jumlah_per_hari(df, "topik:")
    per_topik = per_topik.tail(30).rename(columns=lambda c: c.removeprefix("topik:")).reset_index()
    _tulis_sheet(wb.create_sheet("Per Topik"), per_topik)

    media = metrics.top_media(df, 20, 7, tgl).reset_index()
    _tulis_sheet(wb.create_sheet("Top Media"), media)

    _tulis_sheet(wb.create_sheet("Trending"), metrics.kata_trending(df, tgl))

    per_kw = metrics.jumlah_per_hari(df, "keyword:")
    if not per_kw.empty:
        per_kw = per_kw.tail(30).rename(columns=lambda c: c.removeprefix("keyword:")).reset_index()
    _tulis_sheet(wb.create_sheet("Keyword"), per_kw)

    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


# ---------------------------------------------------------------------- PDF
def buat_pdf(data: DataLaporan, path: Path, grafik: dict[str, Path]) -> Path:
    """PDF 1-2 halaman: judul, temuan, 10 berita utama, grafik topik, wordcloud, sumber."""
    gaya = getSampleStyleSheet()
    kecil = gaya["BodyText"].clone("kecil", fontSize=8, leading=10)
    isi: list[Any] = [
        Paragraph("Laporan PantauBerita", gaya["Title"]),
        Paragraph(f"Tanggal: {tgl_id(data.tanggal)} · dibuat {datetime.now(WIB):%d-%m-%Y %H:%M} WIB", gaya["Normal"]),
        Spacer(1, 0.3 * cm),
        Paragraph("Temuan", gaya["Heading2"]),
    ]
    isi += [Paragraph("• " + escape(t), gaya["BodyText"]) for t in metrics.temuan(data.df, data.tanggal)]

    isi += [Spacer(1, 0.3 * cm), Paragraph("10 berita utama", gaya["Heading2"])]
    utama = berita_utama(data.df, data.tanggal)
    if utama.empty:
        isi.append(Paragraph("Belum ada berita untuk tanggal ini.", gaya["BodyText"]))
    else:
        baris = [["Jam", "Judul", "Media"]] + [
            [r.terbit[-5:], Paragraph(f'<a href="{escape(r.link)}">{escape(r.judul)}</a>', kecil), Paragraph(escape(r.media), kecil)]
            for r in utama.itertuples()
        ]
        tabel = Table(baris, colWidths=[1.3 * cm, 12.2 * cm, 3.5 * cm], repeatRows=1)
        tabel.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e9eef7")),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#c0c0c0")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        isi.append(tabel)

    for nama, judul in (("topik", "Tren topik"), ("wordcloud", "Wordcloud judul hari ini")):
        if nama in grafik and grafik[nama].exists():
            isi += [Spacer(1, 0.3 * cm), Paragraph(judul, gaya["Heading2"]), Image(str(grafik[nama]), 16 * cm, 8 * cm)]

    isi.append(Spacer(1, 0.4 * cm))
    for c in data.catatan:
        isi.append(Paragraph("Catatan: " + escape(c), kecil))
    isi.append(Paragraph(escape(ATRIBUSI) + ". Hanya metadata (judul, media, waktu, tautan, cuplikan RSS).", kecil))

    path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(path), pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=1.5 * cm, bottomMargin=1.5 * cm,
        title=f"Laporan PantauBerita {data.tanggal.isoformat()}",
    )
    doc.build(isi)
    return path


def buat_laporan(cfg: Config, tanggal: date | None = None, repo: Repo | None = None) -> dict[str, Path]:
    """Buat grafik + Excel + PDF di output/. Kembalikan {nama: path}."""
    tanggal = tanggal or datetime.now(WIB).date()
    tutup = repo is None
    repo = repo or Repo(cfg.db_path)
    try:
        data = kumpulkan_data(repo, tanggal)
    finally:
        if tutup:
            repo.close()
    grafik = charts.buat_semua_grafik(data.df, tanggal, cfg.output_dir, data.keywords)
    hasil = dict(grafik)
    hasil["excel"] = buat_excel(data, cfg.output_dir / f"laporan_{tanggal.isoformat()}.xlsx")
    hasil["pdf"] = buat_pdf(data, cfg.output_dir / f"laporan_{tanggal.isoformat()}.pdf", grafik)
    log.info("Laporan dibuat: %s", ", ".join(str(p.name) for p in hasil.values()))
    return hasil


def laporan_pdf_terbaru(output_dir: Path) -> Path | None:
    """PDF laporan terbaru di output/ (berdasarkan nama file bertanggal)."""
    daftar = sorted(output_dir.glob("laporan_*.pdf"))
    return daftar[-1] if daftar else None
