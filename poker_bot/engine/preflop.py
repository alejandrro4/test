"""Decisión preflop.

Orden de prioridad:
  1. Si pagar compromete buena parte del stack (all-in rival, 5-bet...):
     decisión por **equity contra su rango** frente a las pot odds.
  2. Stacks cortos (≤ 12 ciegas) sin subida delante: **push/fold**.
  3. Resto: **tablas** de apertura / 3-bet / 4-bet / defensa, con frecuencias
     mixtas y ajustes explotativos según los rivales.
"""

from __future__ import annotations

import random
from typing import Mapping

from poker_bot.core.cards import hand_class
from poker_bot.core.game_state import ActionType, GameState
from poker_bot.engine.decision_types import Decision
from poker_bot.engine.equity import calculate_equity
from poker_bot.engine.history import PreflopSummary, summarize_preflop
from poker_bot.engine.opponents import OpponentStats, unknown
from poker_bot.engine.preflop_charts import (
    VS_3BET_EARLY_OPEN, VS_3BET_LATE_OPEN, VS_4BET, VS_OPEN, push_percent, rfi_range_text,
)
from poker_bot.engine.ranges import Range
from poker_bot.engine.villain_range import estimate_ranges

SHORT_STACK_BB = 12          # por debajo: push/fold
COMMIT_FRACTION = 0.4        # si una subida pone ≥ 40 % del stack, mejor all-in
LIMP_CALL = "22-99,A2s-A9s,KTs+,QTs+,JTs,T9s,98s,87s,76s,65s"


class _Ctx:
    """Datos de la situación que usan todas las ramas."""

    def __init__(self, state: GameState, profiles: Mapping[str, OpponentStats],
                 rng: random.Random, budget_ms: float):
        self.state = state
        self.profiles = profiles
        self.rng = rng
        self.budget_ms = budget_ms
        self.hero = state.hero
        self.combo = tuple(state.hero_cards)
        self.cls = hand_class(*state.hero_cards)
        self.bb = state.big_blind
        self.summary: PreflopSummary = summarize_preflop(state)
        self.behind = state.players_behind_preflop(self.hero.seat)
        self.heads_up = len(state.preflop_order()) == 2
        self.stack_total = self.hero.stack + self.hero.bet      # lo máximo que puede tener en la calle
        self.eff_bb = state.effective_stack_bb
        if self.behind == 0:
            self.cat = "bb"
        elif self.behind == 1 and not self.heads_up:
            self.cat = "sb"
        else:
            self.cat = "ip"

    def profile(self, seat: int) -> OpponentStats:
        name = self.state.player(seat).name
        return self.profiles.get(name) or unknown(name)

    def weight(self, text: str) -> float:
        return Range.parse(text).weight(self.combo) if text else 0.0

    def raise_to(self, amount: float) -> tuple[ActionType, float]:
        """Convierte una subida en all-in si compromete demasiado stack."""
        if amount >= COMMIT_FRACTION * self.stack_total:
            return ActionType.ALL_IN, self.stack_total
        return ActionType.RAISE, round(amount, 2)

    def decision(self, action: ActionType, amount: float = 0.0, reason: str = "",
                 ev: float | None = None, equity: float | None = None) -> Decision:
        if action is ActionType.CALL:
            amount = self.state.to_call
            if amount >= self.hero.stack:
                action, amount = ActionType.ALL_IN, self.stack_total
        if action is ActionType.FOLD and self.state.to_call == 0:
            action = ActionType.CHECK       # nunca tirarse gratis
        return Decision(action, amount, ev=ev, equity=equity, reason=reason, big_blind=self.bb)


def _mixed(ctx: _Ctx, w_raise: float, w_call: float) -> str:
    """Tira el dado de las frecuencias mixtas: devuelve 'raise', 'call' o 'fold'."""
    p_call = min(w_call, 1.0 - w_raise)
    r = ctx.rng.random()
    if r < w_raise:
        return "raise"
    if r < w_raise + p_call:
        return "call"
    return "fold"


def _exploit_3bet(text: str, fold_factor: float) -> Range:
    """Menos 3-bets de farol contra quien no se tira, más contra quien se tira mucho."""
    rng = Range.parse(text)
    if fold_factor < 0.8:
        return Range({c: w for c, w in rng if w >= 1.0})
    if fold_factor > 1.2:
        return Range({c: min(1.0, w * 1.6) for c, w in rng})
    return rng


# --------------------------------------------------------------------------- #
# Ramas
# --------------------------------------------------------------------------- #
def _equity_call(ctx: _Ctx, why: str) -> Decision:
    """Pagar o no según equity contra el rango estimado y las pot odds."""
    state = ctx.state
    ranges = list(estimate_ranges(state, ctx.profiles).values())
    eq = calculate_equity(state.hero_cards, [], ranges, time_budget_ms=ctx.budget_ms).equity
    call = state.to_call
    ev = eq * (state.pot + call) - call
    need = state.pot_odds
    if eq >= need + 0.02:
        return ctx.decision(ActionType.CALL, ev=ev, equity=eq,
                            reason=f"{why}: equity {eq:.0%} ≥ pot odds {need:.0%}, pagar.")
    return ctx.decision(ActionType.FOLD, ev=0.0, equity=eq,
                        reason=f"{why}: equity {eq:.0%} < pot odds {need:.0%}, tirar.")


def _push_fold(ctx: _Ctx) -> Decision:
    pct = push_percent(ctx.behind, ctx.eff_bb)
    if ctx.summary.limpers:
        pct *= 0.8
    if Range.top_percent(pct).weight(ctx.combo) > 0:
        return ctx.decision(ActionType.ALL_IN, ctx.stack_total,
                            reason=f"Stack corto ({ctx.eff_bb:.0f} BB): {ctx.cls} entra en el top "
                                   f"{pct:.0f}% de push.")
    if ctx.cat == "bb" and ctx.state.to_call == 0:
        return ctx.decision(ActionType.CHECK, reason="Stack corto: pasar gratis desde la BB.")
    return ctx.decision(ActionType.FOLD, reason=f"Stack corto ({ctx.eff_bb:.0f} BB): {ctx.cls} "
                                                f"fuera del top {pct:.0f}% de push.")


def _unopened(ctx: _Ctx) -> Decision:
    state = ctx.state
    behind_seats = state.preflop_order()[-ctx.behind:] if ctx.behind else []
    folders = [ctx.profile(s).fold_factor for s in behind_seats]
    avg_ff = sum(folders) / len(folders) if folders else 1.0
    # Contra mesas que se tiran mucho, robamos más (tabla de una posición más tardía)
    steal_behind = ctx.behind - 1 if avg_ff > 1.2 and ctx.behind > 1 else ctx.behind
    text = rfi_range_text(steal_behind, ctx.heads_up)
    w = ctx.weight(text)
    size = 3.0 if ctx.cat == "sb" else (2.2 if ctx.eff_bb <= 25 else 2.5)
    pos = ctx.hero.position or f"{ctx.behind} detrás"
    if _mixed(ctx, w, 0.0) == "raise":
        action, amount = ctx.raise_to(size * ctx.bb)
        extra = " (ampliado: los de detrás se tiran mucho)" if steal_behind != ctx.behind else ""
        return ctx.decision(action, amount,
                            reason=f"Apertura desde {pos}: {ctx.cls} está en el rango{extra}.")
    return ctx.decision(ActionType.FOLD, reason=f"{ctx.cls} fuera del rango de apertura de {pos}.")


def _limped(ctx: _Ctx) -> Decision:
    n_limp = len(ctx.summary.limpers)
    iso = rfi_range_text(min(9, ctx.behind + n_limp + 1), ctx.heads_up)
    if _mixed(ctx, ctx.weight(iso), 0.0) == "raise":
        size = (3.0 + n_limp + (1.0 if ctx.cat in ("sb", "bb") else 0.0)) * ctx.bb
        action, amount = ctx.raise_to(size)
        return ctx.decision(action, amount,
                            reason=f"Aislar a {n_limp} limper(s) con {ctx.cls}.")
    if ctx.cat == "bb":
        return ctx.decision(ActionType.CHECK, reason="Pasar desde la BB y ver flop gratis.")
    if ctx.cat == "sb":
        if Range.top_percent(40).weight(ctx.combo):
            return ctx.decision(ActionType.CALL, reason="Completar la SB: precio muy barato con limpers.")
        return ctx.decision(ActionType.FOLD, reason=f"{ctx.cls} demasiado flojo incluso para completar.")
    if ctx.weight(LIMP_CALL):
        return ctx.decision(ActionType.CALL,
                            reason=f"Limp detrás con {ctx.cls}: buenas odds implícitas multiway.")
    return ctx.decision(ActionType.FOLD, reason=f"{ctx.cls} no juega en bote con limpers.")


def _vs_open(ctx: _Ctx) -> Decision:
    s = ctx.summary
    opener = s.raisers[0]
    opener_behind = ctx.state.players_behind_preflop(opener)
    if opener_behind == 1:
        opener_cat = "sb"
    else:
        opener_cat = "early" if opener_behind >= 4 else "late"
    key = (opener_cat, ctx.cat) if (opener_cat, ctx.cat) in VS_OPEN else ("late", ctx.cat)
    t3, tc = VS_OPEN[key]
    prof = ctx.profile(opener)
    r3 = _exploit_3bet(t3, prof.fold_factor)
    w3 = r3.weight(ctx.combo)
    wc = ctx.weight(tc)
    callers = len(s.callers_last_raise)
    if callers:
        w3 *= 0.8   # squeeze: algo más selectivo
    choice = _mixed(ctx, w3, wc)
    open_to = s.raise_amounts[0]
    who = ctx.state.player(opener).position or "rival"
    if choice == "raise":
        mult = 3.0 if ctx.cat == "ip" else 4.0
        action, amount = ctx.raise_to(open_to * mult + open_to * callers)
        kind = "valor" if Range.parse(t3).weight(ctx.combo) >= 1 else "farol con bloqueadores/jugabilidad"
        return ctx.decision(action, amount,
                            reason=f"3-bet de {kind} contra apertura de {who}"
                                   + (f" ({prof.style})." if prof.reliable else "."))
    if choice == "call":
        return ctx.decision(ActionType.CALL,
                            reason=f"Defender pagando contra apertura de {who}: {ctx.cls} juega bien postflop.")
    return ctx.decision(ActionType.FOLD, reason=f"{ctx.cls} no defiende contra apertura de {who}.")


def _vs_3bet(ctx: _Ctx) -> Decision:
    s = ctx.summary
    three_bettor = s.raisers[1]
    hero_open_behind = ctx.behind   # el héroe abrió desde su posición actual
    t4, t_ip, t_oop = VS_3BET_EARLY_OPEN if hero_open_behind >= 4 else VS_3BET_LATE_OPEN
    order = ctx.state.postflop_order()
    ip = order.index(ctx.hero.seat) > order.index(three_bettor)
    w4 = ctx.weight(t4)
    wc = ctx.weight(t_ip if ip else t_oop)
    choice = _mixed(ctx, w4, wc)
    three_to = s.raise_amounts[1]
    if choice == "raise":
        action, amount = ctx.raise_to(three_to * (2.3 if ip else 2.6))
        return ctx.decision(action, amount, reason=f"4-bet con {ctx.cls} contra el 3-bet.")
    if choice == "call":
        return ctx.decision(ActionType.CALL,
                            reason=f"Pagar el 3-bet {'en' if ip else 'fuera de'} posición con {ctx.cls}.")
    return ctx.decision(ActionType.FOLD, reason=f"{ctx.cls} no aguanta el 3-bet.")


def _vs_4bet(ctx: _Ctx) -> Decision:
    t5, tc = VS_4BET
    choice = _mixed(ctx, ctx.weight(t5), ctx.weight(tc))
    if choice == "raise":
        return ctx.decision(ActionType.ALL_IN, ctx.stack_total, reason=f"5-bet all-in con {ctx.cls}.")
    if choice == "call":
        # Si tras pagar queda poco detrás, mejor meterlo todo ya (fold equity)
        remaining = ctx.hero.stack - ctx.state.to_call
        if remaining < 1.5 * (ctx.state.pot + ctx.state.to_call):
            return ctx.decision(ActionType.ALL_IN, ctx.stack_total,
                                reason=f"Con {ctx.cls} y SPR tan bajo, all-in en vez de pagar.")
        return ctx.decision(ActionType.CALL, reason=f"Pagar el 4-bet con {ctx.cls}.")
    return ctx.decision(ActionType.FOLD, reason=f"{ctx.cls} no continúa contra un 4-bet.")


# --------------------------------------------------------------------------- #
# Punto de entrada
# --------------------------------------------------------------------------- #
def decide_preflop(state: GameState, profiles: Mapping[str, OpponentStats],
                   rng: random.Random, budget_ms: float) -> Decision:
    ctx = _Ctx(state, profiles, rng, budget_ms)
    s = ctx.summary
    hero_seat = ctx.hero.seat
    to_call = state.to_call

    # 1) Decisiones grandes: pagar compromete ≥ 30 % del stack
    if to_call > 0 and to_call >= 0.3 * ctx.hero.stack:
        return _equity_call(ctx, "Pago grande respecto al stack")

    # 2) Stacks cortos sin subida delante
    if not s.raisers and ctx.eff_bb <= SHORT_STACK_BB:
        return _push_fold(ctx)

    # 3) Tablas
    if not s.raisers:
        return _limped(ctx) if s.limpers else _unopened(ctx)
    if hero_seat not in s.raisers:
        if s.raise_count == 1:
            if ctx.eff_bb <= SHORT_STACK_BB * 1.5:
                pct = push_percent(ctx.behind, ctx.eff_bb) * 0.55
                if Range.top_percent(pct).weight(ctx.combo):
                    return ctx.decision(ActionType.ALL_IN, ctx.stack_total,
                                        reason=f"Stack corto: re-shove con {ctx.cls}.")
                return ctx.decision(ActionType.FOLD, reason=f"Stack corto: {ctx.cls} no re-shovea.")
            return _vs_open(ctx)
        return _equity_call(ctx, f"{s.raise_count} subidas delante")
    if s.raisers == [hero_seat, s.raisers[-1]] and s.raise_count == 2:
        return _vs_3bet(ctx)
    if s.raise_count == 3 and s.raisers[1] == hero_seat:
        return _vs_4bet(ctx)
    return _equity_call(ctx, "Guerra de subidas")
