from dataclasses import replace
from datetime import date

import requests

from pantauberita import pipeline
from pantauberita.collector.feeds import bangun_feeds
from pantauberita.config import TOPIK
from pantauberita.storage.repo import Repo

JUMLAH_FEED = len(bangun_feeds(topik_aktif=list(TOPIK)))


def test_run_default_sukses_dan_idempoten(cfg, peta, fake_client_cls):
    client = fake_client_cls(peta())
    hasil = pipeline.run(cfg, client=client)
    assert hasil.status == "sukses" and hasil.exit_code == 0
    assert len(client.diminta) == JUMLAH_FEED
    assert hasil.artikel_baru == 7  # 5 dari feed utama + 2 baru dari teknologi (1 sama, link ber-utm)
    assert pipeline.run(cfg, client=client).artikel_baru == 0
    with Repo(cfg.db_path) as repo:
        assert repo.jumlah_artikel() == 7


def test_satu_feed_error_status_sebagian(cfg, peta, fake_client_cls):
    client = fake_client_cls(peta(gagal="cnnindonesia.com/teknologi/rss"))
    hasil = pipeline.run(cfg, client=client)
    assert hasil.status == "sebagian" and hasil.exit_code == 1
    assert [f.feed for f in hasil.feeds if f.error] == ["topik:teknologi"]
    with Repo(cfg.db_path) as repo:
        assert repo.jumlah_artikel() == 5  # feed utama tetap tersimpan
        assert repo.run_terakhir()["status"] == "sebagian"


def test_semua_feed_gagal_status_gagal(cfg, fake_client_cls):
    hasil = pipeline.run(cfg, client=fake_client_cls(lambda url: requests.Timeout("lambat")))
    assert hasil.status == "gagal" and hasil.exit_code == 2


def test_robots_diblokir_feed_dilewati(cfg, peta, fake_client_cls):
    client = fake_client_cls(peta(), robots_ok=lambda u: "viva.co.id" not in u)
    hasil = pipeline.run(cfg, client=client)
    diblokir = [f for f in hasil.feeds if f.error == "diblokir robots.txt"]
    assert diblokir and all(f.media == "VIVA" for f in diblokir)
    assert not any("viva.co.id" in u for u in client.diminta)  # tidak pernah diminta
    assert hasil.status == "sebagian"
    semua_blokir = pipeline.run(cfg, client=fake_client_cls(peta(), robots_ok=False))
    assert semua_blokir.status == "gagal" and "robots.txt" in semua_blokir.pesan_error


def test_keyword_cocok_dan_simpan_keyword(cfg, peta, fake_client_cls):
    client = fake_client_cls(peta())
    hasil = pipeline.run(cfg, keywords=["Banjir  Jogja"], client=client)
    assert hasil.keyword == {"banjir jogja": 1}
    with Repo(cfg.db_path) as repo:
        assert repo.keyword_aktif() == []  # tanpa --simpan-keyword tidak ikut jadwal
        assert repo.artikel_terbaru("keyword:banjir jogja")[0]["judul"].startswith("Banjir Rendam")
    pipeline.run(cfg, keywords=["timnas"], simpan_keyword=True, client=client)
    with Repo(cfg.db_path) as repo:
        assert repo.keyword_aktif() == ["timnas"]
    # keyword aktif ikut dicocokkan otomatis pada run berikutnya
    assert pipeline.run(cfg, semua=True, client=client).keyword == {"timnas": 1}


def test_keyword_baru_mencari_riwayat_database(cfg, peta, fake_client_cls):
    pipeline.run(cfg, client=fake_client_cls(peta()))
    hasil = pipeline.cari_lokal(cfg, "Startup")
    assert hasil.keyword == {"startup": 1} and hasil.status == "sukses"
    with Repo(cfg.db_path) as repo:
        assert len(repo.artikel_terbaru("keyword:startup")) == 1


def test_backfill_rentang_dan_mode(cfg, peta, fake_client_cls):
    cfg1 = replace(cfg, media_backfill=("viva.co.id",))
    client = fake_client_cls(peta())
    hasil = pipeline.run_backfill(cfg1, hari=1, hari_ini=date(2026, 11, 11), client=client)
    assert hasil.mode == "backfill" and hasil.status == "sukses"
    assert len(client.diminta) == 1 and "sitemap" in client.diminta[0]
    # 4 item bertanggal: 1 terbit 7 Nov, 1 terbit 11 Nov 01:30 WIB -> dibuang
    assert hasil.feeds[0].diambil == 2 and hasil.feeds[0].feed == "sitemap:viva.co.id"
    assert hasil.cakupan == {date(2026, 11, 10): 2}
    with Repo(cfg.db_path) as repo:
        assert repo.run_terakhir()["mode"] == "backfill"
        r = repo.ringkasan_backfill()[0]
        assert (r["dari"], r["sampai"], r["jumlah"]) == ("2026-11-10", "2026-11-10", 2)


def test_backfill_satu_keyword_hanya_simpan_yang_cocok(cfg, peta, fake_client_cls):
    cfg1 = replace(cfg, media_backfill=("viva.co.id",))
    hasil = pipeline.run_backfill(
        cfg1, hari=7, keywords=["banjir"], hari_ini=date(2026, 11, 12), client=fake_client_cls(peta())
    )
    assert hasil.keyword == {"banjir": 1} and hasil.artikel_baru == 1
    assert sum(hasil.cakupan.values()) == 1 and len(hasil.cakupan) == 7


def test_fungsi_murni_pipeline():
    assert pipeline.saring_rentang([], None) == []
    assert pipeline.tentukan_status(3, 0) == "sukses"
    assert pipeline.tentukan_status(3, 1) == "sebagian"
    assert pipeline.tentukan_status(3, 3) == "gagal"
    baris = [{"id": "a", "judul": "Harga BBM naik", "ringkasan": ""}, {"id": "b", "judul": "Lain", "ringkasan": "bbm"}]
    assert pipeline.cocokkan(baris, "bbm") == ["a", "b"]


def test_backfill_diberi_label_topik_bukan_backfill(cfg, peta, fake_client_cls):
    cfg1 = replace(cfg, media_backfill=("viva.co.id",))
    pipeline.run_backfill(cfg1, hari=1, hari_ini=date(2026, 11, 11), client=fake_client_cls(peta()))
    with Repo(cfg.db_path) as repo:
        assert repo.daftar_feed() == ["topik:nasional"]  # news.detik.com/berita/... -> nasional


def test_migrasi_label_backfill_lama(repo):
    from conftest import buat_artikel

    run = repo.mulai_run("backfill")
    a = buat_artikel("x")
    a = a.__class__(**{**a.__dict__, "link": "https://sport.detik.com/sepakbola/d-1/judul"})
    repo.simpan_feed(run, "backfill:detik.com", [a])
    assert pipeline.migrasi_label_backfill(repo) == 1
    assert repo.daftar_feed() == ["topik:olahraga"]
