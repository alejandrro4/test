"""Interpretación de las acciones de la mano.

Convierte la lista de ``Action`` de ``GameState`` en hechos útiles para
decidir: quién abrió, cuántas subidas hubo, quién pagó, qué papel tiene
cada rival (abridor, 3-bettor, limper...).

Si la capa de lectura no ha registrado acciones (p. ej. el bot se arrancó a
mitad de mano) se reconstruye lo esencial a partir de las apuestas visibles.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from poker_bot.core.game_state import ActionType, GameState, Street

_AGGRESSIVE = (ActionType.BET, ActionType.RAISE, ActionType.ALL_IN)


@dataclass
class PreflopSummary:
    raisers: list[int] = field(default_factory=list)      # asientos, en orden (abridor, 3-bettor...)
    raise_amounts: list[float] = field(default_factory=list)
    limpers: list[int] = field(default_factory=list)
    callers_last_raise: list[int] = field(default_factory=list)
    all_in_seats: list[int] = field(default_factory=list)
    roles: dict[int, str] = field(default_factory=dict)   # asiento -> "open", "3bet", "4bet+", "call", "limp", "check"

    @property
    def raise_count(self) -> int:
        return len(self.raisers)


def summarize_preflop(state: GameState) -> PreflopSummary:
    s = PreflopSummary()
    actions = [a for a in state.actions if a.street is Street.PREFLOP]
    current = state.big_blind
    if actions:
        for a in actions:
            if a.type is ActionType.POST_BLIND:
                continue
            is_raise = a.type in _AGGRESSIVE and a.amount > current + 1e-9
            if a.type is ActionType.ALL_IN:
                s.all_in_seats.append(a.seat)
            if is_raise:
                current = a.amount
                s.raisers.append(a.seat)
                s.raise_amounts.append(a.amount)
                s.callers_last_raise = []
                n = len(s.raisers)
                s.roles[a.seat] = "open" if n == 1 else ("3bet" if n == 2 else "4bet+")
            elif a.type in (ActionType.CALL, ActionType.ALL_IN):
                if s.raisers:
                    s.callers_last_raise.append(a.seat)
                    s.roles[a.seat] = "call"
                else:
                    s.limpers.append(a.seat)
                    s.roles[a.seat] = "limp"
            elif a.type is ActionType.CHECK:
                s.roles.setdefault(a.seat, "check")
        return s

    # Sin historial: reconstrucción a partir de las apuestas de la calle
    if state.street is not Street.PREFLOP:
        return s
    bets = sorted((p for p in state.players if p.in_hand and p.bet > state.big_blind + 1e-9),
                  key=lambda p: p.bet)
    for i, p in enumerate(bets):
        if p.is_hero:
            continue
        s.raisers.append(p.seat)
        s.raise_amounts.append(p.bet)
        s.roles[p.seat] = "open" if i == 0 else ("3bet" if i == 1 else "4bet+")
    # Quien iguala exactamente la ciega grande sin ser la BB ha hecho limp
    bb_seat = _bb_seat(state)
    for p in state.players:
        if p.in_hand and not p.is_hero and p.seat != bb_seat and abs(p.bet - state.big_blind) < 1e-9:
            if not s.raisers:
                s.limpers.append(p.seat)
                s.roles[p.seat] = "limp"
    return s


def _bb_seat(state: GameState) -> int | None:
    order = state.preflop_order()
    if len(order) < 2:
        return None
    return order[-1]


def postflop_actions_by_seat(state: GameState) -> dict[int, list]:
    """Acciones postflop de cada asiento, en orden."""
    out: dict[int, list] = {}
    for a in state.actions:
        if a.street is not Street.PREFLOP and a.type is not ActionType.POST_BLIND:
            out.setdefault(a.seat, []).append(a)
    return out


def hero_was_preflop_aggressor(state: GameState) -> bool:
    s = summarize_preflop(state)
    return bool(s.raisers) and s.raisers[-1] == state.hero.seat


def street_aggressor(state: GameState) -> int | None:
    """Último asiento que apostó o subió en la calle actual (None si nadie)."""
    seat = None
    for a in state.actions:
        if a.street is state.street and a.type in _AGGRESSIVE:
            seat = a.seat
    if seat is None and state.current_bet > 0 and state.street is not Street.PREFLOP:
        top = max((p for p in state.players if p.in_hand), key=lambda p: p.bet)
        seat = None if top.is_hero else top.seat
    return seat
