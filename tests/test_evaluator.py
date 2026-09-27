"""Tests del evaluador. Se ejecutan con el backend activo (eval7 o treys);
el test final compara ambos si los dos están instalados."""
import itertools
import random
import subprocess
import sys

import pytest

from poker_bot.core.cards import FULL_DECK, parse_cards
from poker_bot.engine.evaluator import hand_category, hand_strength


def s(text):
    return hand_strength(parse_cards(text))


@pytest.mark.parametrize("mejor, peor", [
    ("AsKsQsJsTs", "9s9h9d9c2h"),       # escalera de color > póker
    ("9s9h9d9c2h", "AsAhAdKsKh"),       # póker > full
    ("AsAhAdKsKh", "2s4s6s8sTs"),       # full > color
    ("2s4s6s8sTs", "AsKdQhJcTs"),       # color > escalera
    ("AsKdQhJcTs", "5s4d3h2cAh"),       # escalera alta > rueda
    ("5s4d3h2cAh", "QsQhQd2c3h"),       # rueda > trío
    ("QsQhQd2c3h", "AsAhKdKc2h"),       # trío > dobles
    ("AsAhKdKc2h", "AsAhKdQc3h"),       # dobles > pareja
    ("AsAhKdQc3h", "AsKhQdJc9h"),       # pareja > carta alta
    ("AsAhKdQc4h", "AsAhKdQc3h"),       # kicker
])
def test_orden_de_categorias(mejor, peor):
    assert s(mejor) > s(peor)


def test_mejor_de_siete_cartas():
    # Board con escalera; la mano del jugador aporta color
    assert s("Ah2h" + "KhQh9h3c4d") > s("JcTc" + "KhQh9h3c4d")
    # Board que juega para ambos -> empate
    assert s("2c3d" + "AsKsQsJsTs") == s("4h5h" + "AsKsQsJsTs")


@pytest.mark.parametrize("cartas, categoria", [
    ("AsKsQsJsTs", "straight_flush"),
    ("9s9h9d9c2h", "quads"),
    ("AsAhAdKsKh", "full_house"),
    ("2s4s6s8sTs3h4h", "flush"),
    ("AsKdQhJcTs", "straight"),
    ("QsQhQd2c3h", "trips"),
    ("AsAhKdKc2h", "two_pair"),
    ("AsAhKdQc3h", "pair"),
    ("AsKhQdJc9h", "high_card"),
])
def test_categorias(cartas, categoria):
    assert hand_category(parse_cards(cartas)) == categoria


def test_backends_coinciden():
    """eval7 y treys deben ordenar igual 300 pares de manos aleatorias de 7 cartas."""
    pytest.importorskip("eval7")
    pytest.importorskip("treys")
    rnd = random.Random(7)
    manos = [" ".join(rnd.sample(FULL_DECK, 7)) for _ in range(300)]
    script = (
        "import sys; from poker_bot.engine.evaluator import hand_strength as h;"
        "from poker_bot.core.cards import parse_cards as p;"
        "print(','.join(str(h(p(l))) for l in sys.stdin.read().splitlines()))"
    )
    def fuerzas(backend):
        env = {"POKER_BOT_EVALUATOR": backend, "PATH": ""}
        out = subprocess.run([sys.executable, "-c", script], input="\n".join(manos),
                             capture_output=True, text=True, env=env, check=True)
        return [int(x) for x in out.stdout.strip().split(",")]
    a, b = fuerzas("eval7"), fuerzas("treys")
    for i, j in itertools.combinations(range(len(manos)), 2):
        assert (a[i] > a[j]) == (b[i] > b[j]) and (a[i] == a[j]) == (b[i] == b[j])
