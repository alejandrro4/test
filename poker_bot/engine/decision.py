"""Punto de entrada del cerebro: ``decide(GameState) -> Decision``."""

from __future__ import annotations

import random
import time
from typing import Mapping

from poker_bot.core.game_state import ActionType, GameState, Street
from poker_bot.engine.decision_types import Decision
from poker_bot.engine.equity import calculate_equity
from poker_bot.engine.history import summarize_preflop
from poker_bot.engine.opponents import OpponentStats
from poker_bot.engine.postflop import decide_postflop
from poker_bot.engine.preflop import decide_preflop
from poker_bot.engine.villain_range import estimate_ranges

DEFAULT_BUDGET_MS = 1200.0


def decide(state: GameState,
           profiles: Mapping[str, OpponentStats] | None = None,
           budget_ms: float = DEFAULT_BUDGET_MS,
           seed: int | None = None) -> Decision:
    """Mejor acción para el héroe en ``state``.

    :param profiles: estadísticas de los rivales por nombre (las que falten se
                     tratan como desconocidos).
    :param budget_ms: tiempo máximo aproximado para las simulaciones.
    :param seed: fija el azar de las frecuencias mixtas (tests / repetición).
    """
    start = time.perf_counter()
    profiles = profiles or {}
    rng = random.Random(seed)
    if len(state.hero_cards) != 2:
        raise ValueError("Faltan las cartas del héroe")
    if not any(p.position for p in state.players):
        state.assign_positions()

    if not state.opponents_in_hand:
        decision = Decision(ActionType.CHECK, reason="No quedan rivales en la mano.",
                            big_blind=state.big_blind)
    elif state.street is Street.PREFLOP:
        decision = decide_preflop(state, profiles, rng, budget_ms)
        # Equity orientativa contra quien ya ha subido o pagado (para el overlay)
        # (solo contra quien ha metido dinero voluntariamente; los que aún no han
        # hablado probablemente se retiren)
        active = {seat for seat, role in summarize_preflop(state).roles.items() if role != "check"}
        if decision.equity is None and active:
            ranges = [r for seat, r in estimate_ranges(state, profiles).items() if seat in active]
            remaining = budget_ms - (time.perf_counter() - start) * 1000
            decision.equity = calculate_equity(
                state.hero_cards, [], ranges, time_budget_ms=max(50.0, min(200.0, remaining))
            ).equity
    else:
        decision = decide_postflop(state, profiles, rng, budget_ms)

    decision.elapsed_ms = (time.perf_counter() - start) * 1000
    return decision
