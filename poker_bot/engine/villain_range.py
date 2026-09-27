"""Estimación del rango de cada rival a partir de lo que ha hecho en la mano.

1. **Preflop**: según su papel (abrió, pagó, 3-beteó, hizo limp...) y su
   posición, con las tablas de ``preflop_charts`` o, si hay suficientes
   manos registradas, con sus propias estadísticas (VPIP/PFR).
2. **Postflop**: en cada acción se estrecha el rango. Cada combo recibe una
   puntuación 0..1 (percentil de fuerza en ese board, con un mínimo para los
   proyectos) y:
     * apostar/subir -> se queda la parte alta + proyectos + algo de aire (faroles)
     * pagar         -> se va casi todo el aire, las manos muy fuertes bajan un
                        poco (a menudo habría subido)
     * pasar         -> las manos muy fuertes bajan (rango "capado")
"""

from __future__ import annotations

from typing import Mapping

from poker_bot.core.cards import hand_class
from poker_bot.core.game_state import ActionType, GameState, Street
from poker_bot.engine.board import detect_draws
from poker_bot.engine.evaluator import hand_strength
from poker_bot.engine.history import PreflopSummary, postflop_actions_by_seat, summarize_preflop
from poker_bot.engine.opponents import PRIOR_PFR, OpponentStats, unknown
from poker_bot.engine.preflop_charts import ASSUMED_3BET, ASSUMED_4BET, push_percent, rfi_range_text
from poker_bot.engine.ranges import HAND_RANKING, Combo, Range

_BOARD_BY_STREET = {Street.FLOP: 3, Street.TURN: 4, Street.RIVER: 5}


# --------------------------------------------------------------------------- #
# Preflop
# --------------------------------------------------------------------------- #
def _width(rng: Range) -> float:
    return 100.0 * rng.combo_count / 1326


def preflop_range(state: GameState, seat: int, summary: PreflopSummary,
                  profile: OpponentStats) -> Range:
    role = summary.roles.get(seat)
    player = state.player(seat)
    behind = state.players_behind_preflop(seat)
    heads_up = len(state.preflop_order()) == 2
    vpip = profile.vpip_percent
    pfr = profile.open_percent

    if role == "open":
        chart = Range.parse(rfi_range_text(behind, heads_up))
        if not profile.reliable:
            return chart
        # Sus aperturas son más o menos anchas que las de la tabla según su PFR
        return Range.top_percent(_width(chart) * profile.pfr_rate / PRIOR_PFR)

    if role in ("3bet", "4bet+"):
        stack_bb = (player.stack + player.bet) / state.big_blind
        if seat in summary.all_in_seats and stack_bb <= 25:
            return Range.top_percent(push_percent(behind, stack_bb) * 0.8)
        if role == "4bet+":
            return Range.parse(ASSUMED_4BET)
        if profile.reliable:
            return Range.top_percent(max(3.0, 100 * profile.three_bet_rate * 1.3))
        return Range.parse(ASSUMED_3BET)

    if role == "call":
        width = vpip * (1.4 if behind == 0 else 1.0)       # la BB defiende más ancho
        band = Range.top_percent(width)
        return band.minus(Range.top_percent(pfr * 0.4).scaled(0.7))

    if role == "limp":
        return Range.top_percent(vpip).minus(Range.top_percent(pfr).scaled(0.7))

    if role == "check":
        return Range.random().minus(Range.top_percent(pfr * 0.8).scaled(0.8))

    # Sin acción registrada (todavía no ha hablado o se leyó mal): genérico
    return Range.top_percent(min(100.0, vpip * 1.3))


# --------------------------------------------------------------------------- #
# Postflop
# --------------------------------------------------------------------------- #
def combo_scores(rng: Range, board: list[str]) -> dict[Combo, float]:
    """Puntuación 0..1 de cada combo en el board (percentil de fuerza + proyectos)."""
    board_set = set(board)
    combos = [(c, w) for c, w in rng if c[0] not in board_set and c[1] not in board_set]
    if not combos:
        return {}
    strength = {c: hand_strength([c[0], c[1], *board]) for c, _ in combos}
    ordered = sorted(combos, key=lambda cw: strength[cw[0]])
    total = sum(w for _, w in combos)
    scores: dict[Combo, float] = {}
    # Percentil ponderado; los empates en fuerza comparten percentil
    acc, i = 0.0, 0
    while i < len(ordered):
        j, block = i, 0.0
        while j < len(ordered) and strength[ordered[j][0]] == strength[ordered[i][0]]:
            block += ordered[j][1]
            j += 1
        pct = (acc + block / 2) / total
        for k in range(i, j):
            scores[ordered[k][0]] = pct
        acc += block
        i = j
    if len(board) < 5:
        for c, _ in combos:
            d = detect_draws(c, board)
            if d.is_strong:
                scores[c] = max(scores[c], 0.62)
            elif d.any:
                scores[c] = max(scores[c], 0.45)
    return scores


def narrow(rng: Range, board: list[str], action: ActionType, aggression: float = 1.0) -> Range:
    """Estrecha un rango tras una acción postflop."""
    scores = combo_scores(rng, board)
    out: dict[Combo, float] = {}
    for c, s in scores.items():
        w = rng.weight(c)
        if action is ActionType.BET:
            keep = min(0.9, 0.5 * aggression)
            w = w if s >= 1 - keep else w * min(0.5, 0.12 * aggression)
        elif action in (ActionType.RAISE, ActionType.ALL_IN):
            keep = min(0.8, 0.25 * aggression)
            w = w if s >= 1 - keep else w * min(0.3, 0.06 * aggression)
        elif action is ActionType.CALL:
            if s < 0.35:
                w *= 0.15
            elif s > 0.92:
                w *= 0.7
        elif action is ActionType.CHECK:
            if s > 0.85:
                w *= 0.45
        if w > 1e-6:
            out[c] = w
    return Range(out)


def continuing_range(rng: Range, board: list[str], fraction: float,
                     scores: dict[Combo, float] | None = None) -> Range:
    """La parte superior ``fraction`` (ponderada) del rango: la que sigue ante una apuesta.

    ``scores`` permite reutilizar ``combo_scores`` ya calculadas (es lo caro).
    """
    fraction = max(0.0, min(1.0, fraction))
    if scores is None:
        scores = combo_scores(rng, board) if len(board) >= 3 else _preflop_scores(rng)
    ordered = sorted(scores, key=scores.get, reverse=True)
    target = fraction * sum(rng.weight(c) for c in ordered)
    out: dict[Combo, float] = {}
    acc = 0.0
    for c in ordered:
        if acc >= target:
            break
        w = rng.weight(c)
        take = min(w, target - acc)
        out[c] = take
        acc += take
    return Range(out)


_CLASS_ORDER = {cls: i for i, cls in enumerate(HAND_RANKING)}


def _preflop_scores(rng: Range) -> dict[Combo, float]:
    return {c: 1 - _CLASS_ORDER[hand_class(*c)] / 169 for c, _ in rng}


# --------------------------------------------------------------------------- #
# Punto de entrada
# --------------------------------------------------------------------------- #
def estimate_ranges(state: GameState,
                    profiles: Mapping[str, OpponentStats] | None = None) -> dict[int, Range]:
    """Rango estimado de cada rival vivo, por asiento."""
    profiles = profiles or {}
    summary = summarize_preflop(state)
    by_seat = postflop_actions_by_seat(state)
    # Solo se quitan las cartas del board: las del héroe se quitan después al
    # calcular equity, así se puede medir el efecto de los bloqueadores.
    dead = list(state.board)
    out: dict[int, Range] = {}
    for p in state.opponents_in_hand:
        prof = profiles.get(p.name) or unknown(p.name)
        rng = preflop_range(state, p.seat, summary, prof).remove_dead(dead)
        for a in by_seat.get(p.seat, []):
            n = _BOARD_BY_STREET.get(a.street)
            if n and len(state.board) >= n:
                narrowed = narrow(rng, state.board[:n], a.type, prof.aggression_factor)
                if narrowed.combo_count > 0.5:   # nunca dejar un rango vacío por una mala lectura
                    rng = narrowed
        out[p.seat] = rng
    return out
