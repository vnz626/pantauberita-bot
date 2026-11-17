from datetime import datetime

from pantauberita.config import ATRIBUSI_SINGKAT, WIB
from pantauberita.telegram import messages

SEKARANG = datetime(2026, 11, 17, 20, 0, tzinfo=WIB)


def item(i: int, judul: str = "Judul", media: str = "Media", link: str = "https://x.test/a?b=1&c=2"):
    return {"judul": judul, "media": media, "link": link, "terbit": f"2026-11-17T14:{i % 60:02d}:00+07:00"}


def test_format_berita_escape_html():
    teks = messages.format_berita(item(20, judul="<b>Bos</b> & Co", media="A&B"), SEKARANG)
    assert "&lt;b&gt;Bos&lt;/b&gt; &amp; Co" in teks
    assert 'href="https://x.test/a?b=1&amp;c=2"' in teks
    assert teks.endswith("(A&amp;B, 14:20)")
    assert teks.startswith("• <a ")


def test_batas_10_berita_dan_sumber():
    teks = messages.format_daftar_berita("Header", [item(i) for i in range(25)], sekarang=SEKARANG)
    assert teks.count("• <a ") == 10
    assert teks.rstrip().endswith(f"{ATRIBUSI_SINGKAT}</i>")


def test_pesan_tidak_melebihi_batas_telegram():
    panjang = [item(i, judul="J" * 300, link="https://x.test/" + "a" * 600) for i in range(10)]
    teks = messages.format_daftar_berita("Header", panjang, sekarang=SEKARANG)
    assert len(teks) <= 4096
    assert ATRIBUSI_SINGKAT in teks


def test_pesan_saat_kosong():
    teks = messages.format_daftar_berita("Header", [], "topik sains")
    assert "Belum ada berita untuk topik sains" in teks
    assert "/perbarui" in teks and ATRIBUSI_SINGKAT in teks


def test_waktu_hari_lain_menyertakan_tanggal():
    i = {**item(0), "terbit": "2026-11-16T09:05:00+07:00"}
    assert messages.format_berita(i, SEKARANG).endswith("(Media, 16 Nov 09:05)")


def test_bantuan_dan_notifikasi():
    assert "/pantau" in messages.pesan_bantuan("Ani") and "hak cipta" in messages.pesan_bantuan()
    n = messages.format_notifikasi("banjir", [item(1)], sisa=3, lonjakan=True, sekarang=SEKARANG)
    assert "Isu ini sedang ramai" in n and "+3 berita lain" in n
