from datetime import date

from openpyxl import load_workbook

from pantauberita import reports


def test_laporan_excel_pdf_grafik(db_terisi):
    cfg = db_terisi
    hasil = reports.buat_laporan(cfg, tanggal=date(2026, 11, 17))
    for nama in ("excel", "pdf", "topik", "media", "trending", "wordcloud", "keyword"):
        assert hasil[nama].exists() and hasil[nama].stat().st_size > 0, nama
    assert hasil["pdf"].read_bytes().startswith(b"%PDF")

    wb = load_workbook(hasil["excel"])
    assert wb.sheetnames == ["Ringkasan", "Artikel Hari Ini", "Per Topik", "Top Media", "Trending", "Keyword"]
    ws = wb["Artikel Hari Ini"]
    assert ws.freeze_panes == "A2" and ws["A1"].font.bold
    kolom_link = [c.value for c in ws[1]].index("link") + 1
    assert ws.cell(row=2, column=kolom_link).hyperlink is not None
    assert reports.laporan_pdf_terbaru(cfg.output_dir) == hasil["pdf"]


def test_laporan_database_kosong(cfg):
    hasil = reports.buat_laporan(cfg, tanggal=date(2026, 11, 17))
    assert hasil["pdf"].exists() and hasil["excel"].exists()


def test_catatan_backfill():
    teks = reports.catatan_backfill(
        [{"mulai": "2026-11-18T09:00:00+07:00", "dari": "2026-11-10", "sampai": "2026-11-17", "jumlah": 50}] * 2
    )
    assert teks == [
        "Data 10 Nov 2026 – 17 Nov 2026 diambil secara backfill pada 18 Nov 2026 "
        "dari news sitemap resmi media (tanggal terbit asli)."
    ]
