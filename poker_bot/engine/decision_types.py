"""Tipos de salida del motor de decisión."""

from __future__ import annotations

from dataclasses import dataclass, field

from poker_bot.core.game_state import ActionType

_LABELS = {
    ActionType.FOLD: "TIRAR",
    ActionType.CHECK: "PASAR",
    ActionType.CALL: "PAGAR",
    ActionType.BET: "APOSTAR",
    ActionType.RAISE: "SUBIR",
    ActionType.ALL_IN: "ALL-IN",
}


@dataclass
class Option:
    """Una acción evaluada (para mostrar alternativas en el overlay)."""
    action: ActionType
    amount: float           # para BET/RAISE/ALL_IN: cantidad total en la calle ("subir a")
    ev: float | None        # en fichas, relativo a tirarse ahora (fold = 0)
    note: str = ""


@dataclass
class Decision:
    action: ActionType
    amount: float = 0.0     # CALL: lo que se paga; BET/RAISE/ALL_IN: total en la calle
    ev: float | None = None
    equity: float | None = None
    reason: str = ""
    big_blind: float = 1.0
    alternatives: list[Option] = field(default_factory=list)
    elapsed_ms: float = 0.0

    @property
    def ev_bb(self) -> float | None:
        return None if self.ev is None else self.ev / self.big_blind

    def headline(self, chips_per_bb: float | None = None) -> str:
        """Texto corto para el overlay: ``SUBIR a 7.5 (3 BB)``.

        ``chips_per_bb``: si las cantidades internas están en ciegas pero la mesa
        muestra fichas, la cantidad principal se da en fichas (lo que se escribe).
        """
        label = _LABELS[self.action]
        if self.action in (ActionType.FOLD, ActionType.CHECK):
            return label
        bbs = f"{self.amount / self.big_blind:.1f}".rstrip("0").rstrip(".")
        if chips_per_bb:
            amount = f"{round(self.amount / self.big_blind * chips_per_bb, 2):g}"
        else:
            amount = f"{self.amount:g}"
        prep = " a " if self.action in (ActionType.RAISE, ActionType.BET) else " "
        return f"{label}{prep}{amount} ({bbs} BB)"

    def speech(self) -> str:
        """Frase corta para el aviso por voz."""
        if self.action in (ActionType.FOLD, ActionType.CHECK, ActionType.ALL_IN):
            return {ActionType.FOLD: "Tira", ActionType.CHECK: "Pasa",
                    ActionType.ALL_IN: "All in"}[self.action]
        bbs = round(self.amount / self.big_blind, 1)
        verb = {ActionType.CALL: "Paga", ActionType.BET: "Apuesta", ActionType.RAISE: "Sube a"}[self.action]
        return f"{verb} {bbs:g} ciegas"

    def __str__(self) -> str:
        parts = [self.headline()]
        if self.equity is not None:
            parts.append(f"equity {self.equity:.0%}")
        if self.ev_bb is not None:
            parts.append(f"EV {self.ev_bb:+.1f} BB")
        return " · ".join(parts) + (f"\n{self.reason}" if self.reason else "")
