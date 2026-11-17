"""XML RSS / news sitemap media -> list[Artikel] (fungsi murni)."""

from __future__ import annotations

import hashlib
import html
import io
import logging
import re
import warnings
import xml.etree.ElementTree as ET
from calendar import timegm
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit

import feedparser
from bs4 import BeautifulSoup, MarkupResemblesLocatorWarning

from pantauberita.config import WIB

log = logging.getLogger(__name__)

MEDIA_TIDAK_DIKETAHUI = "Tidak diketahui"
MAKS_RINGKASAN = 300
_SPASI = re.compile(r"\s+")
# Peringatan bozo yang tidak berarti XML rusak.
_BOZO_AMAN = (feedparser.CharacterEncodingOverride, feedparser.NonXMLContentType)
_NS_SITEMAP = {
    "sm": "http://www.sitemaps.org/schemas/sitemap/0.9",
    "news": "http://www.google.com/schemas/sitemap-news/0.9",
}


@dataclass(frozen=True)
class Artikel:
    id: str  # sha1(link ternormalisasi), atau sha1(guid) jika link kosong
    judul: str  # tanpa sufiks " - Nama Media"
    media: str  # nama media
    domain: str | None  # domain situs media
    link: str
    terbit: datetime  # timezone-aware, Asia/Jakarta
    ringkasan: str  # teks bersih dari description (boleh "")


def rapikan(teks: str) -> str:
    """Unescape HTML dan rapikan spasi."""
    return _SPASI.sub(" ", html.unescape(teks or "")).strip()


def hapus_sufiks_media(judul: str, media: str | None) -> str:
    """Hapus sufiks ' - {media}' / ' | {media}' bila ada (sebagian media menambahkannya)."""
    judul = rapikan(judul)
    if media:
        for pemisah in (" - ", " | "):
            akhiran = f"{pemisah}{media}"
            if judul.lower().endswith(akhiran.lower()) and len(judul) > len(akhiran):
                return judul[: -len(akhiran)].strip()
    return judul


def bersihkan_html(teks: str, maks: int = MAKS_RINGKASAN) -> str:
    """Ambil teks dari HTML, maksimal `maks` karakter."""
    if not teks:
        return ""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", MarkupResemblesLocatorWarning)
        bersih = BeautifulSoup(teks, "html.parser").get_text(" ")
    return rapikan(bersih)[:maks].rstrip()


def normalisasi_link(link: str) -> str:
    """Buang query/fragment, host lowercase, tanpa '/' di akhir (agar RSS & sitemap cocok)."""
    b = urlsplit(link.strip())
    path = b.path.rstrip("/") or "/"
    return urlunsplit(("https", b.netloc.lower(), path, "", ""))


def buat_id(link: str | None, guid: str | None = None) -> str:
    """sha1 dari link ternormalisasi; fallback guid."""
    kunci = normalisasi_link(link) if link and link.strip() else (guid or "").strip()
    return hashlib.sha1(kunci.encode("utf-8")).hexdigest()


def domain_dari(url: str | None) -> str | None:
    """'https://news.detik.com/x' -> 'detik.com' (dua label terakhir, kecuali .co.id dsb.)."""
    if not url:
        return None
    host = (urlsplit(url).netloc or urlsplit(f"//{url}").netloc).lower().split(":")[0]
    if not host:
        return None
    bagian = host.split(".")
    n = 3 if len(bagian) >= 3 and bagian[-2] in {"co", "or", "go", "ac", "web", "my"} else 2
    return ".".join(bagian[-n:])


def _waktu_entry(entry: feedparser.FeedParserDict, waktu_scrape: datetime) -> datetime:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return waktu_scrape.astimezone(WIB)
    return datetime.fromtimestamp(timegm(parsed), tz=timezone.utc).astimezone(WIB)


def _entry_ke_artikel(
    entry: feedparser.FeedParserDict, media_default: str | None, waktu_scrape: datetime
) -> Artikel | None:
    judul_mentah = entry.get("title") or ""
    link = (entry.get("link") or entry.get("id") or "").strip()
    if not link.startswith("http"):
        link = ""
    if not judul_mentah.strip() or not link:
        log.warning("Item dilewati karena tanpa judul/link: %r", (judul_mentah[:60], link[:60]))
        return None
    source = entry.get("source") or {}
    media = rapikan(source.get("title") or "") or media_default or MEDIA_TIDAK_DIKETAHUI
    judul = hapus_sufiks_media(judul_mentah, media)
    if not judul:
        return None
    return Artikel(
        id=buat_id(link, entry.get("id")),
        judul=judul,
        media=media,
        domain=domain_dari(source.get("href") or link),
        link=link,
        terbit=_waktu_entry(entry, waktu_scrape),
        ringkasan=bersihkan_html(entry.get("summary") or entry.get("description") or ""),
    )


def parse_feed(
    xml: bytes | str, media_default: str | None = None, waktu_scrape: datetime | None = None
) -> list[Artikel]:
    """Parse XML RSS/Atom menjadi list Artikel. XML rusak -> list kosong + log ERROR."""
    waktu_scrape = waktu_scrape or datetime.now(WIB)
    data = xml.encode("utf-8") if isinstance(xml, str) else xml
    if not data or not data.strip():
        log.error("XML kosong")
        return []
    hasil = feedparser.parse(io.BytesIO(data))
    if hasil.get("bozo") and not isinstance(hasil.get("bozo_exception"), _BOZO_AMAN):
        log.error("XML rusak: %s", hasil.get("bozo_exception"))
        return []
    if not hasil.get("version"):
        log.error("Dokumen bukan RSS/Atom yang dikenali")
        return []
    media = media_default or rapikan(hasil.feed.get("title") or "") or None
    artikel: list[Artikel] = []
    for entry in hasil.entries:
        try:
            a = _entry_ke_artikel(entry, media, waktu_scrape)
        except Exception:  # satu item aneh tidak boleh menghentikan proses
            log.warning("Item gagal diparse dan dilewati", exc_info=True)
            continue
        if a is not None:
            artikel.append(a)
    return artikel


def _waktu_iso(teks: str | None) -> datetime | None:
    if not teks or not teks.strip():
        return None
    try:
        t = datetime.fromisoformat(teks.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=WIB)
    return t.astimezone(WIB)


def parse_sitemap(xml: bytes | str, media_default: str | None = None) -> list[Artikel]:
    """Parse news sitemap (<urlset> + <news:news>) menjadi list Artikel.

    Item tanpa judul atau tanpa tanggal terbit dilewati (tanggal wajib untuk backfill).
    """
    data = xml.encode("utf-8") if isinstance(xml, str) else xml
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        log.error("Sitemap rusak: %s", exc)
        return []
    artikel: list[Artikel] = []
    for url in root.findall("sm:url", _NS_SITEMAP):
        link = (url.findtext("sm:loc", namespaces=_NS_SITEMAP) or "").strip()
        judul_mentah = url.findtext("news:news/news:title", namespaces=_NS_SITEMAP) or ""
        terbit = _waktu_iso(url.findtext("news:news/news:publication_date", namespaces=_NS_SITEMAP))
        if not link or not judul_mentah.strip() or terbit is None:
            continue
        media = rapikan(url.findtext("news:news/news:publication/news:name", namespaces=_NS_SITEMAP) or "")
        media = media_default or media or MEDIA_TIDAK_DIKETAHUI
        judul = hapus_sufiks_media(judul_mentah, media)
        artikel.append(Artikel(buat_id(link), judul, media, domain_dari(link), link, terbit, ""))
    return artikel
