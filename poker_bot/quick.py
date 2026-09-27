"""Construcción rápida de un ``GameState`` a partir de pocos datos.

Sirve para pedir una recomendación al instante sin leer la pantalla: se
indican la mano, el board, el bote y lo que ha hecho el rival, y se genera
una mesa "sintética" coherente con eso para el motor de decisión.
"""

from __future__ import annotations

from poker_bot.core.cards import parse_cards
from poker_bot.core.game_state import (
    POSITIONS_BY_SIZE, Action, ActionType, GameState, PlayerState, Street,
)

VILLAIN_PREFLOP_ROLES = ("call", "open", "3bet")


def preflop_state(hand: str, position: str, players: int = 6, stack: float = 100.0,
                  opener: str | None = None, open_size: float = 2.5, all_in: bool = False,
                  villain_names: dict[str, str] | None = None, big_blind: float = 1.0) -> GameState:
    """Situación preflop: sin nadie delante o frente a una apertura (o all-in).

    :param position: posición del héroe ("UTG", "HJ", "CO", "BTN", "SB", "BB"...).
    :param opener: posición del que ha abierto (None = nadie ha subido todavía).
    :param open_size: tamaño de la apertura en ciegas (o del all-in si ``all_in``).
    :param villain_names: nombre de jugador por posición, para usar su perfil.
    """
    names = POSITIONS_BY_SIZE[players]
    position, opener = position.upper(), opener.upper() if opener else None
    if position not in names or (opener and opener not in names):
        raise ValueError(f"Posiciones válidas con {players} jugadores: {', '.join(names)}")
    villain_names = villain_names or {}
    ps = [PlayerState(seat=i, name=villain_names.get(n, n), stack=stack, position=n)
          for i, n in enumerate(names)]
    by_pos = {p.position: p for p in ps}
    hero = by_pos[position]
    hero.is_hero, hero.name = True, "Héroe"

    sb, bb = (by_pos["BTN"], by_pos["BB"]) if players == 2 else (by_pos["SB"], by_pos["BB"])
    actions = [Action(sb.seat, ActionType.POST_BLIND, Street.PREFLOP, 0.5 * big_blind),
               Action(bb.seat, ActionType.POST_BLIND, Street.PREFLOP, big_blind)]
    sb.bet, bb.bet = 0.5 * big_blind, big_blind

    state = GameState(parse_cards(hand), [], 0.0, ps, dealer_seat=0, big_blind=big_blind,
                      is_hero_turn=True)
    order = state.preflop_order()
    for seat in order:
        p = state.player(seat)
        if p is hero:
            break
        if opener and p.position == opener:
            amount = open_size * big_blind
            p.bet = amount
            kind = ActionType.ALL_IN if all_in else ActionType.RAISE
            actions.append(Action(seat, kind, Street.PREFLOP, amount))
        else:
            p.in_hand = False
            actions.append(Action(seat, ActionType.FOLD, Street.PREFLOP))
    if opener and not any(a.type in (ActionType.RAISE, ActionType.ALL_IN) for a in actions):
        raise ValueError("El que abre tiene que hablar antes que el héroe")
    for p in ps:
        # El stack es lo que queda detrás; un all-in no deja nada
        p.stack = 0.0 if (all_in and p.position == opener) else p.stack - p.bet
    state.pot = sum(p.bet for p in ps)
    state.actions = actions
    return state


def postflop_state(hand: str, board: str, pot: float, to_call: float = 0.0,
                   stack: float = 100.0, villain_stack: float | None = None,
                   villains: int = 1, in_position: bool = True,
                   villain_preflop: str = "call", villain_checked: bool = False,
                   villain_names: list[str] | None = None, big_blind: float = 1.0) -> GameState:
    """Situación postflop simplificada.

    :param pot: bote total, incluida la apuesta del rival si la hay.
    :param to_call: apuesta del rival a la que nos enfrentamos (0 = nadie ha apostado).
    :param villain_preflop: qué hizo el rival preflop: "call" (pagó tu subida),
                            "open" (abrió y pagaste) o "3bet" (te 3-beteó y pagaste).
    :param villain_checked: el rival ha pasado en esta calle antes que tú.
    """
    if villain_preflop not in VILLAIN_PREFLOP_ROLES:
        raise ValueError(f"villain_preflop debe ser uno de {VILLAIN_PREFLOP_ROLES}")
    cards_board = parse_cards(board)
    street = Street.from_board(cards_board)
    if street is Street.PREFLOP:
        raise ValueError("Para preflop usa preflop_state()")
    n = villains + 1
    villain_stack = stack if villain_stack is None else villain_stack
    names = villain_names or [f"Rival{i + 1}" for i in range(villains)]

    # Asientos: 0..n-1. En posición = héroe en el botón; fuera = héroe justo tras el botón.
    hero_seat = 0
    dealer = hero_seat if in_position else n - 1
    ps = []
    v_idx = 0
    for seat in range(n):
        if seat == hero_seat:
            ps.append(PlayerState(seat, "Héroe", stack=stack, is_hero=True))
        else:
            ps.append(PlayerState(seat, names[v_idx], stack=villain_stack))
            v_idx += 1
    state = GameState(parse_cards(hand), cards_board, pot, ps, dealer_seat=dealer,
                      big_blind=big_blind, is_hero_turn=True)
    state.assign_positions()
    villains_ps = [p for p in ps if not p.is_hero]

    pre = Street.PREFLOP
    actions: list[Action] = []
    open_to, three_to = 2.5 * big_blind, 8.0 * big_blind
    if villain_preflop == "call":
        actions.append(Action(hero_seat, ActionType.RAISE, pre, open_to))
        actions += [Action(v.seat, ActionType.CALL, pre, open_to) for v in villains_ps]
    elif villain_preflop == "open":
        actions.append(Action(villains_ps[0].seat, ActionType.RAISE, pre, open_to))
        actions.append(Action(hero_seat, ActionType.CALL, pre, open_to))
        actions += [Action(v.seat, ActionType.CALL, pre, open_to) for v in villains_ps[1:]]
    else:  # 3bet
        actions.append(Action(hero_seat, ActionType.RAISE, pre, open_to))
        actions.append(Action(villains_ps[0].seat, ActionType.RAISE, pre, three_to))
        actions.append(Action(hero_seat, ActionType.CALL, pre, three_to))

    # Calles anteriores: se asume que se pasó (no hay más información)
    streets = [Street.FLOP, Street.TURN, Street.RIVER]
    for past in streets[:streets.index(street)]:
        actions += [Action(p.seat, ActionType.CHECK, past) for p in ps]

    if to_call > 0:
        bettor = villains_ps[0]
        bettor.bet = to_call
        bettor.stack = max(0.0, villain_stack - to_call)
        actions.append(Action(bettor.seat, ActionType.BET, street, to_call))
    elif villain_checked:
        actions += [Action(v.seat, ActionType.CHECK, street) for v in villains_ps]
    state.actions = actions
    return state
