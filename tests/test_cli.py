import io
from datetime import date

import pytest
from rich.console import Console

import scraping
from pantauberita import pipeline


def test_argumen_terbaca():
    a = scraping.parse_args(["--topik", "teknologi", "--topik", "SPORTS", "--keyword", "banjir jogja"])
    assert a.topik == ["teknologi", "olahraga"] and a.keyword == ["banjir jogja"]
    a = scraping.parse_args(["--keyword", "UNY", "--simpan-keyword"])
    assert a.simpan_keyword
    assert scraping.parse_args(["--backfill", "7"]).backfill == 7
    assert scraping.parse_args(["--sejak", "2026-11-01"]).sejak == date(2026, 11, 1)
    assert scraping.parse_args(["--tampilkan", "10"]).tampilkan == 10
    assert scraping.parse_args(["--ekspor", "csv"]).ekspor == "csv"
    for flag in ["--semua", "--laporan", "--jadwal", "--simpan-mentah", "--init-db"]:
        assert scraping.parse_args([flag])


@pytest.mark.parametrize(
    "argv",
    [["--topik", "kuliner"], ["--backfill", "0"], ["--sejak", "17-11-2026"], ["--backfill", "3", "--sejak", "2026-11-01"],
     ["--simpan-keyword"], ["--ekspor", "json"]],
)
def test_argumen_tidak_valid(argv):
    with pytest.raises(SystemExit):
        scraping.parse_args(argv)


def test_perlu_scrape():
    assert scraping.perlu_scrape(scraping.parse_args([]))
    assert not scraping.perlu_scrape(scraping.parse_args(["--laporan"]))
    assert not scraping.perlu_scrape(scraping.parse_args(["--tampilkan", "5"]))
    assert scraping.perlu_scrape(scraping.parse_args(["--keyword", "x", "--laporan"]))
    assert not scraping.perlu_scrape(scraping.parse_args(["--backfill", "7"]))


@pytest.mark.parametrize("status,kode", [("sukses", 0), ("sebagian", 1), ("gagal", 2)])
def test_exit_code_sesuai_status(monkeypatch, cfg, status, kode):
    def palsu(cfg, **kwargs):
        return pipeline.HasilRun(run_id=1, mode="manual", status=status)

    monkeypatch.setattr(pipeline, "run", palsu)
    assert scraping.main([], cfg=cfg, console=Console(file=io.StringIO())) == kode


def test_init_db_tampilkan_ekspor(db_terisi):
    cfg = db_terisi
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False, width=200)
    assert scraping.main(["--init-db", "--tampilkan", "2", "--ekspor", "csv"], cfg=cfg, console=console) == 0
    keluar = buf.getvalue()
    assert "utama" in keluar and "topik:teknologi" in keluar and "keyword:banjir" in keluar
    csv = list(cfg.output_dir.glob("artikel_*.csv"))
    assert len(csv) == 1 and "Banjir Rendam" in csv[0].read_text(encoding="utf-8-sig")


def test_jam_scrape_cli(cfg):
    assert scraping.jam_scrape(cfg)[:3] == ["00:00", "03:00", "06:00"]
