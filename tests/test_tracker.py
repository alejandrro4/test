"""Seguimiento de la mano: deducir acciones a partir de lecturas sucesivas."""
from poker_bot.core.game_state import ActionType, Street
from poker_bot.engine.decision import decide
from poker_bot.vision.reader import SeatRead, TableRead
from poker_bot.vision.tracker import HandTracker

A = ActionType
# Mesa de 6, héroe = asiento 0, botón en el asiento 3:
# preflop habla UTG=0 (héroe), HJ=1, CO=2, BTN=3, SB=4, BB=5


def read(seats, hero=("As", "Kd"), board=(), pot=0.0, dealer=3, turn=False):
    """``seats``: lista de (stack, apuesta, en_mano)."""
    return TableRead(list(hero), list(board) + [None] * (5 - len(board)), pot,
                     [SeatRead(st, b, c) for st, b, c in seats], dealer, turn)


def feed(tracker, r, frames=2):
    upd = None
    for _ in range(frames):
        upd = tracker.update(r)
    return upd


def base(**over):
    s = [(100, 0, True)] * 6
    s = [list(x) for x in s]
    s[4] = [99.5, 0.5, True]
    s[5] = [99, 1, True]
    for k, v in over.items():
        s[int(k[1:])] = list(v)
    return [tuple(x) for x in s]


def kinds(tr):
    return [(a.seat, a.type) for a in tr.actions]


def test_necesita_lectura_estable():
    tr = HandTracker()
    r = read(base(), turn=True)
    assert tr.update(r).state is None                 # primer frame: aún no fiable
    assert tr.update(r).state is not None             # segundo igual: ya sí


def test_ciegas_y_mi_turno_sin_nadie_delante():
    tr = HandTracker()
    upd = feed(tr, read(base(), turn=True))
    assert kinds(tr) == [(4, A.POST_BLIND), (5, A.POST_BLIND)]
    gs = upd.state
    assert gs.street is Street.PREFLOP and gs.hero.position == "UTG"
    assert gs.pot == 1.5 and gs.to_call == 1.0
    assert decide(gs, seed=1).action is A.RAISE        # AKo abre desde UTG


def test_deduce_subida_pago_y_fold():
    tr = HandTracker()
    feed(tr, read(base(s0=(100, 0, True))))
    # Héroe (UTG) sube a 2.5
    feed(tr, read(base(s0=(97.5, 2.5, True))))
    # HJ se tira, CO paga, BTN 3-bet a 8
    feed(tr, read(base(s0=(97.5, 2.5, True), s1=(100, 0, False), s2=(97.5, 2.5, True))))
    upd = feed(tr, read(base(s0=(97.5, 2.5, True), s1=(100, 0, False), s2=(97.5, 2.5, True),
                             s3=(92, 8, True), s4=(99.5, 0.5, False), s5=(99, 1, False)), turn=True))
    assert kinds(tr) == [(4, A.POST_BLIND), (5, A.POST_BLIND), (0, A.RAISE), (1, A.FOLD),
                         (2, A.CALL), (3, A.RAISE), (4, A.FOLD), (5, A.FOLD)]
    gs = upd.state
    assert gs.to_call == 5.5 and len(gs.opponents_in_hand) == 2
    assert decide(gs, seed=1).action in (A.RAISE, A.CALL, A.FOLD, A.ALL_IN)


def test_all_in_cuando_se_queda_sin_stack():
    tr = HandTracker()
    feed(tr, read(base()))
    feed(tr, read(base(s1=(0, 100, True))))
    assert kinds(tr)[-1] == (1, A.ALL_IN)


def test_calle_nueva_y_apuesta_postflop():
    tr = HandTracker()
    preflop = base(s0=(97.5, 2.5, True), s1=(100, 0, False), s2=(100, 0, False), s3=(100, 0, False),
                   s4=(99.5, 0, False), s5=(97.5, 2.5, True))
    feed(tr, read(base()))
    feed(tr, read(preflop))
    flop = [(97.5, 0, True), (100, 0, False), (100, 0, False), (100, 0, False), (99.5, 0, False),
            (97.5, 0, True)]
    board = ("Qh", "7c", "2d")
    feed(tr, read(flop, board=board, pot=5.5))
    assert tr.street is Street.FLOP
    bet = list(flop)
    bet[5] = (94, 3.5, True)
    upd = feed(tr, read(bet, board=board, pot=5.5, turn=True))
    assert kinds(tr)[-1] == (5, A.BET)
    gs = upd.state
    assert gs.pot == 9.0 and gs.to_call == 3.5 and gs.board == ["Qh", "7c", "2d"]
    assert gs.hero_in_position()
    d = decide(gs, seed=1)
    assert d.action is not None and d.reason


def test_mano_nueva_reinicia():
    tr = HandTracker()
    feed(tr, read(base(s1=(0, 100, True))))
    feed(tr, read(base(), hero=("7c", "2d"), dealer=4))
    assert tr.hand_id == 2 and kinds(tr) == [(4, A.POST_BLIND), (5, A.POST_BLIND)]
    assert tr.dealer == 4


def test_preflop_sin_bote_visible_usa_las_apuestas():
    r = read(base(), turn=True)
    r.pot = None
    upd = feed(HandTracker(), r)
    assert upd.state is not None and upd.state.pot == 1.5


def test_no_decide_si_la_lectura_es_dudosa():
    tr = HandTracker()
    r = read(base(), board=("Qh", "7c", "2d"), turn=True)
    r.pot = None
    upd = feed(tr, r)
    assert upd.state is None and "no leo el bote" in upd.problems
    r2 = read(base(), turn=True, dealer=None)
    upd = feed(HandTracker(), r2)
    assert upd.state is None and any("botón" in p for p in upd.problems)


def test_sin_cartas_espera():
    tr = HandTracker()
    r = read([(100, 0, False)] * 6, hero=(None, None))
    assert "Esperando" in feed(tr, r).status


def test_no_repite_decision_para_el_mismo_estado():
    tr = HandTracker()
    upd = feed(tr, read(base(), turn=True))
    assert upd.new_decision
    upd = feed(tr, read(base(), turn=True), frames=3)
    assert not upd.new_decision or upd.state is None
