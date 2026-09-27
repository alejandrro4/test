"""Lectura de pantalla sobre la mesa sintética de ``synthetic.py``."""
import numpy as np
import pytest

import synthetic as S
from conftest import needs_tesseract
from poker_bot.capture.calibrate import draw_preview, interpolate_board, run_calibration
from poker_bot.core.cards import FULL_DECK
from poker_bot.vision.calibration import Calibration, Rect
from poker_bot.vision.cards import CardReader, GlyphLibrary
from poker_bot.vision.numbers import parse_amount


# ------------------------------- números ---------------------------------- #
@pytest.mark.parametrize("texto, valor", [
    ("1,234", 1234), ("1.234", 1234), ("1.234,5", 1234.5), ("1,234.5", 1234.5),
    ("12.5", 12.5), ("12,5", 12.5), ("$3.40", 3.4), ("15 BB", 15), ("Bote: 2,500", 2500),
    ("1,000,000", 1_000_000), ("", None), ("abc", None),
])
def test_parse_amount(texto, valor):
    assert parse_amount(texto) == valor


# -------------------------------- cartas ---------------------------------- #
def card_img(card):
    img = np.full((S.CARD_H, S.CARD_W, 3), S.FELT, np.uint8)
    S.draw_card(img, S.Rect(0, 0, S.CARD_W, S.CARD_H), card)
    return img


def test_carta_desconocida_se_guarda_para_aprender(tmp_path):
    lib = GlyphLibrary(tmp_path)
    reader = CardReader(lib, rank_box=(0.0, 0.0, 0.5, 0.6))
    r = reader.read(card_img("Qh"))
    assert r.present and r.unknown and r.card is None
    (gid,) = lib.pending()
    reader.read(card_img("Qd"))                      # mismo número: no duplica
    assert lib.pending() == [gid]
    lib.label(gid, "Q")
    assert reader.read(card_img("Qc")).card == "Qc"
    assert lib.pending() == []


def test_lee_las_52_cartas(library):
    reader = CardReader(library, rank_box=(0.0, 0.0, 0.5, 0.6))
    wrong = [c for c in FULL_DECK if reader.read(card_img(c)).card != c]
    assert wrong == []


def test_sin_carta(library):
    reader = CardReader(library)
    empty = np.full((S.CARD_H, S.CARD_W, 3), S.FELT, np.uint8)
    r = reader.read(empty)
    assert not r.present and r.card is None


def test_etiqueta_invalida(tmp_path):
    lib = GlyphLibrary(tmp_path)
    CardReader(lib, rank_box=(0.0, 0.0, 0.5, 0.6)).read(card_img("Ks"))
    with pytest.raises(ValueError):
        lib.label(lib.pending()[0], "Z")
    lib.discard(lib.pending()[0])
    assert lib.pending() == []


# --------------------------------- mesa ----------------------------------- #
SEATS = [(97.5, 0, True), (100, 0, False), (88, 4, True), None, (95, 4, True), (99, 1, True)]


@needs_tesseract
def test_lectura_completa(table_reader):
    img = S.render(hero=("Ah", "Tc"), board=("Qh", "Td", "2c", "9s"), pot=12.5, seats=SEATS,
                   dealer=2, my_turn=True)
    r = table_reader.read(img)
    assert r.hero_cards == ["Ah", "Tc"]
    assert r.board == ["Qh", "Td", "2c", "9s", None] and r.board_cards == ["Qh", "Td", "2c", "9s"]
    assert r.pot == 12.5
    assert [s.stack for s in r.seats] == [97.5, 100, 88, None, 95, 99]
    assert [s.bet for s in r.seats] == [0, 0, 4, 0, 4, 1]
    assert [s.has_cards for s in r.seats] == [True, False, True, False, True, True]
    assert r.dealer_seat == 2 and r.my_turn and r.problems == []


@needs_tesseract
@pytest.mark.parametrize("dealer", range(6))
def test_boton_de_dealer(table_reader, dealer):
    assert table_reader.read(S.render(dealer=dealer)).dealer_seat == dealer


@needs_tesseract
def test_no_es_mi_turno(table_reader):
    assert not table_reader.read(S.render(my_turn=False)).my_turn


@needs_tesseract
def test_cantidades_en_fichas_se_pasan_a_ciegas(library):
    from poker_bot.vision.numbers import NumberReader
    from poker_bot.vision.reader import TableReader
    calib = S.calibration()
    calib.amounts_in_bb, calib.big_blind = False, 2.0
    tr = TableReader(calib, CardReader(library, calib.rank_box), NumberReader())
    r = tr.read(S.render(pot=30, seats=[(200, 0, True)] * 6))
    assert r.pot == 15 and r.seats[0].stack == 100


@needs_tesseract
def test_ocr_cacheado(table_reader):
    img = S.render(pot=7.5)
    table_reader.read(img)
    calls = table_reader.numbers.calls
    table_reader.read(img)
    assert table_reader.numbers.calls == calls


# ----------------------------- calibración -------------------------------- #
def test_calibracion_guardar_y_cargar(tmp_path):
    c = S.calibration(buttons_hist=np.array([0.1, 0.2], np.float32))
    c.save(tmp_path / "c.json")
    c2 = Calibration.load(tmp_path / "c.json")
    assert c2 == c


def test_calibracion_inexistente(tmp_path):
    with pytest.raises(FileNotFoundError, match="calibrate"):
        Calibration.load(tmp_path / "no.json")


def test_interpolar_board():
    b = interpolate_board(Rect(100, 50, 40, 60), Rect(300, 50, 40, 60))
    assert [r.x for r in b] == [100, 150, 200, 250, 300]


def test_run_calibration_con_selector_simulado():
    """Simula a la persona marcando las zonas de la mesa sintética."""
    truth = S.calibration()
    answers = [truth.hero_cards[0], truth.hero_cards[1], truth.board[0], truth.board[4], truth.pot,
               truth.action_buttons, truth.felt]
    for i, s in enumerate(truth.seats):
        answers += [s.stack, s.bet] + ([] if i == 0 else [s.cards]) + [s.dealer]
    it = iter(answers)
    img = S.render(my_turn=True)
    calib = run_calibration(img, Rect(0, 0, S.W, S.H), lambda *_: next(it), seats=6, amounts_in_bb=True)
    assert calib.board == truth.board and calib.seats[3] == truth.seats[3]
    assert len(calib.buttons_hist) > 0
    assert draw_preview(img, calib).shape == img.shape


# ------------------------- dígitos que se aprenden ------------------------- #
def number_img(v):
    img = np.full((40, 120, 3), S.FELT, np.uint8)
    S.draw_number(img, S.Rect(0, 5, 120, 30), v)
    return img


@needs_tesseract
def test_digitos_se_aprenden_solos(tmp_path):
    from poker_bot.vision.numbers import NumberReader
    lib = GlyphLibrary(tmp_path)
    nr = NumberReader(lib)
    # Una cifra suelta sin plantillas: dudosa, nunca se inventa un número
    r = nr.read_ex(number_img(1))
    assert r.status == "unreadable" and r.value is None
    # Números de varias cifras bien leídos por el OCR enseñan sus dígitos
    for v in (97.5, 1234, 860, 12.5):
        assert nr.read_ex(number_img(v)).value == v
    assert lib.known_labels("digit") >= set("123456789")
    # Ahora las cifras sueltas salen por plantilla, sin OCR
    calls = nr.calls
    assert nr.read(number_img(1)) == 1 and nr.read(number_img(7)) == 7
    assert nr.calls == calls


@needs_tesseract
def test_digito_desconocido_se_ensena(tmp_path):
    from poker_bot.vision.numbers import NumberReader
    lib = GlyphLibrary(tmp_path)
    nr = NumberReader(lib)
    for v in (97.5, 1234, 860):
        nr.read(number_img(v))
    assert "0" in lib.known_labels("digit")          # del 860
    lib2 = GlyphLibrary(tmp_path / "otra")
    nr2 = NumberReader(lib2)
    assert nr2.read_ex(number_img(0)).status == "unreadable"
    (gid,) = [g for g in lib2.pending() if g.startswith("digit_")]
    lib2.label(gid, "0")
    assert nr2.read(number_img(0)) == 0


@needs_tesseract
def test_apuesta_ilegible_bloquea(table_reader, tmp_path):
    from poker_bot.vision.numbers import NumberReader
    table_reader.numbers = NumberReader(GlyphLibrary(tmp_path))   # sin dígitos aprendidos
    seats = [(100, 0, True), (100, 0, True), (100, 0, True), (100, 0, True), (99, 1, True), (98, 2, True)]
    r = table_reader.read(S.render(seats=seats, my_turn=True))
    assert any("apuesta" in p for p in r.problems)
