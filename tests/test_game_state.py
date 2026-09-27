import pytest

from poker_bot.core.game_state import GameState, PlayerState, Street


def mesa_6max(**kw):
    """Mesa de 6: héroe en el asiento 0, botón en el asiento 3."""
    players = [PlayerState(seat=i, name=f"P{i}", stack=100.0) for i in range(6)]
    players[0].is_hero = True
    base = dict(hero_cards=["As", "Kd"], board=[], pot=0.0, players=players,
                dealer_seat=3, big_blind=1.0)
    base.update(kw)
    return GameState(**base)


def test_calle_segun_board():
    assert mesa_6max().street is Street.PREFLOP
    assert mesa_6max(board=["2c", "3d", "4h"]).street is Street.FLOP
    assert mesa_6max(board=["2c", "3d", "4h", "5s", "6c"]).street is Street.RIVER
    with pytest.raises(ValueError):
        _ = mesa_6max(board=["2c"]).street


def test_posiciones_6max():
    gs = mesa_6max()
    gs.assign_positions()
    pos = {p.seat: p.position for p in gs.players}
    assert pos == {3: "BTN", 4: "SB", 5: "BB", 0: "UTG", 1: "HJ", 2: "CO"}


def test_posiciones_con_asiento_vacio_y_heads_up():
    gs = mesa_6max()
    for p in gs.players[2:]:
        if p.seat != 3:
            p.stack, p.in_hand = 0.0, False
    gs.assign_positions()   # quedan los asientos 0, 1 y 3
    assert {p.seat: p.position for p in gs.players if p.position} == {3: "BTN", 0: "SB", 1: "BB"}

    hu = mesa_6max(players=[PlayerState(0, is_hero=True, stack=50), PlayerState(1, stack=50)],
                   dealer_seat=0)
    hu.assign_positions()
    assert hu.hero.position == "BTN"


def test_to_call_pot_odds_y_spr():
    gs = mesa_6max(pot=10.0)
    gs.players[4].bet = 5.0          # un rival apuesta 5 en un bote de 10 (ya incluido)
    for p in gs.players[1:]:
        if p.seat != 4:
            p.in_hand = False
    assert gs.to_call == 5.0
    assert gs.pot_odds == pytest.approx(5 / 15)
    assert gs.effective_stack == 100.0
    assert gs.spr == pytest.approx(10.0)


def test_to_call_limitado_por_stack():
    gs = mesa_6max(pot=300.0)
    gs.hero.stack = 20.0
    gs.players[1].bet = 200.0
    assert gs.to_call == 20.0
    assert gs.effective_stack == 20.0
