"""Decisión postflop por **valor esperado (EV)** de cada acción.

Para cada opción se estima el EV en fichas, relativo a tirarse ahora (= 0):

* ``check``  ≈ equity · R · bote
* ``call``   ≈ equity_vs_rango_de_apuesta · R · (bote + a_pagar) − a_pagar + implícitas
* ``bet/raise`` de tamaño S:
      EV = FE · bote + (1 − FE) · (equity_si_paga · R · (bote + S + pago_rival) − S)

donde R es la "realización" de equity (fuera de posición se realiza menos),
FE la probabilidad de que todos se retiren y ``equity_si_paga`` la equity
contra la parte del rango que continúa.

**Modelo de defensa del rival.** Ante una apuesta S, cada rival defiende la
frecuencia mínima que impide un farol automático (MDF = bote / (bote + S);
repartida entre varios rivales) corregida por su ``fold_factor``. Defiende
con la parte más fuerte de su rango. El umbral de fuerza se fija sobre su
rango *sin* quitar nuestras cartas; al quitarlas después, si bloqueamos sus
manos buenas la FE sube: así se premian los **bloqueadores**.

Con este modelo, contra un rival "equilibrado" un farol sin equity tiene
EV ≈ 0 y lo que decide son los bloqueadores y los proyectos (semi-faroles).
Contra una calling station (fold_factor < 1) los faroles pierden y las
apuestas de valor finas ganan; contra quien se tira mucho, al revés.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Mapping

from poker_bot.core.game_state import ActionType, GameState, Street
from poker_bot.engine.board import analyze_board, detect_draws
from poker_bot.engine.decision_types import Decision, Option
from poker_bot.engine.equity import calculate_equity
from poker_bot.engine.evaluator import hand_category
from poker_bot.engine.opponents import OpponentStats, unknown
from poker_bot.engine.ranges import Range
from poker_bot.engine.villain_range import combo_scores, continuing_range, estimate_ranges

# Tamaños de apuesta (fracción del bote) según calle y textura
BET_SIZES = {
    (Street.FLOP, "seco"): (0.25, 0.33, 0.5),
    (Street.FLOP, "medio"): (0.33, 0.5, 0.75),
    (Street.FLOP, "mojado"): (0.5, 0.75, 1.0),
    (Street.TURN, "seco"): (0.5, 0.75),
    (Street.TURN, "medio"): (0.5, 0.75, 1.0),
    (Street.TURN, "mojado"): (0.66, 1.0, 1.25),
    (Street.RIVER, "seco"): (0.33, 0.75, 1.5),
    (Street.RIVER, "medio"): (0.33, 0.75, 1.5),
    (Street.RIVER, "mojado"): (0.5, 1.0, 1.5),
}
# Realización de equity: (en posición, fuera de posición)
REALIZATION = {Street.FLOP: (0.95, 0.80), Street.TURN: (0.98, 0.88), Street.RIVER: (1.0, 1.0)}
# Si tras apostar queda detrás menos de esta fracción del bote resultante: all-in
COMMIT_RATIO = 0.35
# Diferencia de EV (en fracción del bote) por debajo de la cual se mezclan acciones
MIX_THRESHOLD = 0.03
# Margen de EV (fracción del bote) que debe superar un farol sin proyecto
BLUFF_MARGIN = 0.04
# Parte de las odds implícitas que se espera cobrar al ligar un proyecto
IMPLIED_SHARE = 0.3

_CATEGORY_ES = {
    "high_card": "carta alta", "pair": "pareja", "two_pair": "doble pareja", "trips": "trío",
    "straight": "escalera", "flush": "color", "full_house": "full", "quads": "póker",
    "straight_flush": "escalera de color",
}


@dataclass
class _Villain:
    seat: int
    profile: OpponentStats
    rng: Range                     # rango estimado (sin quitar nuestras cartas)
    scores: dict
    stack_total: float             # stack + apuesta actual
    strong_frac: float             # parte del rango con doble pareja o mejor: nunca se retira


@dataclass
class _Eval:
    option: Option
    fe: float = 0.0
    eq_called: float = 0.0
    size_frac: float = 0.0


def decide_postflop(state: GameState, profiles: Mapping[str, OpponentStats],
                    rng: random.Random, budget_ms: float) -> Decision:
    hero = state.hero
    board = list(state.board)
    street = state.street
    hero_cards = list(state.hero_cards)
    pot = state.pot
    to_call = state.to_call
    bb = state.big_blind
    stack_total = hero.stack + hero.bet

    ranges = estimate_ranges(state, profiles)
    villains = []
    for p in state.opponents_in_hand:
        prof = profiles.get(p.name) or unknown(p.name)
        r = ranges[p.seat]
        villains.append(_Villain(p.seat, prof, r, combo_scores(r, board), p.stack + p.bet,
                                 _strong_fraction(r, board)))
    all_ranges = [v.rng for v in villains]

    texture = analyze_board(board)
    draws = detect_draws(hero_cards, board)
    ip = state.hero_in_position()
    realization = REALIZATION[street][0 if ip else 1]

    sizes = _candidate_sizes(state, street, texture.category, stack_total, villains)
    n_runs = 1 + len(sizes)
    per_run = max(40.0, budget_ms * 0.85 / n_runs)

    eq_full = calculate_equity(hero_cards, board, all_ranges, time_budget_ms=per_run).equity
    evals: list[_Eval] = []

    # --- Opciones pasivas -------------------------------------------------
    if to_call == 0:
        evals.append(_Eval(Option(ActionType.CHECK, 0.0, eq_full * realization * pot)))
    else:
        evals.append(_Eval(Option(ActionType.FOLD, 0.0, 0.0)))
        implied = 0.0
        if street is not Street.RIVER and draws.is_strong and to_call < hero.stack:
            behind = max(v.stack_total for v in villains) - state.current_bet
            p_hit = draws.outs / (52 - len(board) - 2)
            implied = p_hit * IMPLIED_SHARE * min(max(behind, 0.0), pot)
        call_ev = eq_full * realization * (pot + to_call) - to_call + implied
        call_action = ActionType.ALL_IN if to_call >= hero.stack else ActionType.CALL
        call_amount = stack_total if call_action is ActionType.ALL_IN else to_call
        note = "implícitas" if implied else ""
        evals.append(_Eval(Option(call_action, call_amount, call_ev, note)))

    # --- Apuestas / subidas ------------------------------------------------
    for raise_to in sizes:
        evals.append(_evaluate_aggression(state, villains, hero_cards, board, raise_to,
                                          stack_total, realization, per_run))

    # Los faroles sin proyecto solo se eligen si ganan con margen: así no se
    # farolea con todo el aire (EV ≈ 0 en equilibrio) sino con los mejores
    # candidatos (bloqueadores, rivales que se tiran de más).
    def rank(e: _Eval) -> float:
        bluff = e.option.action in (ActionType.BET, ActionType.RAISE, ActionType.ALL_IN) \
            and e.eq_called < 0.25 and not draws.any and e.fe > 0
        return e.option.ev - (BLUFF_MARGIN * pot if bluff else 0.0)

    evals.sort(key=rank, reverse=True)
    best = evals[0]
    mixed = False
    if len(evals) > 1:
        gap = rank(best) - rank(evals[1])
        if gap < MIX_THRESHOLD * pot and rng.random() < 0.5 * (1 - gap / (MIX_THRESHOLD * pot)):
            best, mixed = evals[1], True

    reason = _reason(best, eq_full, state, texture.describe(), draws.describe(),
                     hero_cards, board, villains, mixed)
    return Decision(
        action=best.option.action,
        amount=best.option.amount,
        ev=best.option.ev,
        equity=eq_full,
        reason=reason,
        big_blind=bb,
        alternatives=[e.option for e in evals],
    )


_STRONG = {"two_pair", "trips", "straight", "flush", "full_house", "quads", "straight_flush"}


def _strong_fraction(rng: Range, board: list[str]) -> float:
    total = strong = 0.0
    board_pair = hand_category(board) if len(board) == 5 else ""
    for (a, b), w in rng:
        cat = hand_category([a, b, *board])
        total += w
        # Si el board ya trae la jugada (p. ej. doble pareja en la mesa) no cuenta
        if cat in _STRONG and cat != board_pair:
            strong += w
    return strong / total if total else 0.0


def _candidate_sizes(state: GameState, street: Street, category: str, stack_total: float,
                     villains: list[_Villain]) -> list[float]:
    """Cantidades "subir a" candidatas, ya ajustadas a stacks y compromiso."""
    hero = state.hero
    pot = state.pot
    current = state.current_bet
    if hero.stack <= state.to_call:
        return []                               # solo puede pagar (all-in) o tirar
    # Nadie puede pagar más que el mayor stack rival
    cap = min(stack_total, max(v.stack_total for v in villains))
    if cap <= current:
        return []
    raw: list[float] = []
    if current == 0:
        raw = [f * pot for f in BET_SIZES[(street, category)]]
        if hero.stack <= 3 * pot:
            raw.append(stack_total)
    else:
        mults = (2.5,) if street is Street.RIVER else (2.5, 3.2)
        raw = [current * m for m in mults]
        # All-in como subida solo con SPR bajo; con stacks profundos es tirar fichas
        if hero.stack <= 3 * (pot + state.to_call):
            raw.append(stack_total)
    out: list[float] = []
    for amount in raw:
        amount = min(max(amount, current + state.big_blind), cap)
        # Compromiso: si queda poco detrás, mejor meterlo todo
        pot_after = pot + (amount - hero.bet) * 2
        if stack_total - amount < COMMIT_RATIO * pot_after:
            amount = cap
        amount = round(amount, 2)
        if amount not in out:
            out.append(amount)
    return out


def _evaluate_aggression(state: GameState, villains: list[_Villain], hero_cards: list[str],
                         board: list[str], raise_to: float, stack_total: float,
                         realization: float, budget_ms: float) -> _Eval:
    hero = state.hero
    pot = state.pot
    invest = raise_to - hero.bet                  # fichas nuevas que pone el héroe
    n = len(villains)
    mdf = pot / (pot + invest)
    share = mdf ** (1.0 / n)                      # la defensa se reparte entre varios rivales

    fold_all = 1.0
    cont_ranges: list[Range] = []
    expected_callers = 0.0
    call_amounts = []
    for v in villains:
        defend = 1.0 - (1.0 - share) * v.profile.fold_factor
        # Por grande que sea la apuesta, nadie tira doble pareja o mejor
        defend = max(0.03, v.strong_frac, min(0.97, defend))
        cont = continuing_range(v.rng, board, defend, v.scores)
        # Bloqueadores: el umbral se fijó sin nuestras cartas; ahora las quitamos
        full_unblocked = v.rng.remove_dead(hero_cards).combo_count
        cont_unblocked = cont.remove_dead(hero_cards)
        p_continue = cont_unblocked.combo_count / full_unblocked if full_unblocked else 0.0
        fold_all *= 1.0 - p_continue
        expected_callers += p_continue
        if cont_unblocked.combo_count > 0:
            cont_ranges.append(cont_unblocked)
        call_amounts.append(min(raise_to, v.stack_total) - state.player(v.seat).bet)

    fe = fold_all
    if cont_ranges:
        eq_called = calculate_equity(hero_cards, board, cont_ranges, time_budget_ms=budget_ms).equity
    else:
        eq_called = 1.0
    callers = max(1.0, expected_callers / max(1e-9, 1.0 - fe)) if fe < 1 else 1.0
    avg_call = sum(call_amounts) / len(call_amounts)
    pot_if_called = pot + invest + callers * avg_call
    ev = fe * pot + (1 - fe) * (eq_called * realization * pot_if_called - invest)

    if raise_to >= stack_total - 1e-9:
        action = ActionType.ALL_IN
    elif state.current_bet > 0:
        action = ActionType.RAISE
    else:
        action = ActionType.BET
    return _Eval(Option(action, raise_to, ev, f"FE {fe:.0%}, eq si paga {eq_called:.0%}"),
                 fe=fe, eq_called=eq_called, size_frac=invest / pot if pot else 0.0)


def _reason(best: _Eval, eq: float, state: GameState, texture: str, draw_text: str,
            hero_cards: list[str], board: list[str], villains: list[_Villain], mixed: bool) -> str:
    made = _CATEGORY_ES.get(hand_category(hero_cards + board), "")
    hand = made + (f" + {draw_text}" if draw_text else "")
    a = best.option.action
    if a is ActionType.CHECK:
        text = f"Pasar con {hand} (equity {eq:.0%}): apostar no mejora el EV en board {texture}."
    elif a is ActionType.FOLD:
        text = f"Tirar {hand}: equity {eq:.0%} < pot odds {state.pot_odds:.0%}."
    elif a in (ActionType.CALL,) or (a is ActionType.ALL_IN and best.fe == 0 and state.to_call >= state.hero.stack):
        extra = " contando implícitas" if best.option.note == "implícitas" else ""
        text = f"Pagar con {hand}: equity {eq:.0%} vs pot odds {state.pot_odds:.0%}{extra}."
    else:
        if draw_text and made in ("carta alta", "pareja") and best.eq_called < 0.6:
            kind = "Semi-farol"
        elif best.eq_called >= 0.5:
            kind = "Valor"
        elif draw_text:
            kind = "Semi-farol"
        else:
            kind = "Farol"
        if a is ActionType.ALL_IN:
            verb = "all-in"
        elif a is ActionType.RAISE:
            verb = f"subida a {best.option.amount:g}"
        elif best.size_frac > 1.0:
            verb = f"overbet de {best.size_frac:.0%} del bote"
        else:
            verb = f"{best.size_frac:.0%} del bote"
        text = (f"{kind} con {hand}: {verb} en board {texture}. "
                f"Se retiran ~{best.fe:.0%}; si pagan, equity {best.eq_called:.0%}.")
    if mixed:
        text += " (Mezcla: EV casi igual a la alternativa.)"
    styles = [v.profile.summary().split(" · ")[0] for v in villains if v.profile.reliable]
    if styles:
        text += " Rival: " + "; ".join(styles) + "."
    return text
