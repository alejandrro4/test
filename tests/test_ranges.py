import pytest

from poker_bot.engine.ranges import HAND_RANKING, Range, RangeParseError, combos_of_class


def test_combos_por_clase():
    assert len(combos_of_class("AA")) == 6
    assert len(combos_of_class("AKs")) == 4
    assert len(combos_of_class("AKo")) == 12
    assert len(combos_of_class("AK")) == 16


def test_ranking_tiene_169_clases():
    assert len(HAND_RANKING) == 169 == len(set(HAND_RANKING))
    assert sum(len(combos_of_class(c)) for c in HAND_RANKING) == 1326


@pytest.mark.parametrize("texto, combos", [
    ("AA", 6), ("TT+", 30), ("22-55", 24), ("55-22", 24),
    ("ATs+", 16), ("A2s-A5s", 16), ("AK", 16), ("KQo", 12),
    ("AsKs", 1), ("AA, KK, AKs", 16), ("AA,AA", 6),
])
def test_parse_cuenta_combos(texto, combos):
    assert len(Range.parse(texto)) == combos


def test_combo_concreto_orden_indiferente():
    r = Range.parse("KdAs")
    assert ("As", "Kd") in r and ("Kd", "As") in r


def test_pesos():
    r = Range.parse("AA, KK:0.5")
    assert r.combo_count == pytest.approx(6 + 3)


@pytest.mark.parametrize("texto", ["AAs", "XK", "AK-QJ", "KQx", "AA:2"])
def test_parse_invalido(texto):
    with pytest.raises((RangeParseError, ValueError)):
        Range.parse(texto)


def test_top_percent():
    assert len(Range.random()) == 1326
    top = Range.top_percent(10)
    assert 120 <= len(top) <= 150
    assert "AA" in top.classes() and "72o" not in top.classes()


def test_remove_dead():
    r = Range.parse("AA").remove_dead(["As"])
    assert len(r) == 3
