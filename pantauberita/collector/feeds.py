"""Daftar sumber (RSS & news sitemap resmi media) dan pembangun daftar feed (fungsi murni).

Semua sumber di bawah dicek robots.txt-nya pada 17 Nov 2026 (user-agent umum diizinkan);
pipeline tetap mengecek ulang robots.txt setiap kali jalan.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from types import MappingProxyType
from urllib.parse import urlsplit

from pantauberita.config import TOPIK


@dataclass(frozen=True)
class Sumber:
    media: str
    url: str


@dataclass(frozen=True)
class Feed:
    """Satu URL yang akan diambil.

    label  : nama feed di tabel kemunculan ('utama', 'topik:teknologi'); untuk sitemap hanya
             label tampilan ('sitemap:detik.com') karena tiap artikel diberi topik dari URL-nya
    jenis  : 'rss' atau 'sitemap'
    rentang: untuk backfill, hanya item dengan tanggal terbit (WIB) di dalam rentang ini yang disimpan
    """

    label: str
    url: str
    media: str
    jenis: str = "rss"
    rentang: tuple[date, date] | None = None


# ---------------------------------------------------------------------- daftar sumber
SUMBER_UTAMA: tuple[Sumber, ...] = (
    Sumber("ANTARA", "https://www.antaranews.com/rss/terkini.xml"),
    Sumber("CNN Indonesia", "https://www.cnnindonesia.com/rss"),
    Sumber("detikNews", "https://news.detik.com/rss"),
    Sumber("CNBC Indonesia", "https://www.cnbcindonesia.com/rss"),
    Sumber("VIVA", "https://www.viva.co.id/get/all"),
    Sumber("Republika", "https://www.republika.co.id/rss"),
    Sumber("JPNN", "https://www.jpnn.com/index.php?mib=rss"),
)

SUMBER_TOPIK: Mapping[str, tuple[Sumber, ...]] = MappingProxyType(
    {
        "NATION": (
            Sumber("CNN Indonesia", "https://www.cnnindonesia.com/nasional/rss"),
            Sumber("detikNews", "https://news.detik.com/berita/rss"),
            Sumber("VIVA", "https://www.viva.co.id/get/berita"),
        ),
        "WORLD": (
            Sumber("CNN Indonesia", "https://www.cnnindonesia.com/internasional/rss"),
            Sumber("detikNews", "https://news.detik.com/internasional/rss"),
            Sumber("VIVA", "https://www.viva.co.id/get/dunia"),
        ),
        "BUSINESS": (
            Sumber("CNN Indonesia", "https://www.cnnindonesia.com/ekonomi/rss"),
            Sumber("detikFinance", "https://finance.detik.com/rss"),
            Sumber("CNBC Indonesia", "https://www.cnbcindonesia.com/market/rss"),
            Sumber("VIVA", "https://www.viva.co.id/get/bisnis"),
        ),
        "TECHNOLOGY": (
            Sumber("CNN Indonesia", "https://www.cnnindonesia.com/teknologi/rss"),
            Sumber("detikInet", "https://inet.detik.com/rss"),
            Sumber("CNBC Indonesia", "https://www.cnbcindonesia.com/tech/rss"),
            Sumber("VIVA", "https://www.viva.co.id/get/digital"),
        ),
        "ENTERTAINMENT": (
            Sumber("CNN Indonesia", "https://www.cnnindonesia.com/hiburan/rss"),
            Sumber("detikHot", "https://hot.detik.com/rss"),
            Sumber("VIVA", "https://www.viva.co.id/get/showbiz"),
        ),
        "SPORTS": (
            Sumber("CNN Indonesia", "https://www.cnnindonesia.com/olahraga/rss"),
            Sumber("detikSport", "https://sport.detik.com/rss"),
            Sumber("VIVA", "https://www.viva.co.id/get/sport"),
        ),
        "SCIENCE": (
            Sumber("detikEdu", "https://www.detik.com/edu/rss"),
            Sumber("ANTARA", "https://www.antaranews.com/rss/warta-bumi.xml"),
        ),
        "HEALTH": (
            Sumber("detikHealth", "https://health.detik.com/rss"),
            Sumber("CNN Indonesia", "https://www.cnnindonesia.com/gaya-hidup/rss"),
        ),
    }
)

#: News sitemap (format Google News sitemap: judul + tanggal terbit asli, ±2-4 hari terakhir).
SITEMAP_BACKFILL: Mapping[str, tuple[Sumber, ...]] = MappingProxyType(
    {
        "detik.com": tuple(
            Sumber(nama, f"https://{sub}.detik.com/sitemap_news.xml")
            for sub, nama in (
                ("news", "detikNews"),
                ("finance", "detikFinance"),
                ("sport", "detikSport"),
                ("hot", "detikHot"),
                ("inet", "detikInet"),
                ("health", "detikHealth"),
            )
        ),
        "cnnindonesia.com": tuple(
            Sumber("CNN Indonesia", f"https://www.cnnindonesia.com/{k}/sitemap_news.xml")
            for k in ("nasional", "internasional", "ekonomi", "olahraga", "teknologi", "hiburan", "gaya-hidup")
        ),
        "cnbcindonesia.com": tuple(
            Sumber("CNBC Indonesia", f"https://www.cnbcindonesia.com/{k}/sitemap_news.xml")
            for k in ("news", "market", "tech")
        ),
        "viva.co.id": (Sumber("VIVA", "https://www.viva.co.id/sitemap/news/news-sitemap.xml"),),
    }
)


# ---------------------------------------------------------------------- topik dari URL
#: Subdomain detik -> label topik.
_TOPIK_SUBDOMAIN: Mapping[str, str] = MappingProxyType(
    {"finance": "bisnis", "sport": "olahraga", "hot": "hiburan", "inet": "teknologi", "health": "kesehatan"}
)
#: Segmen path spesifik -> label topik (dicek lebih dulu).
_TOPIK_SPESIFIK: Mapping[str, str] = MappingProxyType(
    {
        **dict.fromkeys(("internasional", "dunia", "world"), "dunia"),
        **dict.fromkeys(("ekonomi", "bisnis", "market", "finance", "berita-ekonomi-bisnis", "energi"), "bisnis"),
        **dict.fromkeys(("teknologi", "tech", "tekno", "digital", "digilife", "inet", "gadget"), "teknologi"),
        **dict.fromkeys(("hiburan", "showbiz", "hot", "seleb", "celeb", "entertainment", "film", "musik"), "hiburan"),
        **dict.fromkeys(("olahraga", "sport", "bola", "sepakbola", "motogp", "raket"), "olahraga"),
        **dict.fromkeys(("kesehatan", "health"), "kesehatan"),
        **dict.fromkeys(("sains", "science", "edu"), "sains"),
    }
)
#: Segmen path umum -> label topik (dipakai bila tidak ada yang spesifik).
_TOPIK_UMUM: Mapping[str, str] = MappingProxyType(
    {
        **dict.fromkeys(("nasional", "berita", "news", "politik", "hukum"), "nasional"),
        "gaya-hidup": "kesehatan",  # konsisten dengan pemetaan RSS CNN gaya-hidup -> kesehatan
    }
)


def topik_dari_url(link: str) -> str | None:
    """Tebak label topik dari URL artikel (subdomain/segmen path). None jika tidak bisa ditebak."""
    bagian = urlsplit(link)
    sub = bagian.netloc.lower().split(".")[0]
    if bagian.netloc.lower().endswith("detik.com") and sub in _TOPIK_SUBDOMAIN:
        return _TOPIK_SUBDOMAIN[sub]
    segmen = [s.lower() for s in bagian.path.split("/") if s][:-1]  # segmen terakhir = slug judul
    for s in segmen:
        if s in _TOPIK_SPESIFIK:
            return _TOPIK_SPESIFIK[s]
    for s in segmen:
        if s in _TOPIK_UMUM:
            return _TOPIK_UMUM[s]
    return None


def label_dari_url(link: str) -> str:
    """Label feed untuk artikel hasil backfill: 'topik:{x}', atau 'utama' bila topik tak dikenali."""
    topik = topik_dari_url(link)
    return f"topik:{topik}" if topik else "utama"


# ---------------------------------------------------------------------- fungsi murni
def normalisasi_keyword(teks: str) -> str:
    """Lowercase dan spasi tunggal."""
    return " ".join(teks.lower().split())


def kode_topik(nama: str) -> str:
    """Terima label ('teknologi') atau kode ('TECHNOLOGY'); kembalikan kode. Lempar ValueError bila tak dikenal."""
    n = nama.strip()
    if n.upper() in TOPIK:
        return n.upper()
    for kode, label in TOPIK.items():
        if label == n.lower():
            return kode
    raise ValueError(f"Topik tidak dikenal: {nama!r}. Pilihan: {', '.join(TOPIK.values())}")


def feeds_utama() -> list[Feed]:
    return [Feed("utama", s.url, s.media) for s in SUMBER_UTAMA]


def feeds_topik(kode: str) -> list[Feed]:
    kode = kode_topik(kode)
    return [Feed(f"topik:{TOPIK[kode]}", s.url, s.media) for s in SUMBER_TOPIK.get(kode, ())]


def bangun_feeds(*, topik_aktif: Sequence[str], topik: Sequence[str] | None = None) -> list[Feed]:
    """Daftar feed satu kali jalan.

    - `topik` diberikan: hanya feed topik tersebut.
    - Tidak: utama + semua topik aktif.
    URL yang sama hanya diambil sekali.
    """
    feeds: list[Feed] = []
    if topik:
        for t in topik:
            feeds += feeds_topik(t)
    else:
        feeds += feeds_utama()
        for kode in topik_aktif:
            feeds += feeds_topik(kode)
    unik: dict[str, Feed] = {}
    for f in feeds:
        unik.setdefault(f.url, f)
    return list(unik.values())


def daftar_tanggal_backfill(hari_ini: date, hari: int | None = None, sejak: date | None = None) -> list[date]:
    """Tanggal yang di-backfill: N hari ke belakang, atau `sejak` s.d. kemarin."""
    kemarin = hari_ini - timedelta(days=1)
    if sejak is not None:
        awal = sejak
    elif hari is not None and hari > 0:
        awal = hari_ini - timedelta(days=hari)
    else:
        return []
    jumlah = (kemarin - awal).days + 1
    return [awal + timedelta(days=i) for i in range(max(0, jumlah))]


def bangun_feeds_backfill(tanggal: Sequence[date], media: Iterable[str]) -> list[Feed]:
    """Satu feed per news sitemap untuk tiap domain di `media` (domain tak dikenal diabaikan).

    Artikel sitemap TIDAK disimpan dengan label 'backfill', melainkan diberi label topik dari URL-nya
    (lihat `label_dari_url`). Asal backfill tetap tercatat lewat scrape_run.mode = 'backfill'.
    """
    if not tanggal:
        return []
    rentang = (min(tanggal), max(tanggal))
    feeds: list[Feed] = []
    for domain in media:
        for s in SITEMAP_BACKFILL.get(domain, ()):
            feeds.append(Feed(f"sitemap:{domain}", s.url, s.media, "sitemap", rentang))
    return feeds


def semua_url() -> list[str]:
    """Seluruh URL sumber (untuk dokumentasi/cek manual)."""
    urls = [s.url for s in SUMBER_UTAMA]
    urls += [s.url for daftar in SUMBER_TOPIK.values() for s in daftar]
    urls += [s.url for daftar in SITEMAP_BACKFILL.values() for s in daftar]
    return urls
