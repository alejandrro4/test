"""Tests de comportamiento del cerebro: situaciones con respuesta clara.

Las situaciones con frecuencias mixtas se evitan o se prueban con varias
semillas; la equity es Monte Carlo, así que se eligen casos con margen.
"""
import pytest

from poker_bot.core.game_state import ActionType
from poker_bot.engine.decision import decide
from poker_bot.engine.opponents import OpponentStats
from poker_bot.quick import postflop_state, preflop_state

A = ActionType
AGGRO = (A.BET, A.RAISE, A.ALL_IN)

STATION = OpponentStats("Rival1", hands=200, vpip=110, pfr=20, postflop_aggr=20,
                        postflop_calls=120, cbet_faced=60, fold_to_cbet=10, saw_flop=150,
                        went_to_showdown=90)
FOLDER = OpponentStats("Rival1", hands=200, vpip=50, pfr=30, postflop_aggr=40, postflop_calls=30,
                       cbet_faced=60, fold_to_cbet=48, saw_flop=100, went_to_showdown=15)


# ------------------------------- preflop ---------------------------------- #
@pytest.mark.parametrize("hand, pos, esperado", [
    ("AsAh", "UTG", A.RAISE),
    ("7c2d", "UTG", A.FOLD),
    ("7c2d", "BTN", A.FOLD),
    ("KsQs", "HJ", A.RAISE),
    ("Ah4c", "BTN", A.RAISE),
])
def test_aperturas(hand, pos, esperado):
    assert decide(preflop_state(hand, pos), seed=1).action is esperado


def test_apertura_tamano():
    d = decide(preflop_state("AsAh", "CO"), seed=1)
    assert d.amount == pytest.approx(2.5)
    assert "SUBIR" in d.headline()


def test_aa_siempre_3betea():
    for seed in range(10):
        d = decide(preflop_state("AsAh", "BTN", opener="UTG"), seed=seed)
        assert d.action is A.RAISE and d.amount == pytest.approx(7.5)


def test_bb_defiende_ancho_contra_btn_pero_no_basura():
    assert decide(preflop_state("Kh7h", "BB", opener="BTN"), seed=1).action is A.CALL
    assert decide(preflop_state("7h2c", "BB", opener="BTN"), seed=1).action is A.FOLD


def test_pagar_all_in_por_equity():
    call = decide(preflop_state("AdJc", "BB", opener="BTN", open_size=40, all_in=True))
    fold = decide(preflop_state("8d4c", "BB", opener="UTG", open_size=100, all_in=True))
    assert call.action in (A.CALL, A.ALL_IN) and call.ev > 0
    assert fold.action is A.FOLD


def test_push_fold_stack_corto():
    assert decide(preflop_state("Kd9c", "BTN", stack=8), seed=1).action is A.ALL_IN
    assert decide(preflop_state("7d2c", "UTG", stack=8), seed=1).action is A.FOLD


def test_heads_up():
    d = decide(preflop_state("Qd6c", "BTN", players=2), seed=1)
    assert d.action is A.RAISE


# ------------------------------- postflop --------------------------------- #
def test_set_en_board_seco_apuesta_valor():
    gs = postflop_state("7s7d", "Kc7h2d", pot=5.5, villain_checked=True)
    d = decide(gs, seed=1)
    assert d.action in AGGRO and d.equity > 0.9 and d.ev > 0


def test_cbet_pequena_en_seco_y_grande_en_mojado():
    seco = decide(postflop_state("KsKd", "Kc7h2d", pot=10, villain_checked=True), seed=1)
    mojado = decide(postflop_state("KsKd", "JhTh9c", pot=10, villain_checked=True), seed=1)
    assert seco.action is A.BET and mojado.action is A.BET
    assert seco.amount <= 5 <= mojado.amount


def test_tira_basura_contra_apuesta():
    gs = postflop_state("4c3c", "KdQhJs", pot=9.5, to_call=4)
    assert decide(gs, seed=1).action is A.FOLD


def test_paga_con_pot_odds_correctas():
    # Proyecto de color al nuts contra apuesta pequeña: nunca tirar
    gs = postflop_state("As5s", "Qs9s2d", pot=7.5, to_call=2)
    d = decide(gs, seed=1)
    assert d.action is not A.FOLD


def test_river_nuts_apuesta_grande():
    gs = postflop_state("AhTh", "Kh9h4c2h7d", pot=20, stack=80, villain_checked=True)
    d = decide(gs, seed=1)
    assert d.action in AGGRO and d.amount >= 20      # overbet o all-in


def test_no_farolear_a_calling_station_si_a_quien_se_tira():
    gs = postflop_state("Ah3c", "Kh9h4c2h7d", pot=20, stack=80, villain_checked=True)
    assert decide(gs, {"Rival1": STATION}, seed=1).action is A.CHECK
    assert decide(gs, {"Rival1": FOLDER}, seed=1).action in AGGRO


def test_multiway_y_tiempo():
    gs = postflop_state("AhKd", "Kc8h3s", pot=12, villains=3, villain_checked=True)
    d = decide(gs, budget_ms=800)
    assert d.action in (A.BET, A.CHECK)
    assert d.elapsed_ms < 3000


def test_salida_legible():
    d = decide(postflop_state("7s7d", "Kc7h2d", pot=5.5, villain_checked=True), seed=1)
    texto = str(d)
    assert "equity" in texto and "EV" in texto and d.reason
    assert d.speech()


def test_sin_rivales():
    gs = postflop_state("7s7d", "Kc7h2d", pot=5.5)
    for p in gs.opponents_in_hand:
        p.in_hand = False
    assert decide(gs).action is A.CHECK
