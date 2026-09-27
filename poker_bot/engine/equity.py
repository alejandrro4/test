"""Cálculo de equity por simulación Monte Carlo contra RANGOS de rivales.

Cada iteración:
  1. Saca una mano para cada rival de su rango (ponderado por pesos), sin
     repetir cartas con el héroe, el board ni con los otros rivales.
  2. Completa el board con cartas aleatorias de la baraja restante.
  3. Evalúa todas las manos y reparte el bote entre los ganadores.

Se detiene al llegar a ``iterations`` o al agotar ``time_budget_ms`` (lo que
ocurra antes), así la decisión nunca se come el tiempo de respuesta.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Sequence

from poker_bot.core.cards import remaining_deck
from poker_bot.engine.evaluator import hand_strength
from poker_bot.engine.ranges import Range

# Cada cuántas iteraciones se mira el reloj (mirarlo siempre es caro)
_CLOCK_EVERY = 128
# Intentos máximos para sacar combos compatibles antes de descartar la iteración
_MAX_SAMPLE_TRIES = 50


@dataclass(frozen=True)
class EquityResult:
    equity: float        # parte esperada del bote (victorias + empates repartidos), 0..1
    win: float           # frecuencia de victoria en solitario
    tie: float           # frecuencia de empate (con al menos un rival)
    iterations: int
    elapsed_ms: float

    @property
    def std_error(self) -> float:
        """Error estándar aproximado de la estimación de equity."""
        if self.iterations == 0:
            return 1.0
        e = self.equity
        return (e * (1 - e) / self.iterations) ** 0.5


def calculate_equity(
    hero: Sequence[str],
    board: Sequence[str],
    villain_ranges: Sequence[Range],
    iterations: int = 10_000,
    time_budget_ms: float = 300.0,
    dead: Sequence[str] = (),
    seed: int | None = None,
) -> EquityResult:
    """Equity del héroe contra uno o varios rivales, cada uno con su rango.

    :param hero: las 2 cartas del héroe.
    :param board: 0, 3, 4 o 5 cartas comunitarias.
    :param villain_ranges: un ``Range`` por rival vivo en la mano.
    :param dead: cartas conocidas fuera de juego (p. ej. mostradas por un rival que foldeó).
    :param seed: semilla para resultados reproducibles (tests).
    """
    if len(hero) != 2:
        raise ValueError("El héroe debe tener exactamente 2 cartas")
    if len(board) not in (0, 3, 4, 5):
        raise ValueError("El board debe tener 0, 3, 4 o 5 cartas")
    if not villain_ranges:
        raise ValueError("Hace falta al menos un rango de rival")
    known = list(hero) + list(board) + list(dead)
    if len(set(known)) != len(known):
        raise ValueError(f"Cartas repetidas entre mano/board/muertas: {known}")

    rnd = random.Random(seed)
    # Card removal: fuera los combos que chocan con cartas ya conocidas
    ranges = [r.remove_dead(known) for r in villain_ranges]
    for i, r in enumerate(ranges):
        if not len(r):
            raise ValueError(f"El rango del rival {i} queda vacío tras quitar cartas conocidas")
    samplers = [r.sampler(rnd) for r in ranges]

    hero_l, board_l = list(hero), list(board)
    deck = remaining_deck(known)
    missing = 5 - len(board_l)
    budget_s = time_budget_ms / 1000.0

    total_share = wins = ties = 0.0
    done = 0        # iteraciones válidas (las que cuentan para la media)
    attempts = 0    # incluye las descartadas por colisión de cartas entre rivales
    start = time.perf_counter()

    while done < iterations and attempts < iterations * 3:
        attempts += 1
        if attempts % _CLOCK_EVERY == 0 and time.perf_counter() - start > budget_s:
            break

        # 1) Manos de los rivales sin colisiones entre ellos
        used: set[str] = set()
        villains: list[tuple[str, str]] = []
        for sample in samplers:
            for _ in range(_MAX_SAMPLE_TRIES):
                a, b = sample()
                if a not in used and b not in used:
                    break
            else:
                villains = []
                break
            used.add(a)
            used.add(b)
            villains.append((a, b))
        if len(villains) != len(samplers):
            continue    # iteración descartada: no sesga la media

        # 2) Completar el board
        if missing:
            runout: list[str] = []
            while len(runout) < missing:
                c = deck[rnd.randrange(len(deck))]
                if c not in used:
                    used.add(c)
                    runout.append(c)
            full_board = board_l + runout
        else:
            full_board = board_l

        # 3) Showdown
        hero_s = hand_strength(hero_l + full_board)
        best_villain = max(hand_strength([a, b] + full_board) for a, b in villains)
        if hero_s > best_villain:
            wins += 1
            total_share += 1
        elif hero_s == best_villain:
            n_tied = 1 + sum(
                1 for a, b in villains if hand_strength([a, b] + full_board) == hero_s
            )
            ties += 1
            total_share += 1.0 / n_tied
        done += 1

    elapsed = (time.perf_counter() - start) * 1000
    if done == 0:
        raise ValueError("Los rangos de los rivales son incompatibles entre sí")
    n = done
    return EquityResult(
        equity=total_share / n,
        win=wins / n,
        tie=ties / n,
        iterations=done,
        elapsed_ms=elapsed,
    )
