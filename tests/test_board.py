import pytest

from poker_bot.core.cards import parse_cards
from poker_bot.engine.board import analyze_board, detect_draws


def tex(b):
    return analyze_board(parse_cards(b))


def test_board_seco_vs_mojado():
    seco, mojado = tex("Kc7h2d"), tex("JhTh9c")
    assert seco.category == "seco"
    assert mojado.category == "mojado"
    assert mojado.wetness > seco.wetness


def test_flags_de_textura():
    assert tex("Ks8s3s").monotone
    assert tex("Ks8s3d").two_tone
    assert tex("KsKd3c").paired
    assert tex("9c8d7h").straight_possible
    assert not tex("Kc7h2d").straight_possible
    assert tex("Kc7h2d").describe().startswith("seco")


def test_board_demasiado_corto():
    with pytest.raises(ValueError):
        analyze_board(["As", "Kd"])


@pytest.mark.parametrize("hole, board, fd, nut, s_outs", [
    ("As5s", "Qs9s2d", True, True, 0),        # nut flush draw
    ("Ks5s", "Qs9s2d", True, False, 0),       # flush draw no nuts
    ("JcTc", "9h8d2s", False, False, 8),      # escalera abierta
    ("JcTc", "Qh8d2s", False, False, 4),      # gutshot (falta el 9)
    ("Ah2c", "3d4s9h", False, False, 4),      # gutshot a la rueda (falta el 5)
    ("7c2d", "KsQs9h", False, False, 0),      # nada
])
def test_proyectos(hole, board, fd, nut, s_outs):
    d = detect_draws(parse_cards(hole), parse_cards(board))
    assert (d.flush_draw, d.nut_flush_draw, d.straight_outs) == (fd, nut, s_outs)


def test_proyecto_solo_del_board_no_cuenta():
    # 4 al color en la mesa sin cartas de ese palo en la mano: no es nuestro proyecto
    d = detect_draws(parse_cards("2c3d"), parse_cards("AsKsQs7s"))
    assert not d.flush_draw


def test_sin_proyectos_en_river():
    assert not detect_draws(parse_cards("As5s"), parse_cards("Qs9s2d3c4h")).any
