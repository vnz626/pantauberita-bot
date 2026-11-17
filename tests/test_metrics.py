from datetime import date, datetime, timedelta

import pandas as pd

from pantauberita.analysis import metrics
from pantauberita.config import WIB

HARI = date(2026, 11, 17)


def baris(i: int, tgl: date, judul: str, feed: str = "utama", media: str = "Media A", sentimen: float = 0.0):
    return {
        "id": f"id{i}",
        "judul": judul,
        "media": media,
        "terbit": datetime(tgl.year, tgl.month, tgl.day, 10, 0, tzinfo=WIB).isoformat(),
        "sentimen": sentimen,
        "feed": feed,
    }


def df_dari(rows):
    return metrics.siapkan_df(pd.DataFrame(rows))


def test_kata_trending_menangkap_lonjakan():
    rows, i = [], 0
    for d in range(1, 8):  # 7 hari sebelumnya: 'pemilu' muncul 2x/hari
        for _ in range(2):
            i += 1
            rows.append(baris(i, HARI - timedelta(days=d), "Debat pemilu ramai"))
    for _ in range(4):  # hari ini 'gempa' muncul 4x (sebelumnya 0); 'pemilu' tetap 2x
        i += 1
        rows.append(baris(i, HARI, "Gempa guncang Cianjur"))
    for _ in range(2):
        i += 1
        rows.append(baris(i, HARI, "Debat pemilu ramai"))
    tren = metrics.kata_trending(df_dari(rows), HARI)
    assert tren.iloc[0]["kata"] in {"gempa", "guncang", "cianjur", "gempa guncang", "guncang cianjur"}
    assert tren.iloc[0]["skor"] == 5.0  # (4+1)/(0+1)
    assert "pemilu" not in set(tren["kata"])  # hanya 2x hari ini (< minimal 3)


def test_lonjakan_keyword_di_batas_2x():
    def buat(hari_ini: int, per_hari: int):
        rows, i = [], 0
        for d in range(1, 8):
            for _ in range(per_hari):
                i += 1
                rows.append(baris(i, HARI - timedelta(days=d), "x", feed="keyword:uny"))
        for _ in range(hari_ini):
            i += 1
            rows.append(baris(i, HARI, "x", feed="keyword:uny"))
        return df_dari(rows)

    assert metrics.lonjakan_keyword(buat(6, 3), "uny", HARI) is True  # tepat 2x rata-rata 3
    assert metrics.lonjakan_keyword(buat(5, 3), "uny", HARI) is False  # < 2x
    assert metrics.lonjakan_keyword(buat(4, 0), "uny", HARI) is False  # < 5 artikel
    assert metrics.lonjakan_keyword(buat(5, 0), "uny", HARI) is True


def test_top_media_urut():
    rows = [baris(i, HARI, "x", media=m) for i, m in enumerate(["B", "A", "B", "C", "B", "A"])]
    rows.append(baris(99, HARI - timedelta(days=10), "x", media="C"))  # di luar 7 hari
    top = metrics.top_media(df_dari(rows), n=10, hari=7, acuan=HARI)
    assert list(top.index) == ["B", "A", "C"]
    assert list(top.values) == [3, 2, 1]


def test_artikel_banyak_feed_dihitung_sekali():
    rows = [baris(1, HARI, "x", feed="utama"), baris(1, HARI, "x", feed="topik:bisnis"), baris(2, HARI, "y")]
    df = df_dari(rows)
    assert int(metrics.jumlah_per_hari(df).loc[HARI, "total"]) == 2
    assert metrics.distribusi_topik(df, HARI).to_dict() == {"bisnis": 1}


def test_temuan_dan_sentimen_harian():
    rows = [baris(i, HARI, "Timnas menang", feed="topik:olahraga", sentimen=1.0) for i in range(3)]
    rows += [baris(10 + i, HARI, "Harga naik", feed="topik:bisnis", media="Media B", sentimen=-1.0) for i in range(2)]
    df = df_dari(rows)
    t = metrics.temuan(df, HARI)
    assert 3 <= len(t) <= 5
    assert "Topik terbanyak hari ini: olahraga (3 berita)." in t
    assert metrics.sentimen_harian(df).loc[HARI] == 0.2
    assert metrics.temuan(df, HARI - timedelta(days=1)) == ["Belum ada berita untuk tanggal ini."]


def test_df_kosong_aman():
    kosong = metrics.siapkan_df(pd.DataFrame(columns=["id", "judul", "media", "terbit", "sentimen", "feed"]))
    assert metrics.kata_trending(kosong, HARI).empty
    assert metrics.top_media(kosong).empty
    assert metrics.lonjakan_keyword(kosong, "x", HARI) is False
