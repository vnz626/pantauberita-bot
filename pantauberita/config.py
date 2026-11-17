"""Konfigurasi: baca .env, konstanta, dan daftar topik."""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import time
from pathlib import Path
from types import MappingProxyType
from zoneinfo import ZoneInfo

from dotenv import dotenv_values

log = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
OUTPUT_DIR = ROOT_DIR / "output"
LOG_DIR = ROOT_DIR / "logs"
FIXTURE_DIR = ROOT_DIR / "tests" / "fixtures"

WIB = ZoneInfo("Asia/Jakarta")
USER_AGENT = "PantauBerita/1.0 (proyek kuliah)"
ATRIBUSI = (
    "Sumber: RSS & sitemap berita resmi detikcom, CNN Indonesia, CNBC Indonesia, VIVA, ANTARA, "
    "Republika, JPNN; hak cipta milik masing-masing media"
)
ATRIBUSI_SINGKAT = "Sumber: RSS resmi media, hak cipta milik masing-masing media"
MIN_SCRAPE_SETIAP_JAM = 3

#: Kode topik -> label Indonesia (tidak bisa diubah saat runtime).
TOPIK: Mapping[str, str] = MappingProxyType(
    {
        "NATION": "nasional",
        "WORLD": "dunia",
        "BUSINESS": "bisnis",
        "TECHNOLOGY": "teknologi",
        "ENTERTAINMENT": "hiburan",
        "SPORTS": "olahraga",
        "SCIENCE": "sains",
        "HEALTH": "kesehatan",
    }
)
#: Label Indonesia -> kode topik.
LABEL_TOPIK: Mapping[str, str] = MappingProxyType({v: k for k, v in TOPIK.items()})

#: Media yang news sitemap-nya dipakai untuk backfill (lihat collector/feeds.py).
MEDIA_BACKFILL_DEFAULT: tuple[str, ...] = (
    "detik.com",
    "cnnindonesia.com",
    "cnbcindonesia.com",
    "viva.co.id",
)


@dataclass(frozen=True)
class Config:
    """Seluruh pengaturan aplikasi (immutable)."""

    bot_token: str = ""
    admin_ids: tuple[int, ...] = ()
    db_path: Path = DATA_DIR / "berita.db"
    scrape_setiap_jam: int = 3
    jam_mulai_scrape: time = time(6, 0)
    jam_laporan: time = time(7, 0)
    jeda_detik: float = 1.5
    topik_aktif: tuple[str, ...] = tuple(TOPIK)
    media_backfill: tuple[str, ...] = MEDIA_BACKFILL_DEFAULT
    output_dir: Path = OUTPUT_DIR
    log_dir: Path = LOG_DIR


def _daftar(nilai: str | None) -> tuple[str, ...]:
    """Pecah string berkoma menjadi tuple tanpa elemen kosong."""
    if not nilai:
        return ()
    return tuple(x.strip() for x in nilai.split(",") if x.strip())


def _jam(nilai: str | None, bawaan: time) -> time:
    """Ubah 'HH:MM' menjadi `datetime.time`."""
    if not nilai:
        return bawaan
    try:
        jam, menit = nilai.strip().split(":")
        return time(int(jam), int(menit))
    except ValueError:
        log.warning("Format jam tidak valid: %r, pakai %s", nilai, bawaan)
        return bawaan


def _path(nilai: str | None, bawaan: Path) -> Path:
    """Path relatif dianggap relatif terhadap folder proyek."""
    if not nilai:
        return bawaan
    p = Path(nilai)
    return p if p.is_absolute() else ROOT_DIR / p


def load_config(env_file: Path | None = None, environ: Mapping[str, str] | None = None) -> Config:
    """Bangun `Config` dari file .env lalu variabel lingkungan (lingkungan menang)."""
    nilai: dict[str, str] = {}
    env_path = env_file if env_file is not None else ROOT_DIR / ".env"
    if env_path.exists():
        nilai.update({k: v for k, v in dotenv_values(env_path).items() if v is not None})
    nilai.update(environ if environ is not None else os.environ)

    def ambil(kunci: str) -> str | None:
        v = nilai.get(kunci)
        return v.strip() if isinstance(v, str) and v.strip() else None

    bawaan = Config()
    admin: list[int] = []
    for x in _daftar(ambil("ADMIN_IDS")):
        try:
            admin.append(int(x))
        except ValueError:
            log.warning("ADMIN_IDS berisi nilai bukan angka: %r", x)

    setiap = int(ambil("SCRAPE_SETIAP_JAM") or bawaan.scrape_setiap_jam)
    if setiap < MIN_SCRAPE_SETIAP_JAM:
        log.warning("SCRAPE_SETIAP_JAM=%s terlalu sering, dinaikkan ke %s", setiap, MIN_SCRAPE_SETIAP_JAM)
        setiap = MIN_SCRAPE_SETIAP_JAM

    jeda = max(1.5, float(ambil("JEDA_DETIK") or bawaan.jeda_detik))

    topik = tuple(t.upper() for t in _daftar(ambil("TOPIK_AKTIF"))) or bawaan.topik_aktif
    topik_tak_dikenal = [t for t in topik if t not in TOPIK]
    if topik_tak_dikenal:
        log.warning("Topik tidak dikenal diabaikan: %s", topik_tak_dikenal)
    topik = tuple(t for t in topik if t in TOPIK)

    return Config(
        bot_token=ambil("BOT_TOKEN") or "",
        admin_ids=tuple(admin),
        db_path=_path(ambil("DB_PATH"), bawaan.db_path),
        scrape_setiap_jam=setiap,
        jam_mulai_scrape=_jam(ambil("JAM_MULAI_SCRAPE"), bawaan.jam_mulai_scrape),
        jam_laporan=_jam(ambil("JAM_LAPORAN"), bawaan.jam_laporan),
        jeda_detik=jeda,
        topik_aktif=topik,
        media_backfill=tuple(d.lower() for d in _daftar(ambil("MEDIA_BACKFILL"))) or bawaan.media_backfill,
        output_dir=_path(ambil("OUTPUT_DIR"), bawaan.output_dir),
        log_dir=_path(ambil("LOG_DIR"), bawaan.log_dir),
    )
