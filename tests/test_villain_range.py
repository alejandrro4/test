from poker_bot.core.cards import parse_cards
from poker_bot.core.game_state import ActionType
from poker_bot.engine.ranges import Range
from poker_bot.engine.villain_range import combo_scores, continuing_range, estimate_ranges, narrow
from poker_bot.quick import postflop_state

BOARD = parse_cards("Kc7h2d")


def test_scores_ordenan_por_fuerza():
    r = Range.parse("KK,77,AK,QQ,65s")
    sc = combo_scores(r, BOARD)
    assert sc[("Kh", "Kd")] > sc[("Ah", "Kh")] > sc[("Qh", "Qd")] > sc[("6s", "5s")]


def test_proyectos_puntuan_alto():
    board = parse_cards("Qs9s2d")
    sc = combo_scores(Range.parse("AsJs,33"), board)
    assert sc[("As", "Js")] >= 0.62


def test_apostar_estrecha_hacia_manos_fuertes():
    r = Range.top_percent(40).remove_dead(BOARD)
    betting = narrow(r, BOARD, ActionType.BET)
    assert betting.combo_count < r.combo_count
    # Las manos fuertes se conservan enteras, el aire casi desaparece
    assert betting.weight(("Ks", "Kh")) == 1.0
    assert betting.weight(("Js", "Ts")) < 0.2


def test_pasar_capa_el_rango():
    r = Range.top_percent(40).remove_dead(BOARD)
    checking = narrow(r, BOARD, ActionType.CHECK)
    assert checking.weight(("Ks", "Kh")) < 1.0
    assert checking.weight(("Js", "Ts")) == 1.0


def test_continuing_range_es_la_parte_alta():
    r = Range.parse("KK,AK,QQ,JJ,65s").remove_dead(BOARD)
    top = continuing_range(r, BOARD, 0.5)
    assert abs(top.combo_count - r.combo_count * 0.5) < 1e-6
    assert ("Ks", "Kh") in top and ("6s", "5s") not in top


def test_estimate_ranges_postflop():
    gs = postflop_state("AsAd", "Kc7h2d", pot=9.5, to_call=4.0)
    ranges = estimate_ranges(gs)
    assert len(ranges) == 1
    r = next(iter(ranges.values()))
    # No incluye cartas del board; las del héroe se quitan luego (bloqueadores)
    assert all("Kc" not in c for c, _ in r)
    assert 0 < r.combo_count < 1326
