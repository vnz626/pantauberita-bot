"""Klien HTTP: session, retry + backoff, jeda antar-request, dan cek robots.txt per host."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

from pantauberita.config import USER_AGENT

log = logging.getLogger(__name__)


def buat_session(user_agent: str = USER_AGENT, percobaan: int = 3) -> requests.Session:
    """Session dengan retry 3x + exponential backoff untuk error jaringan, 5xx, dan 429."""
    retry = Retry(
        total=percobaan,
        connect=percobaan,
        read=percobaan,
        status=percobaan,
        backoff_factor=1.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    session = requests.Session()
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update(
        {"User-Agent": user_agent, "Accept": "application/rss+xml, application/xml;q=0.9, text/xml;q=0.8"}
    )
    return session


def izinkan_robots(robots_txt: str, user_agent: str, urls: Iterable[str]) -> dict[str, bool]:
    """Fungsi murni: evaluasi isi robots.txt untuk daftar URL."""
    rp = RobotFileParser()
    rp.parse(robots_txt.splitlines())
    agen = user_agent.split("/")[0]
    return {u: rp.can_fetch(agen, u) for u in urls}


def _host(url: str) -> str:
    b = urlsplit(url)
    return f"{b.scheme}://{b.netloc}"


class HttpClient:
    """Pengambil URL dengan jeda minimal antar-request."""

    def __init__(
        self,
        jeda_detik: float = 1.5,
        timeout: float = 20.0,
        user_agent: str = USER_AGENT,
        session: requests.Session | None = None,
        tidur: Callable[[float], None] = time.sleep,
        jam: Callable[[], float] = time.monotonic,
    ) -> None:
        self.jeda_detik = jeda_detik
        self.timeout = timeout
        self.user_agent = user_agent
        self._session = session or buat_session(user_agent)
        self._tidur = tidur
        self._jam = jam
        self._terakhir: float | None = None

    def _tunggu_giliran(self) -> None:
        if self._terakhir is not None:
            sisa = self.jeda_detik - (self._jam() - self._terakhir)
            if sisa > 0:
                self._tidur(sisa)
        self._terakhir = self._jam()

    def ambil(self, url: str) -> bytes:
        """GET url dan kembalikan body; lempar `requests.RequestException` jika gagal."""
        self._tunggu_giliran()
        log.debug("GET %s", url)
        resp = self._session.get(url, timeout=self.timeout)
        resp.raise_for_status()
        return resp.content

    def _robots_host(self, host: str) -> str | None:
        """Isi robots.txt; '' bila tidak ada (404 = semua boleh); None bila akses ditolak (401/403)."""
        try:
            return self.ambil(f"{host}/robots.txt").decode("utf-8", errors="replace")
        except requests.HTTPError as exc:
            kode = exc.response.status_code if exc.response is not None else 0
            if kode in (401, 403):
                log.warning("robots.txt %s ditolak (%s): host dianggap melarang", host, kode)
                return None
            log.info("robots.txt %s tidak tersedia (%s): dianggap mengizinkan", host, kode)
            return ""
        except requests.RequestException as exc:
            log.warning("Gagal mengambil robots.txt %s (%s): dianggap mengizinkan", host, exc)
            return ""

    def cek_robots(self, urls: Iterable[str]) -> dict[str, bool]:
        """Cek izin tiap URL terhadap robots.txt host-nya (satu request per host)."""
        per_host: dict[str, list[str]] = {}
        for u in urls:
            per_host.setdefault(_host(u), []).append(u)
        hasil: dict[str, bool] = {}
        for host, daftar in per_host.items():
            isi = self._robots_host(host)
            if isi is None:
                hasil.update({u: False for u in daftar})
            else:
                hasil.update(izinkan_robots(isi, self.user_agent, daftar))
        diblokir = [u for u, ok in hasil.items() if not ok]
        log.info("Cek robots.txt %d host: %d URL diizinkan, %d diblokir", len(per_host), len(hasil) - len(diblokir), len(diblokir))
        for u in diblokir:
            log.warning("Diblokir robots.txt: %s", u)
        return hasil
