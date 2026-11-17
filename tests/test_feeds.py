from datetime import date

import pytest

from pantauberita.analysis.text import cocok_keyword
from pantauberita.collector import feeds
from pantauberita.collector.http import HttpClient, izinkan_robots
from pantauberita.config import TOPIK


def test_bangun_feeds_default_utama_dan_8_topik():
    semua = feeds.bangun_feeds(topik_aktif=list(TOPIK))
    label = {f.label for f in semua}
    assert label == {"utama"} | {f"topik:{t}" for t in TOPIK.values()}
    assert len([f for f in semua if f.label == "utama"]) == len(feeds.SUMBER_UTAMA)
    assert len({f.url for f in semua}) == len(semua)  # tidak ada URL ganda
    assert all(f.url.startswith("https://") and f.jenis == "rss" for f in semua)


def test_bangun_feeds_satu_topik():
    hanya = feeds.bangun_feeds(topik_aktif=list(TOPIK), topik=["teknologi"])
    assert {f.label for f in hanya} == {"topik:teknologi"}
    assert {f.media for f in hanya} >= {"CNN Indonesia", "detikInet"}


def test_kode_topik_tidak_dikenal():
    assert feeds.kode_topik("teknologi") == "TECHNOLOGY"
    with pytest.raises(ValueError):
        feeds.kode_topik("kuliner")


def test_semua_topik_punya_sumber():
    assert set(feeds.SUMBER_TOPIK) == set(TOPIK)
    assert all(len(v) >= 2 for v in feeds.SUMBER_TOPIK.values())


def test_normalisasi_dan_pencocokan_keyword():
    assert feeds.normalisasi_keyword("  Banjir   JOGJA ") == "banjir jogja"
    assert cocok_keyword("Banjir Rendam Ratusan Rumah di Sleman, Jogja", "banjir jogja")
    assert not cocok_keyword("Banjir di Sleman", "banjir jogja")  # semua kata wajib ada
    assert not cocok_keyword("Pembanjiran data", "banjir")  # kata utuh
    assert cocok_keyword("Rektor UNY lantik pejabat", "uny")
    assert not cocok_keyword("apa saja", "")


def test_backfill_tanggal_dan_sitemap():
    tanggal = feeds.daftar_tanggal_backfill(date(2026, 11, 18), hari=7)
    assert tanggal[0] == date(2026, 11, 11) and tanggal[-1] == date(2026, 11, 17) and len(tanggal) == 7
    daftar = feeds.bangun_feeds_backfill(tanggal, ["detik.com", "tidak-dikenal.com"])
    assert daftar and all(f.jenis == "sitemap" and f.label == "sitemap:detik.com" for f in daftar)
    assert daftar[0].rentang == (date(2026, 11, 11), date(2026, 11, 17))
    assert feeds.bangun_feeds_backfill([], ["detik.com"]) == []


def test_backfill_sejak_sampai_kemarin():
    tanggal = feeds.daftar_tanggal_backfill(date(2026, 11, 18), sejak=date(2026, 11, 1))
    assert tanggal[0] == date(2026, 11, 1) and tanggal[-1] == date(2026, 11, 17) and len(tanggal) == 17


def test_robots_dievaluasi():
    url = "https://news.contoh.test/rss"
    assert izinkan_robots("User-agent: *\nDisallow: /\n", "PantauBerita/1.0", [url])[url] is False
    assert izinkan_robots("User-agent: *\nAllow: /\n", "PantauBerita/1.0", [url])[url] is True
    khusus_ai = "User-agent: ClaudeBot\nDisallow: /\n\nUser-agent: *\nAllow: /\n"
    assert izinkan_robots(khusus_ai, "PantauBerita/1.0", [url])[url] is True


def test_cek_robots_satu_request_per_host():
    diminta: list[str] = []

    class Resp:
        def __init__(self, isi: bytes):
            self.content = isi

        def raise_for_status(self):
            return None

    class Sesi:
        def get(self, url, timeout):
            diminta.append(url)
            return Resp(b"User-agent: *\nDisallow: /rahasia\n")

    c = HttpClient(jeda_detik=0, session=Sesi())
    hasil = c.cek_robots(["https://a.test/rss", "https://a.test/rahasia/rss", "https://b.test/rss"])
    assert hasil == {"https://a.test/rss": True, "https://a.test/rahasia/rss": False, "https://b.test/rss": True}
    assert diminta == ["https://a.test/robots.txt", "https://b.test/robots.txt"]


def test_http_client_menjaga_jeda():
    tidur: list[float] = []
    jam = iter([0.0, 0.5, 0.5])

    class Resp:
        content = b"ok"

        def raise_for_status(self):
            return None

    class Sesi:
        def get(self, url, timeout):
            return Resp()

    c = HttpClient(jeda_detik=1.5, session=Sesi(), tidur=tidur.append, jam=lambda: next(jam))
    c.ambil("https://a")
    c.ambil("https://b")
    assert tidur == [1.0]


def test_topik_dari_url():
    t = feeds.topik_dari_url
    assert t("https://finance.detik.com/berita-ekonomi-bisnis/d-1/judul") == "bisnis"
    assert t("https://news.detik.com/internasional/d-1/judul") == "dunia"
    assert t("https://news.detik.com/berita/d-1/judul") == "nasional"
    assert t("https://www.viva.co.id/berita/dunia/1-judul") == "dunia"  # spesifik menang atas 'berita'
    assert t("https://www.viva.co.id/gaya-hidup/showbiz/1-judul") == "hiburan"
    assert t("https://www.cnbcindonesia.com/tech/2026-38-1/judul") == "teknologi"
    assert t("https://www.viva.co.id/otomotif/1-judul") is None
    assert t("https://www.contoh.test/bisnis-baru") is None  # slug judul tidak dipakai
    assert feeds.label_dari_url("https://www.viva.co.id/otomotif/1-x") == "utama"
