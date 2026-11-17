"""Fixture bersama: semua tes berjalan tanpa internet dan tanpa Telegram."""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pantauberita.config import WIB, Config  # noqa: E402
from pantauberita.parser.rss import Artikel, buat_id  # noqa: E402
from pantauberita.storage.repo import Repo  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def baca_fixture() -> Callable[[str], bytes]:
    return lambda nama: (FIXTURES / nama).read_bytes()


@pytest.fixture
def cfg(tmp_path: Path) -> Config:
    return replace(
        Config(),
        db_path=tmp_path / "berita.db",
        output_dir=tmp_path / "output",
        log_dir=tmp_path / "logs",
        jeda_detik=0,
    )


@pytest.fixture
def repo(cfg: Config):
    r = Repo(cfg.db_path)
    r.init_db()
    yield r
    r.close()


def buat_artikel(
    kunci: str, judul: str = "Judul contoh", media: str = "Media A", terbit: datetime | None = None
) -> Artikel:
    return Artikel(
        id=buat_id(f"https://contoh.test/{kunci}"),
        judul=judul,
        media=media,
        domain="contoh.test",
        link=f"https://contoh.test/{kunci}",
        terbit=terbit or datetime(2026, 11, 17, 10, 0, tzinfo=WIB),
        ringkasan="",
    )


class FakeClient:
    """Pengganti HttpClient: URL -> isi fixture (atau Exception)."""

    def __init__(self, peta: Callable[[str], bytes | Exception], robots_ok: bool = True) -> None:
        self.peta = peta
        self.robots_ok = robots_ok
        self.diminta: list[str] = []

    def ambil(self, url: str) -> bytes:
        self.diminta.append(url)
        hasil = self.peta(url)
        if isinstance(hasil, Exception):
            raise hasil
        return hasil

    def cek_robots(self, urls):
        if callable(self.robots_ok):
            return {u: bool(self.robots_ok(u)) for u in urls}
        return {u: bool(self.robots_ok) for u in urls}


def peta_fixture(baca: Callable[[str], bytes], gagal: str | None = None) -> Callable[[str], bytes | Exception]:
    """URL sumber -> fixture: feed utama -> rss_utama, CNN teknologi -> rss_teknologi,
    sitemap -> sitemap_detik, sisanya feed kosong. `gagal`: potongan URL yang dibuat error."""
    import requests

    from pantauberita.collector.feeds import SUMBER_UTAMA

    utama = {s.url for s in SUMBER_UTAMA}

    def peta(url: str):
        if gagal and gagal in url:
            return requests.ConnectionError("koneksi putus")
        if "sitemap" in url:
            return baca("sitemap_detik.xml")
        if url == "https://www.cnnindonesia.com/teknologi/rss":
            return baca("rss_teknologi.xml")
        if url in utama:
            return baca("rss_utama.xml")
        return baca("kosong.xml")

    return peta


@pytest.fixture
def fake_client_cls():
    return FakeClient


@pytest.fixture
def peta(baca_fixture):
    return lambda gagal=None: peta_fixture(baca_fixture, gagal)


@pytest.fixture
def db_terisi(cfg: Config, baca_fixture) -> Config:
    """Database berisi hasil satu run dari fixture (utama + topik teknologi + keyword 'banjir')."""
    from pantauberita import pipeline

    pipeline.run(cfg, semua=True, keywords=["banjir"], client=FakeClient(peta_fixture(baca_fixture)))
    return cfg
