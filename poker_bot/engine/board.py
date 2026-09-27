"""Textura del board y detección de proyectos (draws).

La textura decide el tamaño de apuesta: en boards secos (K72 arcoíris) basta
una c-bet pequeña porque al rival casi nada le conecta; en boards mojados
(JT9 dos colores) hay que apostar grande para cobrar a los proyectos.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Sequence

from poker_bot.core.cards import RANK_VALUE, RANKS


def _straight_windows() -> list[set[int]]:
    """Las 10 escaleras posibles como conjuntos de valores (el as cuenta también como 1)."""
    wins = [set(range(lo, lo + 5)) for lo in range(0, 9)]   # 2-6 ... T-A
    wins.insert(0, {12, 0, 1, 2, 3})                         # A-2-3-4-5
    return wins


_WINDOWS = _straight_windows()


def _has_straight(values: set[int]) -> bool:
    return any(w <= values for w in _WINDOWS)


def straight_completing_ranks(cards: Sequence[str]) -> set[int]:
    """Valores de carta que, añadidos, formarían escalera (y que aún no la hay)."""
    values = {RANK_VALUE[c[0]] for c in cards}
    if _has_straight(values):
        return set()
    return {v for v in range(13) if v not in values and _has_straight(values | {v})}


@dataclass(frozen=True)
class BoardTexture:
    paired: bool             # hay al menos una pareja en el board
    monotone: bool           # 3+ cartas del mismo palo (color posible)
    two_tone: bool           # exactamente 2 del mismo palo (proyecto de color posible)
    straight_possible: bool  # 3 cartas dentro de una ventana de 5 valores
    connected: bool          # 2+ cartas consecutivas o con un hueco
    high_cards: int          # nº de cartas T o más altas
    wetness: float           # 0 = muy seco, 1 = muy mojado

    @property
    def category(self) -> str:
        if self.wetness < 0.3:
            return "seco"
        if self.wetness < 0.6:
            return "medio"
        return "mojado"

    def describe(self) -> str:
        tags = [self.category]
        if self.monotone:
            tags.append("monocolor")
        elif self.two_tone:
            tags.append("dos colores")
        if self.paired:
            tags.append("pareado")
        if self.straight_possible:
            tags.append("escalera posible")
        return ", ".join(tags)


def analyze_board(board: Sequence[str]) -> BoardTexture:
    if len(board) < 3:
        raise ValueError("La textura solo tiene sentido con flop, turn o river")
    suits = Counter(c[1] for c in board)
    ranks = Counter(c[0] for c in board)
    values = sorted({RANK_VALUE[r] for r in ranks})
    max_suit = max(suits.values())

    paired = max(ranks.values()) >= 2
    monotone = max_suit >= 3
    two_tone = max_suit == 2
    straight_possible = any(len(w & set(values)) >= 3 for w in _WINDOWS)
    # Conexión: valores a distancia 1 o 2 (contando el as bajo)
    ext = sorted(set(values) | ({-1} if 12 in values else set()))
    connected = any(b - a <= 2 for a, b in zip(ext, ext[1:]))
    high = sum(1 for c in board if RANK_VALUE[c[0]] >= RANK_VALUE["T"])

    wet = 0.0
    wet += 0.45 if monotone else (0.25 if two_tone else 0.0)
    wet += 0.35 if straight_possible else (0.15 if connected else 0.0)
    wet += 0.05 * high
    wet -= 0.15 if paired else 0.0
    return BoardTexture(
        paired=paired, monotone=monotone, two_tone=two_tone,
        straight_possible=straight_possible, connected=connected,
        high_cards=high, wetness=max(0.0, min(1.0, wet)),
    )


@dataclass(frozen=True)
class DrawInfo:
    flush_draw: bool
    nut_flush_draw: bool
    straight_outs: int      # 8 = escalera abierta (o doble gutshot), 4 = gutshot
    outs: int               # outs limpios aproximados (sin descontar solapes raros)

    @property
    def is_strong(self) -> bool:
        return self.flush_draw or self.straight_outs >= 8

    @property
    def any(self) -> bool:
        return self.flush_draw or self.straight_outs > 0

    def describe(self) -> str:
        parts = []
        if self.flush_draw:
            parts.append("proyecto de color" + (" al nuts" if self.nut_flush_draw else ""))
        if self.straight_outs >= 8:
            parts.append("escalera abierta")
        elif self.straight_outs:
            parts.append("gutshot")
        return " + ".join(parts)


NO_DRAW = DrawInfo(False, False, 0, 0)


def detect_draws(hole: Sequence[str], board: Sequence[str]) -> DrawInfo:
    """Proyectos del jugador que usan al menos una de sus cartas (solo flop y turn)."""
    if len(board) not in (3, 4):
        return NO_DRAW
    cards = list(hole) + list(board)

    # Color: 4 cartas de un palo, con al menos una propia, sin color hecho
    flush_draw = nut_fd = False
    suits = Counter(c[1] for c in cards)
    for suit, n in suits.items():
        if n == 4 and any(c[1] == suit for c in hole):
            flush_draw = True
            # Nut flush draw: tenemos la carta más alta de ese palo que no está en el board
            on_board = {c[0] for c in board if c[1] == suit}
            top_missing = next(r for r in reversed(RANKS) if r not in on_board)
            nut_fd = (top_missing + suit) in hole

    # Escalera: rangos que la completan con nuestras cartas y no solo con el board
    mine = straight_completing_ranks(cards)
    board_only = straight_completing_ranks(board)
    s_ranks = mine - board_only
    straight_outs = 4 * min(len(s_ranks), 2)

    outs = (9 if flush_draw else 0) + straight_outs
    if flush_draw and straight_outs:
        outs -= 2  # cartas que cuentan doble
    return DrawInfo(flush_draw, nut_fd, straight_outs, outs)
