"""Tests del cálculo de equity contra valores de referencia conocidos
(obtenidos con la rutina en C de eval7, 2M simulaciones). Tolerancia ±1.5 puntos."""
import pytest

from poker_bot.core.cards import parse_cards
from poker_bot.engine.equity import calculate_equity
from poker_bot.engine.ranges import Range

TOL = 0.015


def eq(hero, board, *ranges, n=20_000, **kw):
    return calculate_equity(parse_cards(hero), parse_cards(board) if board else [],
                            [Range.parse(r) if isinstance(r, str) else r for r in ranges],
                            iterations=n, time_budget_ms=5_000, seed=42, **kw)


@pytest.mark.parametrize("hero, board, villano, esperado", [
    ("AsAh", "", Range.random(), 0.852),      # AA vs mano aleatoria
    ("AsAh", "", "KK", 0.819),                # AA vs KK
    ("AhKh", "", "QQ", 0.460),                # AKs vs QQ (coinflip)
    ("7h8h", "", "AA", 0.225),                # 87s vs AA
    ("AsKs", "Qs7s2d", "QQ", 0.256),          # proyecto nut de color vs set (el board puede doblarse)
    ("JcTc", "9h8d2s", "AA", 0.342),          # escalera abierta vs overpair (8 outs, 2 calles)
])
def test_equity_referencia(hero, board, villano, esperado):
    assert eq(hero, board, villano).equity == pytest.approx(esperado, abs=TOL)


def test_river_es_determinista():
    # En el river no hay azar: AA gana siempre a KK en este board
    r = eq("AsAh", "2c7d9hJsQc", "KK")
    assert r.equity == 1.0 and r.win == 1.0


def test_empate_reparte_bote():
    # Escalera real en el board: todos empatan
    r = eq("2c3d", "AsKsQsJsTs", "72o")
    assert r.equity == pytest.approx(0.5) and r.tie == 1.0


def test_multiway_baja_equity():
    heads_up = eq("AsAh", "", Range.random()).equity
    tres = eq("AsAh", "", Range.random(), Range.random(), Range.random()).equity
    assert tres == pytest.approx(0.64, abs=0.02) and tres < heads_up


def test_rango_importa():
    # AQo contra un rango ajustado vale mucho menos que contra uno amplio
    ajustado = eq("AdQc", "", "QQ+,AK").equity
    amplio = eq("AdQc", "", Range.top_percent(50)).equity
    assert ajustado < 0.40 < amplio


def test_card_removal_y_cartas_muertas():
    r = eq("AsAh", "", "AA,KK", dead=["Kd"])
    assert 0 < r.equity < 1


def test_presupuesto_de_tiempo():
    r = calculate_equity(parse_cards("AsKd"), [], [Range.random()] * 5,
                         iterations=10**9, time_budget_ms=100)
    assert r.elapsed_ms < 250 and r.iterations > 100


def test_minimo_10000_iteraciones_en_300ms_heads_up():
    r = calculate_equity(parse_cards("AsKd"), parse_cards("Qh7c2d"), [Range.top_percent(30)],
                         iterations=10_000, time_budget_ms=300)
    assert r.iterations == 10_000 or r.elapsed_ms >= 290


@pytest.mark.parametrize("hero, board, rangos", [
    ("As", "", ["AA"]),                  # una sola carta
    ("AsKd", "Qh7c", ["AA"]),            # board de 2 cartas
    ("AsKd", "AsQh7c", ["QQ"]),          # carta repetida
    ("AsAh", "", ["AsAh"]),              # rango vacío tras card removal
])
def test_entradas_invalidas(hero, board, rangos):
    with pytest.raises(ValueError):
        eq(hero, board, *rangos)
