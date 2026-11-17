import logging

import bot
from pantauberita.logging_setup import FormatterAman, sensor_token

TOKEN_CONTOH = "1234567890:" + "A" * 35  # token palsu untuk tes


def test_sensor_token_di_teks_dan_url():
    teks = f"token `{TOKEN_CONTOH}` ditolak; https://api.telegram.org/bot{TOKEN_CONTOH}/getMe"
    hasil = sensor_token(teks)
    assert TOKEN_CONTOH not in hasil
    assert hasil.count("<BOT_TOKEN disensor>") == 2


def test_formatter_menyensor_traceback():
    try:
        raise RuntimeError(f"The token `{TOKEN_CONTOH}` was rejected by the server.")
    except RuntimeError:
        import sys

        record = logging.LogRecord("t", logging.ERROR, __file__, 1, "gagal", None, sys.exc_info())
    keluar = FormatterAman("%(message)s").format(record)
    assert "RuntimeError" in keluar and TOKEN_CONTOH not in keluar


def test_format_token_wajar():
    assert bot.format_token_wajar(TOKEN_CONTOH)
    assert not bot.format_token_wajar(TOKEN_CONTOH + "s")  # satu karakter kelebihan
    assert not bot.format_token_wajar("bukan-token")
