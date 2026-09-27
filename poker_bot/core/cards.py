"""Representación de cartas.

Una carta es simplemente un string canónico de 2 caracteres: rango + palo,
por ejemplo ``"As"`` (as de picas) o ``"Td"`` (diez de diamantes).

Usar strings mantiene el resto del código legible y desacoplado del
evaluador concreto (eval7 o treys); la conversión a sus tipos internos se
hace una sola vez y se cachea en ``engine/evaluator.py``.
"""

from __future__ import annotations

from typing import Iterable

RANKS = "23456789TJQKA"   # de menor a mayor
SUITS = "shdc"            # picas, corazones, diamantes, tréboles

# Valor numérico de cada rango (2 -> 0 ... A -> 12)
RANK_VALUE = {r: i for i, r in enumerate(RANKS)}

FULL_DECK: tuple[str, ...] = tuple(r + s for r in RANKS for s in SUITS)

# Alias habituales que puede devolver un OCR o escribir una persona
_RANK_ALIASES = {"10": "T", "1": "A"}
_SUIT_ALIASES = {
    "♠": "s", "♥": "h", "♦": "d", "♣": "c",
    "S": "s", "H": "h", "D": "d", "C": "c",
}


class InvalidCardError(ValueError):
    """Se lanza cuando un texto no representa una carta válida."""


def parse_card(text: str) -> str:
    """Normaliza un texto a carta canónica. ``"10♥"`` -> ``"Th"``, ``"as"`` -> ``"As"``."""
    t = text.strip()
    if len(t) < 2:
        raise InvalidCardError(f"Carta inválida: {text!r}")
    rank, suit = t[:-1], t[-1]
    rank = _RANK_ALIASES.get(rank, rank).upper()
    suit = _SUIT_ALIASES.get(suit, suit).lower()
    if rank not in RANK_VALUE or suit not in SUITS:
        raise InvalidCardError(f"Carta inválida: {text!r}")
    return rank + suit


def parse_cards(text: str | Iterable[str]) -> list[str]:
    """Convierte ``"AsKd"``, ``"As Kd"`` o ``["As", "Kd"]`` en una lista de cartas.

    Lanza ``InvalidCardError`` si hay cartas repetidas.
    """
    if isinstance(text, str):
        compact = text.replace(" ", "").replace(",", "")
        tokens: list[str] = []
        i = 0
        while i < len(compact):
            # "10" ocupa dos caracteres de rango
            step = 3 if compact[i:i + 2] == "10" else 2
            tokens.append(compact[i:i + step])
            i += step
    else:
        tokens = list(text)
    cards = [parse_card(t) for t in tokens]
    if len(set(cards)) != len(cards):
        raise InvalidCardError(f"Cartas repetidas: {cards}")
    return cards


def remaining_deck(dead: Iterable[str]) -> list[str]:
    """Baraja completa sin las cartas indicadas (en orden estable)."""
    dead_set = set(dead)
    return [c for c in FULL_DECK if c not in dead_set]


def hand_class(c1: str, c2: str) -> str:
    """Clase preflop de una mano concreta: ``("Ks", "Ah")`` -> ``"AKo"``, ``("7d", "7c")`` -> ``"77"``."""
    r1, r2 = c1[0], c2[0]
    if RANK_VALUE[r1] < RANK_VALUE[r2]:
        r1, r2 = r2, r1
    if r1 == r2:
        return r1 + r2
    return r1 + r2 + ("s" if c1[1] == c2[1] else "o")
