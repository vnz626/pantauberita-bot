"""Entry point bot Telegram PantauBerita (sekaligus menjalankan jadwal scraping)."""

from __future__ import annotations

import logging
import re
import sys

from telegram import BotCommand
from telegram.error import InvalidToken
from telegram.ext import Application

from pantauberita.config import Config, load_config
from pantauberita.logging_setup import setup_logging
from pantauberita.storage.repo import Repo
from pantauberita.telegram import handlers, jobs, messages

log = logging.getLogger("bot")


async def _setelah_mulai(app: Application) -> None:
    perintah = [BotCommand(c.split()[0].lstrip("/").rstrip(","), d) for c, d in messages.PERINTAH]
    perintah += [BotCommand("stop", "matikan laporan harian"), BotCommand("bantuan", "daftar perintah")]
    await app.bot.set_my_commands(perintah)


def buat_aplikasi(cfg: Config) -> Application:
    app = Application.builder().token(cfg.bot_token).post_init(_setelah_mulai).build()
    app.bot_data["cfg"] = cfg
    handlers.daftarkan(app)
    jobs.jadwalkan(app, cfg)
    return app


_POLA_TOKEN = re.compile(r"^\d{6,}:[A-Za-z0-9_-]{35}$")
PESAN_TOKEN_DITOLAK = (
    "BOT_TOKEN ditolak Telegram (salah ketik, ada karakter tambahan, atau token sudah di-revoke).\n"
    "Salin ulang token dari @BotFather (/mybots -> pilih bot -> API Token) ke baris BOT_TOKEN di .env, "
    "tanpa spasi atau tanda kutip, lalu jalankan lagi."
)


def format_token_wajar(token: str) -> bool:
    """Cek format token tanpa jaringan: '<angka>:<35 karakter>'."""
    return bool(_POLA_TOKEN.match(token))


def main() -> int:
    cfg = load_config()
    setup_logging(cfg.log_dir)
    if not cfg.bot_token:
        print("BOT_TOKEN kosong. Isi BOT_TOKEN di file .env (salin dari .env.example), lalu jalankan lagi.")
        return 1
    if not format_token_wajar(cfg.bot_token):
        log.warning("Format BOT_TOKEN tidak lazim (harus '<angka>:<35 karakter>'); tetap dicoba")
    with Repo(cfg.db_path) as repo:
        repo.init_db()
    if not cfg.admin_ids:
        log.warning("ADMIN_IDS kosong: /perbarui tidak bisa dipakai siapa pun")
    print("Bot PantauBerita berjalan. Tekan Ctrl+C untuk berhenti.")
    try:
        buat_aplikasi(cfg).run_polling()
    except InvalidToken:
        print(PESAN_TOKEN_DITOLAK)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
