from datetime import date

from conftest import buat_artikel

from pantauberita.telegram.jobs import MAKS_PER_KEYWORD, jam_jadwal, kumpulkan_notifikasi
from pantauberita.config import WIB
from datetime import time


def test_artikel_terkirim_tidak_dikirim_ulang(repo):
    repo.daftar_pengguna(1, "Ani")
    repo.daftar_pengguna(2, "Budi")
    repo.tambah_pantauan(1, "banjir")
    repo.tambah_pantauan(2, "banjir")
    run = repo.mulai_run("bot")
    repo.simpan_feed(run, "keyword:banjir", [buat_artikel(f"b{i}") for i in range(7)])

    pertama = kumpulkan_notifikasi(repo, run, tanggal=date(2026, 11, 17))
    assert {n.chat_id for n in pertama} == {1, 2}
    n1 = next(n for n in pertama if n.chat_id == 1)
    assert len(n1.items) == MAKS_PER_KEYWORD and n1.sisa == 2 and len(n1.ids) == 7

    repo.tandai_terkirim(1, n1.ids)  # hanya chat 1 yang sudah dikirimi
    kedua = kumpulkan_notifikasi(repo, run, tanggal=date(2026, 11, 17))
    assert [n.chat_id for n in kedua] == [2]

    # run berikutnya membawa 1 artikel lama + 1 baru -> chat 1 hanya menerima yang baru
    run2 = repo.mulai_run("bot")
    repo.simpan_feed(run2, "keyword:banjir", [buat_artikel("b0"), buat_artikel("baru")])
    ketiga = [n for n in kumpulkan_notifikasi(repo, run2, tanggal=date(2026, 11, 17)) if n.chat_id == 1]
    assert [a["link"] for a in ketiga[0].items] == ["https://contoh.test/baru"]


def test_pengguna_memblokir_bot_dibersihkan(repo):
    repo.daftar_pengguna(5, "C")
    repo.set_langganan(5, True)
    repo.tambah_pantauan(5, "uny")
    repo.nonaktifkan_pengguna(5)
    assert repo.pelanggan_laporan() == [] and repo.pantauan_pengguna(5) == []
    assert repo.keyword_aktif() == []


def test_jam_jadwal_tiap_3_jam_mulai_06():
    jam = jam_jadwal(time(6, 0), 3)
    assert [f"{t:%H:%M}" for t in jam] == ["00:00", "03:00", "06:00", "09:00", "12:00", "15:00", "18:00", "21:00"]
    assert all(t.tzinfo == WIB for t in jam)
