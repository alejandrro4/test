"""Evaluador de manos con backend intercambiable.

Se usa ``eval7`` (C, muy rápido) si está instalado y, si no, ``treys``
(Python puro, instala en cualquier sistema). El resto del código solo ve
``hand_strength(cards)``, donde **mayor = mejor**.

Variable de entorno ``POKER_BOT_EVALUATOR=treys`` fuerza el respaldo.
"""

from __future__ import annotations

import os
from typing import Callable, Sequence

from poker_bot.core.cards import FULL_DECK

BACKEND: str

try:
    # POKER_BOT_EVALUATOR=treys fuerza el respaldo (útil para testearlo)
    if os.environ.get("POKER_BOT_EVALUATOR", "").lower() == "treys":
        raise ImportError
    import eval7 as _eval7

    BACKEND = "eval7"
    _CARD = {c: _eval7.Card(c) for c in FULL_DECK}

    def _strength(cards: Sequence[str]) -> int:
        return _eval7.evaluate([_CARD[c] for c in cards])

    def _category(cards: Sequence[str]) -> str:
        return _eval7.handtype(_strength(cards))

except ImportError:  # pragma: no cover - depende del entorno
    from treys import Card as _TCard, Evaluator as _TEvaluator

    BACKEND = "treys"
    _CARD = {c: _TCard.new(c) for c in FULL_DECK}
    _EV = _TEvaluator()
    _MAX_RANK = 7462  # peor mano posible en treys (menor = mejor)

    def _strength(cards: Sequence[str]) -> int:
        tc = [_CARD[c] for c in cards]
        # treys: menor = mejor, y separa "board" (3-5) de "mano" (2)
        return _MAX_RANK + 1 - _EV.evaluate(tc[2:], tc[:2])

    def _category(cards: Sequence[str]) -> str:
        tc = [_CARD[c] for c in cards]
        rank = _EV.evaluate(tc[2:], tc[:2])
        return _EV.class_to_string(_EV.get_rank_class(rank))


# Nombres de categoría unificados (treys y eval7 los escriben distinto)
_CATEGORY_ALIASES = {
    "Straight Flush": "straight_flush", "Four of a Kind": "quads", "Quads": "quads",
    "Full House": "full_house", "Flush": "flush", "Straight": "straight",
    "Three of a Kind": "trips", "Trips": "trips", "Two Pair": "two_pair",
    "Pair": "pair", "High Card": "high_card", "Royal Flush": "straight_flush",
}

hand_strength: Callable[[Sequence[str]], int] = _strength
"""Fuerza de una mano de 5 a 7 cartas. Mayor = mejor. Solo sirve para comparar."""


def hand_category(cards: Sequence[str]) -> str:
    """Categoría de la mano: ``"pair"``, ``"flush"``, ``"full_house"``..."""
    raw = _category(cards)
    return _CATEGORY_ALIASES.get(raw, raw.lower().replace(" ", "_"))
