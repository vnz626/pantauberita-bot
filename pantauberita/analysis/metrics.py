"""Metrik tren berita (fungsi murni di atas DataFrame).

DataFrame masukan berisi satu baris per pasangan (artikel, feed) dengan kolom:
id, judul, media, terbit, sentimen, feed. Panggil `siapkan_df` dulu agar kolom
`terbit` menjadi datetime WIB dan ada kolom `tanggal`.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta

import pandas as pd

from pantauberita.analysis.text import token_dan_bigram
from pantauberita.config import WIB

HARI_PEMBANDING = 7


def hari_ini() -> date:
    return datetime.now(WIB).date()


def siapkan_df(df: pd.DataFrame) -> pd.DataFrame:
    """Konversi `terbit` ke datetime WIB dan tambahkan kolom `tanggal` (datetime.date)."""
    df = df.copy()
    for kolom in ("id", "judul", "media", "terbit", "sentimen", "feed"):
        if kolom not in df.columns:
            df[kolom] = pd.Series(dtype="object")
    if df.empty:
        df["terbit"] = pd.Series(dtype="datetime64[ns, Asia/Jakarta]")
        df["tanggal"] = pd.Series(dtype="object")
        return df
    df["terbit"] = pd.to_datetime(df["terbit"], utc=True, format="ISO8601").dt.tz_convert(WIB)
    df["tanggal"] = df["terbit"].dt.date
    df["sentimen"] = pd.to_numeric(df["sentimen"], errors="coerce")
    return df


def unik(df: pd.DataFrame) -> pd.DataFrame:
    """Satu baris per artikel."""
    return df.drop_duplicates("id")


def filter_feed(df: pd.DataFrame, feed: str | None) -> pd.DataFrame:
    """feed=None: semua. feed berakhiran ':' (mis. 'topik:'): prefix. Lainnya: sama persis."""
    if feed is None:
        return df
    if feed.endswith(":"):
        return df[df["feed"].astype(str).str.startswith(feed)]
    return df[df["feed"] == feed]


def jumlah_per_hari(df: pd.DataFrame, feed: str | None = None) -> pd.DataFrame:
    """Jumlah artikel per hari. feed=None -> kolom 'total'; prefix/feed -> satu kolom per feed."""
    if df.empty:
        return pd.DataFrame()
    if feed is None:
        hasil = unik(df).groupby("tanggal").size().to_frame("total")
    else:
        sub = filter_feed(df, feed).drop_duplicates(["id", "feed"])
        if sub.empty:
            return pd.DataFrame()
        hasil = sub.groupby(["tanggal", "feed"]).size().unstack(fill_value=0)
    rentang = pd.date_range(min(hasil.index), max(hasil.index), freq="D").date
    hasil = hasil.reindex(rentang, fill_value=0)
    hasil.index.name = "tanggal"
    return hasil


def top_media(df: pd.DataFrame, n: int = 10, hari: int = 7, acuan: date | None = None) -> pd.Series:
    """Media dengan artikel terbanyak dalam `hari` hari terakhir (s.d. `acuan`)."""
    if df.empty:
        return pd.Series(dtype="int64", name="jumlah")
    acuan = acuan or hari_ini()
    awal = acuan - timedelta(days=hari - 1)
    u = unik(df)
    u = u[(u["tanggal"] >= awal) & (u["tanggal"] <= acuan)]
    hasil = u.groupby("media").size().sort_values(ascending=False, kind="stable").head(n)
    hasil.name = "jumlah"
    return hasil


def distribusi_topik(df: pd.DataFrame, tanggal: date) -> pd.Series:
    """Jumlah artikel per topik (dari feed topik:*) pada satu hari."""
    sub = filter_feed(df, "topik:")
    if sub.empty:
        return pd.Series(dtype="int64", name="jumlah")
    sub = sub[sub["tanggal"] == tanggal].drop_duplicates(["id", "feed"])
    hasil = sub.groupby(sub["feed"].str.removeprefix("topik:")).size().sort_values(ascending=False, kind="stable")
    hasil.index.name = "topik"
    hasil.name = "jumlah"
    return hasil


def _hitung_kata_per_hari(df: pd.DataFrame, tanggal_list: list[date]) -> dict[date, Counter[str]]:
    u = unik(df)
    u = u[u["tanggal"].isin(tanggal_list)]
    hasil: dict[date, Counter[str]] = {t: Counter() for t in tanggal_list}
    for tgl, judul in zip(u["tanggal"], u["judul"]):
        hasil[tgl].update(set(token_dan_bigram(str(judul))))  # satu judul dihitung sekali per kata
    return hasil


def kata_trending(df: pd.DataFrame, tanggal: date, n: int = 15, min_hari_ini: int = 3) -> pd.DataFrame:
    """Kata/bigram yang naik paling tajam: skor = (hari_ini+1)/(rata_rata_7_hari+1)."""
    kolom = ["kata", "hari_ini", "rata_rata", "skor"]
    if df.empty:
        return pd.DataFrame(columns=kolom)
    sebelumnya = [tanggal - timedelta(days=i) for i in range(1, HARI_PEMBANDING + 1)]
    hitung = _hitung_kata_per_hari(df, [tanggal, *sebelumnya])
    baris = []
    for kata, jumlah in hitung[tanggal].items():
        if jumlah < min_hari_ini:
            continue
        rata = sum(hitung[t][kata] for t in sebelumnya) / HARI_PEMBANDING
        baris.append((kata, jumlah, round(rata, 2), round((jumlah + 1) / (rata + 1), 2)))
    hasil = pd.DataFrame(baris, columns=kolom)
    if hasil.empty:
        return hasil
    return hasil.sort_values(["skor", "hari_ini", "kata"], ascending=[False, False, True]).head(n).reset_index(drop=True)


def jumlah_keyword_per_hari(df: pd.DataFrame, keyword: str) -> pd.Series:
    sub = filter_feed(df, f"keyword:{keyword}").drop_duplicates("id")
    return sub.groupby("tanggal").size()


def lonjakan_keyword(df: pd.DataFrame, keyword: str, tanggal: date | None = None) -> bool:
    """True jika artikel hari ini >= 2x rata-rata 7 hari sebelumnya dan >= 5 artikel."""
    if df.empty:
        return False
    tanggal = tanggal or hari_ini()
    per_hari = jumlah_keyword_per_hari(df, keyword)
    hari_itu = int(per_hari.get(tanggal, 0))
    rata = sum(int(per_hari.get(tanggal - timedelta(days=i), 0)) for i in range(1, HARI_PEMBANDING + 1))
    rata /= HARI_PEMBANDING
    return hari_itu >= 5 and hari_itu >= 2 * rata


def sentimen_harian(df: pd.DataFrame, feed: str | None = None) -> pd.Series:
    """Rata-rata sentimen per hari."""
    sub = unik(filter_feed(df, feed)) if feed else unik(df)
    if sub.empty:
        return pd.Series(dtype="float64", name="sentimen")
    hasil = sub.groupby("tanggal")["sentimen"].mean().round(3)
    hasil.name = "sentimen"
    return hasil


def _angka(x: float) -> str:
    return f"{x:+.2f}".replace(".", ",")


def label_sentimen(nilai: float) -> str:
    if nilai > 0.05:
        return "positif"
    if nilai < -0.05:
        return "negatif"
    return "netral"


def temuan(df: pd.DataFrame, tanggal: date) -> list[str]:
    """3-5 kalimat temuan otomatis untuk satu hari."""
    if df.empty:
        return ["Belum ada berita untuk tanggal ini."]
    hari = unik(df)
    hari = hari[hari["tanggal"] == tanggal]
    if hari.empty:
        return ["Belum ada berita untuk tanggal ini."]

    kalimat = [f"Total {len(hari)} berita terbit hari ini dari {hari['media'].nunique()} media."]
    topik = distribusi_topik(df, tanggal)
    if not topik.empty:
        kalimat.append(f"Topik terbanyak hari ini: {topik.index[0]} ({int(topik.iloc[0])} berita).")
    media = hari.groupby("media").size().sort_values(ascending=False, kind="stable")
    kalimat.append(f"Media paling aktif hari ini: {media.index[0]} ({int(media.iloc[0])} berita).")
    trending = kata_trending(df, tanggal, n=3)
    if not trending.empty:
        kalimat.append("Kata yang sedang naik: " + ", ".join(trending["kata"]) + ".")
    rata = hari["sentimen"].mean()
    if pd.notna(rata):
        kalimat.append(f"Sentimen rata-rata judul berita cenderung {label_sentimen(rata)} ({_angka(rata)}).")
    return kalimat[:5]
