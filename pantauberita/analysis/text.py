"""Analisis teks: tokenisasi, stopwords, bigram, dan sentimen berbasis kamus (fungsi murni)."""

from __future__ import annotations

import re
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path

from pantauberita.config import DATA_DIR

_KATA = re.compile(r"[a-z]+")
MIN_PANJANG = 3


@lru_cache(maxsize=8)
def muat_kata(nama_file: str, folder: Path = DATA_DIR) -> frozenset[str]:
    """Baca daftar kata (satu per baris, '#' = komentar) sebagai frozenset."""
    path = folder / nama_file
    if not path.exists():
        return frozenset()
    kata = set()
    for baris in path.read_text(encoding="utf-8").splitlines():
        baris = baris.strip().lower()
        if baris and not baris.startswith("#"):
            kata.add(baris)
    return frozenset(kata)


def stopwords() -> frozenset[str]:
    return muat_kata("stopwords_id.txt")


def kata_positif() -> frozenset[str]:
    return muat_kata("kata_positif.txt")


def kata_negatif() -> frozenset[str]:
    return muat_kata("kata_negatif.txt")


def kata_mentah(teks: str) -> list[str]:
    """Lowercase lalu ambil huruf saja (tanda baca dan angka hilang)."""
    return _KATA.findall((teks or "").lower())


def tokenisasi(teks: str, stop: Iterable[str] | None = None) -> list[str]:
    """Token bersih: tanpa stopwords dan kata < 3 huruf."""
    stop_set = frozenset(stop) if stop is not None else stopwords()
    return [k for k in kata_mentah(teks) if len(k) >= MIN_PANJANG and k not in stop_set]


def bigram(tokens: list[str]) -> list[str]:
    """Pasangan kata berurutan, mis. ['harga', 'beras'] -> ['harga beras']."""
    return [f"{a} {b}" for a, b in zip(tokens, tokens[1:])]


def token_dan_bigram(teks: str, stop: Iterable[str] | None = None) -> list[str]:
    tokens = tokenisasi(teks, stop)
    return tokens + bigram(tokens)


def sentimen(
    teks: str, positif: Iterable[str] | None = None, negatif: Iterable[str] | None = None
) -> float:
    """(positif - negatif) / jumlah kata yang cocok kamus; 0 jika tidak ada yang cocok."""
    pos = frozenset(positif) if positif is not None else kata_positif()
    neg = frozenset(negatif) if negatif is not None else kata_negatif()
    kata = kata_mentah(teks)
    n_pos = sum(1 for k in kata if k in pos)
    n_neg = sum(1 for k in kata if k in neg)
    total = n_pos + n_neg
    if total == 0:
        return 0.0
    return round((n_pos - n_neg) / total, 4)


def kata_keyword(keyword: str) -> list[str]:
    """Kata-kata penyusun keyword (lowercase, huruf/angka)."""
    return re.findall(r"\w+", (keyword or "").lower())


def cocok_keyword(teks: str, keyword: str) -> bool:
    """True jika SEMUA kata keyword muncul sebagai kata utuh di teks (tidak peka huruf besar)."""
    kata = kata_keyword(keyword)
    if not kata:
        return False
    teks = (teks or "").lower()
    return all(re.search(rf"(?<!\w){re.escape(k)}(?!\w)", teks) for k in kata)
