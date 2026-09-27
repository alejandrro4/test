import pytest

from poker_bot.core.cards import (
    FULL_DECK, InvalidCardError, hand_class, parse_card, parse_cards, remaining_deck,
)


def test_baraja_completa():
    assert len(FULL_DECK) == 52
    assert len(set(FULL_DECK)) == 52


@pytest.mark.parametrize("texto, esperado", [
    ("As", "As"), ("as", "As"), ("10♥", "Th"), ("K♣", "Kc"), ("tD", "Td"), (" 2s ", "2s"),
])
def test_parse_card_normaliza(texto, esperado):
    assert parse_card(texto) == esperado


@pytest.mark.parametrize("texto", ["", "A", "Zs", "Ax", "11h"])
def test_parse_card_rechaza_invalidas(texto):
    with pytest.raises(InvalidCardError):
        parse_card(texto)


def test_parse_cards_formatos():
    assert parse_cards("AsKd") == ["As", "Kd"]
    assert parse_cards("As Kd 10h") == ["As", "Kd", "Th"]
    assert parse_cards(["qh", "Jc"]) == ["Qh", "Jc"]


def test_parse_cards_rechaza_repetidas():
    with pytest.raises(InvalidCardError):
        parse_cards("AsAs")


def test_remaining_deck():
    resto = remaining_deck(["As", "Kd"])
    assert len(resto) == 50 and "As" not in resto and "Kd" not in resto


@pytest.mark.parametrize("c1, c2, clase", [
    ("Ks", "Ah", "AKo"), ("Ah", "Kh", "AKs"), ("7d", "7c", "77"), ("2c", "Tc", "T2s"),
])
def test_hand_class(c1, c2, clase):
    assert hand_class(c1, c2) == clase
