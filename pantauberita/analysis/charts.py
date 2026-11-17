"""Grafik PNG (matplotlib) dan wordcloud ke folder output/."""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Sequence
from datetime import date, timedelta
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from wordcloud import WordCloud  # noqa: E402

from pantauberita.analysis import metrics  # noqa: E402
from pantauberita.analysis.text import tokenisasi  # noqa: E402
from pantauberita.config import ATRIBUSI_SINGKAT  # noqa: E402

log = logging.getLogger(__name__)

WARNA = ["#2a6fdb", "#e4572e", "#29a36a", "#f3a712", "#8e44ad", "#17a2b8", "#d63384", "#6c757d"]
DPI = 120


def _simpan(fig: plt.Figure, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.text(0.99, 0.01, ATRIBUSI_SINGKAT, ha="right", va="bottom", fontsize=7, color="#777777")
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(path, dpi=DPI)
    plt.close(fig)
    return path


def _kosong(judul: str, path: Path) -> Path:
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.axis("off")
    ax.set_title(judul)
    ax.text(0.5, 0.5, "Belum ada data", ha="center", va="center", fontsize=14, color="#888888")
    return _simpan(fig, path)


def _garis(data: pd.DataFrame, judul: str, path: Path, hari: int, acuan: date) -> Path:
    awal = acuan - timedelta(days=hari - 1)
    rentang = pd.date_range(awal, acuan, freq="D").date
    data = data.reindex(rentang, fill_value=0) if not data.empty else data
    if data.empty or data.to_numpy().sum() == 0:
        return _kosong(judul, path)
    fig, ax = plt.subplots(figsize=(10, 5))
    for i, kolom in enumerate(data.columns):
        label = str(kolom).split(":", 1)[-1]
        ax.plot(list(data.index), data[kolom], marker="o", markersize=3, label=label, color=WARNA[i % len(WARNA)])
    ax.set_title(judul)
    ax.set_ylabel("Jumlah artikel")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8, ncol=2)
    fig.autofmt_xdate()
    return _simpan(fig, path)


def grafik_topik(df: pd.DataFrame, path: Path, acuan: date, hari: int = 14) -> Path:
    """Garis jumlah artikel per topik (hanya data feed topik:*)."""
    return _garis(metrics.jumlah_per_hari(df, "topik:"), f"Jumlah artikel per topik ({hari} hari)", path, hari, acuan)


def grafik_keyword(df: pd.DataFrame, keywords: Sequence[str], path: Path, acuan: date, hari: int = 14) -> Path:
    """Garis jumlah artikel per keyword yang dipantau."""
    data = metrics.jumlah_per_hari(df, "keyword:")
    if not data.empty and keywords:
        data = data[[c for c in data.columns if c.removeprefix("keyword:") in set(keywords)]]
    return _garis(data, f"Jumlah artikel per keyword ({hari} hari)", path, hari, acuan)


def _bar_h(nilai: pd.Series, judul: str, path: Path, xlabel: str) -> Path:
    if nilai.empty:
        return _kosong(judul, path)
    nilai = nilai.iloc[::-1]
    fig, ax = plt.subplots(figsize=(9, max(3, 0.45 * len(nilai) + 1)))
    ax.barh([str(i) for i in nilai.index], nilai.values, color=WARNA[0])
    ax.set_title(judul)
    ax.set_xlabel(xlabel)
    ax.grid(axis="x", alpha=0.3)
    return _simpan(fig, path)


def grafik_media(df: pd.DataFrame, path: Path, acuan: date) -> Path:
    """Bar horizontal 10 media teratas (7 hari)."""
    return _bar_h(metrics.top_media(df, 10, 7, acuan), "10 media paling aktif (7 hari)", path, "Jumlah artikel")


def grafik_trending(df: pd.DataFrame, tanggal: date, path: Path) -> Path:
    """Bar kata trending hari ini."""
    tren = metrics.kata_trending(df, tanggal)
    nilai = pd.Series(tren["skor"].to_numpy(), index=tren["kata"]) if not tren.empty else pd.Series(dtype=float)
    return _bar_h(nilai, f"Kata trending {tanggal:%d-%m-%Y}", path, "Skor kenaikan")


def wordcloud_judul(df: pd.DataFrame, tanggal: date, path: Path) -> Path:
    """Wordcloud judul berita hari ini."""
    judul = f"Wordcloud judul {tanggal:%d-%m-%Y}"
    if df.empty:
        return _kosong(judul, path)
    u = metrics.unik(df)
    frekuensi = Counter(t for j in u.loc[u["tanggal"] == tanggal, "judul"] for t in tokenisasi(str(j)))
    if not frekuensi:
        return _kosong(judul, path)
    wc = WordCloud(width=1000, height=500, background_color="white", colormap="viridis", random_state=42)
    wc.generate_from_frequencies(frekuensi)
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.imshow(wc, interpolation="bilinear")
    ax.axis("off")
    ax.set_title(judul)
    return _simpan(fig, path)


def buat_semua_grafik(
    df: pd.DataFrame, tanggal: date, output_dir: Path, keywords: Sequence[str] = ()
) -> dict[str, Path]:
    """Buat seluruh grafik; kembalikan {nama: path}."""
    akhir = f"{tanggal.isoformat()}.png"
    return {
        "topik": grafik_topik(df, output_dir / f"grafik_topik_{akhir}", tanggal),
        "media": grafik_media(df, output_dir / f"grafik_media_{akhir}", tanggal),
        "trending": grafik_trending(df, tanggal, output_dir / f"grafik_trending_{akhir}"),
        "wordcloud": wordcloud_judul(df, tanggal, output_dir / f"wordcloud_{akhir}"),
        "keyword": grafik_keyword(df, keywords, output_dir / f"grafik_keyword_{akhir}", tanggal),
    }
