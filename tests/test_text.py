from pantauberita.analysis.text import bigram, sentimen, token_dan_bigram, tokenisasi


def test_stopwords_tanda_baca_angka_terbuang():
    tokens = tokenisasi("Harga beras naik 10% di pasar, ini kata pedagang yang ada di Jakarta!")
    assert "yang" not in tokens and "di" not in tokens and "ini" not in tokens
    assert "10" not in tokens and all(t.isalpha() for t in tokens)
    assert {"harga", "beras", "pasar", "pedagang", "jakarta"} <= set(tokens)


def test_kata_pendek_terbuang():
    assert tokenisasi("RI dan AS teken MoU", stop=[]) == ["dan", "teken", "mou"]


def test_bigram():
    assert bigram(["harga", "beras", "naik"]) == ["harga beras", "beras naik"]
    assert "harga beras" in token_dan_bigram("Harga beras di pasar")


def test_sentimen_positif_negatif_netral():
    assert sentimen("Timnas menang dan raih prestasi gemilang") > 0
    assert sentimen("Banjir dan longsor tewaskan warga, korban bertambah") < 0
    assert sentimen("Rapat koordinasi digelar di balai kota") == 0.0
    assert -1.0 <= sentimen("menang kalah gagal") <= 1.0


def test_sentimen_kamus_kustom():
    assert sentimen("bagus jelek jelek", positif={"bagus"}, negatif={"jelek"}) == round(-1 / 3, 4)
