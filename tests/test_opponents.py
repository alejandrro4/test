from poker_bot.engine.opponents import OpponentStats, unknown


def test_desconocido_es_neutro():
    u = unknown("Ana")
    assert u.fold_factor == 1.0
    assert u.aggression_factor == 1.0
    assert not u.reliable


def test_suavizado_con_pocas_manos():
    # 3 manos jugando todas: no debe salir VPIP 100 %
    s = OpponentStats("Luis", hands=3, vpip=3)
    assert s.vpip_rate < 0.6


def test_calling_station():
    s = OpponentStats("Pepe", hands=200, vpip=110, pfr=20, postflop_aggr=20, postflop_calls=120,
                      cbet_faced=60, fold_to_cbet=10, saw_flop=150, went_to_showdown=90)
    assert s.style == "calling station"
    assert s.fold_factor < 0.7
    assert s.reliable


def test_roca_y_maniaco():
    roca = OpponentStats("R", hands=200, vpip=24, pfr=8, postflop_aggr=10, postflop_calls=30)
    maniaco = OpponentStats("M", hands=200, vpip=120, pfr=90, postflop_aggr=150, postflop_calls=30)
    assert roca.style == "roca"
    assert maniaco.style == "maníaco"
    assert maniaco.aggression_factor > 1.3


def test_quien_se_tira_mucho():
    s = OpponentStats("F", hands=200, vpip=50, pfr=30, cbet_faced=60, fold_to_cbet=48,
                      saw_flop=100, went_to_showdown=15)
    assert s.fold_factor > 1.3
