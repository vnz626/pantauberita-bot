"""Pengaturan logging: konsol + file berputar."""

from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
_PENANDA = "_pantauberita_handler"
# Token bot Telegram: <angka>:<string acak>. Juga muncul di URL API (/bot<token>/).
_POLA_TOKEN = re.compile(r"(?<!\d)\d{6,}:[A-Za-z0-9_-]{30,}")


def sensor_token(teks: str) -> str:
    """Ganti token bot Telegram di teks dengan penanda tersensor."""
    return _POLA_TOKEN.sub("<BOT_TOKEN disensor>", teks)


class FormatterAman(logging.Formatter):
    """Formatter yang menyensor token bot, termasuk di dalam traceback."""

    def format(self, record: logging.LogRecord) -> str:
        return sensor_token(super().format(record))


def setup_logging(log_dir: Path, level: int = logging.INFO, konsol: bool = True) -> None:
    """Pasang handler konsol dan `logs/pantauberita.log` (1 MB x 5). Aman dipanggil berulang."""
    root = logging.getLogger()
    root.setLevel(level)
    for h in list(root.handlers):
        if getattr(h, _PENANDA, False):
            root.removeHandler(h)
            h.close()

    formatter = FormatterAman(FORMAT, datefmt="%Y-%m-%d %H:%M:%S")
    log_dir.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        log_dir / "pantauberita.log", maxBytes=1_000_000, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    setattr(file_handler, _PENANDA, True)
    root.addHandler(file_handler)

    if konsol:
        stream = logging.StreamHandler()
        stream.setFormatter(formatter)
        stream.setLevel(logging.WARNING)
        setattr(stream, _PENANDA, True)
        root.addHandler(stream)

    for berisik in ("httpx", "matplotlib", "PIL", "apscheduler"):
        logging.getLogger(berisik).setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.ERROR)  # retry otomatis tidak perlu memenuhi konsol
