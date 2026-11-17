from conftest import buat_artikel

from pantauberita.collector.feeds import normalisasi_keyword


def test_artikel_sama_dari_dua_feed(repo, baca_fixture):
    from pantauberita.parser.rss import parse_feed

    run = repo.mulai_run("manual")
    baru_utama = repo.simpan_feed(run, "utama", parse_feed(baca_fixture("rss_utama.xml"), "CNN Indonesia"))
    baru_tek = repo.simpan_feed(run, "topik:teknologi", parse_feed(baca_fixture("rss_teknologi.xml"), "CNN Indonesia"))
    assert baru_utama == 5
    assert baru_tek == 2  # 1 artikel (Startup) sudah ada dari feed utama (link ber-utm tetap dikenali)
    assert repo.jumlah_artikel() == 7
    assert repo.jumlah_kemunculan() == 8


def test_satu_artikel_dua_feed_satu_baris(repo):
    a = buat_artikel("x")
    run = repo.mulai_run("manual")
    repo.simpan_feed(run, "utama", [a])
    repo.simpan_feed(run, "topik:bisnis", [a])
    assert repo.jumlah_artikel() == 1
    assert repo.jumlah_kemunculan() == 2


def test_jalan_dua_kali_tidak_duplikat(repo):
    artikel = [buat_artikel("a"), buat_artikel("b")]
    for _ in range(2):
        run = repo.mulai_run("manual")
        repo.simpan_feed(run, "utama", artikel)
        repo.simpan_feed(run, "utama", artikel)  # bahkan dalam satu run
    assert repo.jumlah_artikel() == 2
    assert repo.jumlah_kemunculan() == 4  # 2 artikel x 2 run


def test_aman_dari_sql_injection(repo):
    jahat = "x'); DROP TABLE artikel; --"
    a = buat_artikel("inj", judul=jahat, media="Robert'); DROP TABLE kemunculan;--")
    run = repo.mulai_run("manual")
    repo.simpan_feed(run, f"keyword:{jahat}", [a])
    repo.tambah_keyword(jahat)
    assert "artikel" in repo.tabel() and "kemunculan" in repo.tabel()
    assert repo.artikel_terbaru(f"keyword:{jahat}")[0]["judul"] == jahat
    assert jahat in repo.keyword_aktif()
    assert repo.artikel_terbaru("keyword:%", prefix=False) == []  # wildcard tidak bocor


def test_keyword_yatim_dinonaktifkan(repo):
    repo.daftar_pengguna(1, "A")
    repo.tambah_keyword("uny", aktif=True, dari_cli=True)
    repo.tambah_pantauan(1, normalisasi_keyword("Banjir  Jogja"))
    assert repo.keyword_aktif() == ["banjir jogja", "uny"]
    assert repo.hapus_pantauan(1, "banjir jogja")
    assert repo.keyword_aktif() == ["uny"]  # 'uny' disimpan via CLI, tetap aktif


def test_run_tercatat(repo):
    run = repo.mulai_run("jadwal")
    repo.selesai_run(run, "sebagian", 9, 12, "topik:sains: timeout")
    r = repo.run_terakhir()
    assert (r["mode"], r["status"], r["jumlah_feed"], r["artikel_baru"]) == ("jadwal", "sebagian", 9, 12)
    assert r["selesai"] is not None


def test_tandai_keyword_tidak_dobel(repo):
    run = repo.mulai_run("manual")
    a = buat_artikel("k")
    repo.simpan_feed(run, "utama", [a])
    assert repo.tandai_keyword(run, "uny", [a.id]) == 1
    assert repo.tandai_keyword(run, "uny", [a.id]) == 0
    assert [b["id"] for b in repo.artikel_untuk_pencarian(ids=[a.id])] == [a.id]


def test_hapus_artikel_sebelum_tanggal(repo):
    from datetime import date, datetime

    from pantauberita.config import WIB

    lama = buat_artikel("lama", terbit=datetime(2026, 11, 5, 9, 0, tzinfo=WIB))
    baru = buat_artikel("baru", terbit=datetime(2026, 11, 14, 0, 5, tzinfo=WIB))
    run = repo.mulai_run("manual")
    repo.simpan_feed(run, "utama", [lama, baru])
    repo.tandai_terkirim(1, [lama.id])
    assert repo.hapus_artikel_sebelum(date(2026, 11, 14)) == 1
    assert repo.jumlah_artikel() == 1 and repo.jumlah_kemunculan() == 1
    assert repo.artikel_terbaru()[0]["id"] == baru.id
