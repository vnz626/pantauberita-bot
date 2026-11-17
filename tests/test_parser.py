from datetime import date, datetime

from pantauberita.config import WIB
from pantauberita.parser.rss import (
    MEDIA_TIDAK_DIKETAHUI,
    buat_id,
    domain_dari,
    hapus_sufiks_media,
    normalisasi_link,
    parse_feed,
    parse_sitemap,
)


def test_parse_rss_media(baca_fixture):
    artikel = parse_feed(baca_fixture("rss_utama.xml"), "CNN Indonesia")
    assert len(artikel) == 5
    a = artikel[0]
    assert a.judul == "Banjir Rendam Ratusan Rumah di Sleman Jogja"
    assert a.media == "CNN Indonesia"
    assert a.domain == "cnnindonesia.com"
    assert a.id == buat_id(a.link)


def test_sufiks_media_terhapus_dan_karakter_html(baca_fixture):
    judul = [a.judul for a in parse_feed(baca_fixture("rss_utama.xml"), "CNN Indonesia")]
    assert "Harga Emas & Perak Naik Tajam Pagi Ini" in judul
    assert hapus_sufiks_media("Gempa Guncang Bantul | Media Contoh", "Media Contoh") == "Gempa Guncang Bantul"
    assert hapus_sufiks_media("Persib vs Persija - Babak 1", "CNN Indonesia") == "Persib vs Persija - Babak 1"


def test_konversi_waktu_ke_wib(baca_fixture):
    artikel = parse_feed(baca_fixture("rss_utama.xml"), "CNN Indonesia")
    assert artikel[0].terbit == datetime(2026, 11, 17, 14, 20, tzinfo=WIB)
    assert artikel[0].terbit.utcoffset().total_seconds() == 7 * 3600
    # 23:30 GMT 16 Nov = 06:30 WIB 17 Nov
    assert artikel[3].terbit == datetime(2026, 11, 17, 6, 30, tzinfo=WIB)


def test_ringkasan_tanpa_tag_html(baca_fixture):
    a = parse_feed(baca_fixture("rss_utama.xml"), "CNN Indonesia")[0]
    assert "<" not in a.ringkasan and a.ringkasan.startswith("Hujan deras")
    assert len(a.ringkasan) <= 300


def test_item_rusak_dilewati_dan_media_dari_channel(baca_fixture):
    waktu = datetime(2026, 11, 17, 9, 0, tzinfo=WIB)
    artikel = parse_feed(baca_fixture("tanpa_source.xml"), waktu_scrape=waktu)
    assert [a.judul for a in artikel] == ["Gempa Magnitudo 5,1 Guncang Bantul", "Judul tanpa waktu terbit"]
    assert artikel[0].media == "Media Contoh"  # dari <channel><title>
    assert artikel[0].domain == "media-contoh.co.id"
    assert artikel[1].terbit == waktu  # tanpa pubDate -> waktu scrape


def test_xml_rusak_mengembalikan_list_kosong(baca_fixture, caplog):
    assert parse_feed(baca_fixture("rusak.xml")) == []
    assert any(r.levelname == "ERROR" for r in caplog.records)
    assert parse_feed(b"") == []
    assert parse_feed("bukan xml sama sekali") == []
    assert parse_sitemap(baca_fixture("rusak.xml")) == []


def test_feed_kosong(baca_fixture):
    assert parse_feed(baca_fixture("kosong.xml")) == []


def test_parse_sitemap(baca_fixture):
    artikel = parse_sitemap(baca_fixture("sitemap_detik.xml"))
    assert len(artikel) == 4  # item tanpa <news:title> dilewati
    a = artikel[1]
    assert a.judul == "Harga Cabai Turun di Pasar Induk, Banjir Pasokan dari Jogja"
    assert a.media == "detikNews" and a.domain == "detik.com" and a.ringkasan == ""
    assert a.terbit == datetime(2026, 11, 10, 19, 30, tzinfo=WIB)
    assert artikel[3].terbit.date() == date(2026, 11, 11)  # 18:30Z = 01:30 WIB besoknya


def test_normalisasi_link_dan_domain():
    a = "https://www.cnnindonesia.com/teknologi/123/judul/?utm_source=rss#atas"
    b = "https://WWW.cnnindonesia.com/teknologi/123/judul"
    assert normalisasi_link(a) == normalisasi_link(b)
    assert buat_id(a) == buat_id(b)
    assert domain_dari("https://news.detik.com/x") == "detik.com"
    assert domain_dari("https://www.viva.co.id/x") == "viva.co.id"
    assert MEDIA_TIDAK_DIKETAHUI == "Tidak diketahui"
