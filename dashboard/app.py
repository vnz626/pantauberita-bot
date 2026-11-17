"""Dashboard Streamlit PantauBerita. Jalankan: streamlit run dashboard/app.py"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402
from wordcloud import WordCloud  # noqa: E402

from pantauberita.analysis import metrics  # noqa: E402
from pantauberita.analysis.text import tokenisasi  # noqa: E402
from pantauberita.config import ATRIBUSI, load_config  # noqa: E402
from pantauberita.storage.repo import Repo  # noqa: E402

st.set_page_config(page_title="PantauBerita", page_icon="📰", layout="wide")


@st.cache_data(ttl=300)
def muat_data(db_path: str) -> pd.DataFrame:
    """Seluruh pasangan (artikel, feed) dari database."""
    with Repo(db_path) as repo:
        repo.init_db()
        return metrics.siapkan_df(repo.artikel_df())


def saring(df: pd.DataFrame, awal: date, akhir: date, topik: list[str], media: list[str],
           keyword: list[str], cari: str) -> pd.DataFrame:
    """Terapkan filter sidebar. Filter topik/keyword memilih artikel yang muncul di feed tersebut."""
    hasil = df[(df["tanggal"] >= awal) & (df["tanggal"] <= akhir)]
    if media:
        hasil = hasil[hasil["media"].isin(media)]
    if cari:
        hasil = hasil[hasil["judul"].str.contains(cari, case=False, regex=False)]
    feed_dipilih = [f"topik:{t}" for t in topik] + [f"keyword:{k}" for k in keyword]
    if feed_dipilih:
        ids = set(hasil.loc[hasil["feed"].isin(feed_dipilih), "id"])
        hasil = hasil[hasil["id"].isin(ids)]
    return hasil


def main() -> None:
    cfg = load_config()
    df = muat_data(str(cfg.db_path))
    st.title("📰 PantauBerita")
    st.caption(ATRIBUSI + ". Hanya metadata (judul, media, waktu, tautan).")

    if df.empty:
        st.info("Belum ada data. Jalankan `python scraping.py` atau `python scraping.py --backfill 7` dulu.")
        return

    feeds = sorted(df["feed"].unique())
    semua_topik = [f.removeprefix("topik:") for f in feeds if f.startswith("topik:")]
    semua_keyword = [f.removeprefix("keyword:") for f in feeds if f.startswith("keyword:")]
    tgl_min, tgl_max = min(df["tanggal"]), max(df["tanggal"])

    with st.sidebar:
        st.header("Filter")
        rentang = st.date_input("Rentang tanggal", (max(tgl_min, tgl_max - timedelta(days=13)), tgl_max),
                                min_value=tgl_min, max_value=tgl_max)
        awal, akhir = (rentang if isinstance(rentang, tuple) and len(rentang) == 2 else (tgl_min, tgl_max))
        topik = st.multiselect("Topik", semua_topik)
        media = st.multiselect("Media", sorted(df["media"].unique()))
        keyword = st.multiselect("Keyword", semua_keyword)
        cari = st.text_input("Cari judul")
        if st.button("Muat ulang data"):
            muat_data.clear()
            st.rerun()

    data = saring(df, awal, akhir, topik, media, keyword, cari.strip())
    u = metrics.unik(data)
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Total artikel", f"{len(u):,}".replace(",", "."))
    k2.metric("Artikel hari ini", int((u["tanggal"] == akhir).sum()))
    k3.metric("Jumlah media", u["media"].nunique())
    rata = u["sentimen"].mean()
    k4.metric("Sentimen rata-rata", f"{rata:+.3f}" if pd.notna(rata) else "-")

    t_tren, t_media, t_trending, t_keyword, t_data = st.tabs(["Tren", "Media", "Trending", "Keyword", "Data"])

    with t_tren:
        st.subheader("Jumlah artikel per topik")
        per_topik = metrics.jumlah_per_hari(data, "topik:")
        if per_topik.empty:
            st.info("Belum ada data feed topik pada rentang ini.")
        else:
            st.line_chart(per_topik.rename(columns=lambda c: c.removeprefix("topik:")))
        st.subheader("Jumlah artikel per hari (semua feed)")
        total = metrics.jumlah_per_hari(data)
        if not total.empty:
            st.bar_chart(total)
        sent = metrics.sentimen_harian(data)
        if not sent.empty:
            st.subheader("Sentimen rata-rata per hari")
            st.line_chart(sent)

    with t_media:
        hari = (akhir - awal).days + 1
        top = metrics.top_media(data, 15, hari, akhir)
        st.subheader(f"Media paling aktif ({hari} hari)")
        if top.empty:
            st.info("Tidak ada data.")
        else:
            st.bar_chart(top.sort_values(), horizontal=True)

    with t_trending:
        tren = metrics.kata_trending(data if not cari else df, akhir)
        st.subheader(f"Kata trending {akhir:%d-%m-%Y}")
        if tren.empty:
            st.info("Belum ada kata yang menonjol (minimal muncul 3× pada hari itu).")
        else:
            st.bar_chart(tren.set_index("kata")["skor"].sort_values(), horizontal=True)
            st.dataframe(tren, hide_index=True, use_container_width=True)
        frek = pd.Series([t for j in u.loc[u["tanggal"] == akhir, "judul"] for t in tokenisasi(str(j))]).value_counts()
        if not frek.empty:
            wc = WordCloud(width=1000, height=400, background_color="white", random_state=42)
            wc.generate_from_frequencies(frek.to_dict())
            fig, ax = plt.subplots(figsize=(10, 4))
            ax.imshow(wc, interpolation="bilinear")
            ax.axis("off")
            st.pyplot(fig)
            plt.close(fig)

    with t_keyword:
        per_kw = metrics.jumlah_per_hari(data, "keyword:")
        if per_kw.empty:
            st.info("Belum ada data keyword. Tambahkan dengan `--keyword ... --simpan-keyword` atau /pantau di bot.")
        else:
            st.line_chart(per_kw.rename(columns=lambda c: c.removeprefix("keyword:")))
            for kw in [c.removeprefix("keyword:") for c in per_kw.columns]:
                if metrics.lonjakan_keyword(df, kw, akhir):
                    st.warning(f"Isu **{kw}** sedang ramai (≥2× rata-rata 7 hari).")

    with t_data:
        urut = u.sort_values("terbit", ascending=False)
        feed_per_id = data.groupby("id")["feed"].agg(lambda s: ", ".join(sorted(set(s))))
        tabel = urut[["terbit", "judul", "media", "sentimen", "link"]].copy()
        tabel["feed"] = urut["id"].map(feed_per_id)
        tabel["terbit"] = tabel["terbit"].dt.strftime("%Y-%m-%d %H:%M")
        st.dataframe(tabel, hide_index=True, use_container_width=True,
                     column_config={"link": st.column_config.LinkColumn("link", display_text="buka")})
        # data berupa callable: CSV baru dibuat & dikirim saat tombol diklik, bukan setiap halaman
        # di-render (sebelumnya file ikut terambil tiap ganti filter -> sebagian browser langsung mengunduh).
        st.download_button(
            "Unduh CSV",
            data=lambda: tabel.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"pantauberita_{awal}_{akhir}.csv",
            mime="text/csv",
            on_click="ignore",
        )

    st.caption(ATRIBUSI)


main()
