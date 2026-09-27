"""Rangos de manos.

Un ``Range`` es un conjunto de combos concretos (``("As", "Kd")``) con un peso
entre 0 y 1 cada uno. Se construye desde la notación habitual de póker:

    "AA, KK, AKs, AQo"      manos sueltas
    "TT+"                   parejas de TT hacia arriba
    "22-55"                 parejas entre 22 y 55
    "ATs+"                  ATs, AJs, AQs, AKs (sube el kicker)
    "A2s-A5s"               intervalo de kicker
    "AK"                    AKs + AKo
    "AsKs"                  combo concreto
    "KQs:0.5"               peso parcial (se juega la mitad de las veces)

o con ``Range.top_percent(20)`` para el X% superior de manos.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from itertools import combinations
from typing import Iterable, Iterator

from poker_bot.core.cards import RANK_VALUE, RANKS, SUITS, hand_class, parse_card

Combo = tuple[str, str]

# Las 169 clases de manos ordenadas por equity contra una mano aleatoria
# (heads-up, 400k simulaciones cada una). Sirve para rangos "top X%".
HAND_RANKING: tuple[str, ...] = tuple("""
AA KK QQ JJ TT 99 88 AKs 77 AQs AJs AKo ATs AQo KQs AJo 66 A9s ATo KJs A8s KTs
KQo A7s A9o KJo 55 QJs K9s A6s A8o A5s KTo QTs A4s A7o K8s A3s QJo K9o A5o A6o
Q9s K7s JTs A2s QTo 44 A4o K6s K8o Q8s A3o J9s K5s Q9o JTo K7o A2o K4s Q7s K6o
T9s J8s K3s 33 Q6s Q8o K5o J9o K2s Q5s J7s K4o T8s Q4s Q7o J8o T9o K3o Q6o Q3s
98s T7s J6s K2o 22 Q2s Q5o J5s T8o J7o Q4o T6s J4s 97s J3s Q3o 98o 87s J6o T7o
96s J2s T5s Q2o J5o T4s 97o T6o J4o 86s T3s 95s J3o 76s 87o T2s 85s 96o J2o T5o
94s 75s T4o 93s 86o 65s 84s 95o T3o 92s 76o 74s T2o 85o 54s 64s 83s 94o 75o 82s
93o 73s 65o 53s 63s 84o 92o 43s 74o 72s 54o 64o 52s 62s 83o 42s 82o 73o 53o 63o
32s 43o 72o 52o 62o 42o 32o
""".split())


class RangeParseError(ValueError):
    """Notación de rango no reconocida."""


def combos_of_class(cls: str) -> list[Combo]:
    """Todos los combos de una clase: ``"AKs"`` -> 4, ``"AKo"`` -> 12, ``"AA"`` -> 6."""
    r1, r2 = cls[0], cls[1]
    if r1 == r2:
        return [(r1 + a, r2 + b) for a, b in combinations(SUITS, 2)]
    kind = cls[2] if len(cls) == 3 else ""
    out: list[Combo] = []
    for s1 in SUITS:
        for s2 in SUITS:
            suited = s1 == s2
            if (kind == "s" and not suited) or (kind == "o" and suited):
                continue
            out.append((r1 + s1, r2 + s2))
    return out


def _normalize_class(token: str) -> str:
    """``"KA"`` -> ``"AK"``, ``"kqs"`` -> ``"KQs"``. Valida los rangos."""
    r1, r2 = token[0].upper(), token[1].upper()
    suffix = token[2:].lower()
    if r1 not in RANK_VALUE or r2 not in RANK_VALUE or suffix not in ("", "s", "o"):
        raise RangeParseError(f"Mano inválida: {token!r}")
    if r1 == r2 and suffix:
        raise RangeParseError(f"Una pareja no puede ser suited/offsuit: {token!r}")
    if RANK_VALUE[r1] < RANK_VALUE[r2]:
        r1, r2 = r2, r1
    return r1 + r2 + suffix


def _expand_token(token: str) -> list[str]:
    """Expande un token (sin peso) a una lista de clases o combos concretos."""
    # Combo concreto: "AsKd"
    if len(token) == 4 and token[1].lower() in SUITS and token[3].lower() in SUITS:
        c1, c2 = parse_card(token[:2]), parse_card(token[2:])
        if c1 == c2:
            raise RangeParseError(f"Combo imposible: {token!r}")
        return [c1 + c2]

    # Intervalo: "22-55", "A2s-A5s"
    if "-" in token:
        lo, hi = (_normalize_class(t) for t in token.split("-"))
        if lo[0] == lo[1] and hi[0] == hi[1]:            # parejas
            a, b = sorted((RANK_VALUE[lo[0]], RANK_VALUE[hi[0]]))
            return [RANKS[v] * 2 for v in range(a, b + 1)]
        if lo[0] != hi[0] or lo[2:] != hi[2:]:
            raise RangeParseError(f"Intervalo inválido: {token!r}")
        a, b = sorted((RANK_VALUE[lo[1]], RANK_VALUE[hi[1]]))
        return [lo[0] + RANKS[v] + lo[2:] for v in range(a, b + 1)]

    # "Plus": "TT+", "ATs+"
    if token.endswith("+"):
        cls = _normalize_class(token[:-1])
        if cls[0] == cls[1]:
            return [RANKS[v] * 2 for v in range(RANK_VALUE[cls[0]], len(RANKS))]
        top = RANK_VALUE[cls[0]]
        return [cls[0] + RANKS[v] + cls[2:] for v in range(RANK_VALUE[cls[1]], top)]

    return [_normalize_class(token)]


@dataclass
class Range:
    weights: dict[Combo, float] = field(default_factory=dict)

    # ------------------------------------------------------------------ #
    # Construcción
    # ------------------------------------------------------------------ #
    @classmethod
    def parse(cls, text: str) -> "Range":
        rng = cls()
        for raw in text.replace(";", ",").split(","):
            raw = raw.strip()
            if not raw:
                continue
            weight = 1.0
            if ":" in raw:
                raw, w = raw.split(":", 1)
                weight = float(w)
                if not 0.0 <= weight <= 1.0:
                    raise RangeParseError(f"Peso fuera de [0, 1]: {w}")
            for item in _expand_token(raw.strip()):
                if len(item) == 4:   # combo concreto
                    rng.add((item[:2], item[2:]), weight)
                else:
                    for combo in combos_of_class(item):
                        rng.add(combo, weight)
        return rng

    @classmethod
    def from_classes(cls, classes: Iterable[str], weight: float = 1.0) -> "Range":
        rng = cls()
        for c in classes:
            for combo in combos_of_class(_normalize_class(c)):
                rng.add(combo, weight)
        return rng

    @classmethod
    def top_percent(cls, pct: float) -> "Range":
        """El ``pct``% superior de combos según ``HAND_RANKING``."""
        target = 1326 * max(0.0, min(pct, 100.0)) / 100.0
        rng, total = cls(), 0
        for c in HAND_RANKING:
            if total >= target:
                break
            for combo in combos_of_class(c):
                rng.add(combo)
            total += len(combos_of_class(c))
        return rng

    @classmethod
    def random(cls) -> "Range":
        return cls.top_percent(100)

    # ------------------------------------------------------------------ #
    # Operaciones
    # ------------------------------------------------------------------ #
    @staticmethod
    def _key(combo: Combo) -> Combo:
        """Orden canónico dentro del combo para evitar duplicados (AsKd == KdAs)."""
        a, b = combo
        return (a, b) if (RANK_VALUE[a[0]], a[1]) >= (RANK_VALUE[b[0]], b[1]) else (b, a)

    def add(self, combo: Combo, weight: float = 1.0) -> None:
        key = self._key(combo)
        self.weights[key] = max(self.weights.get(key, 0.0), weight)

    def remove_dead(self, dead: Iterable[str]) -> "Range":
        """Nuevo rango sin los combos que usan cartas ya vistas (card removal)."""
        dead_set = set(dead)
        return Range({c: w for c, w in self.weights.items()
                      if w > 0 and c[0] not in dead_set and c[1] not in dead_set})

    def __len__(self) -> int:
        return len(self.weights)

    def __iter__(self) -> Iterator[tuple[Combo, float]]:
        return iter(self.weights.items())

    def __contains__(self, combo: object) -> bool:
        return isinstance(combo, tuple) and self._key(combo) in self.weights  # type: ignore[arg-type]

    @property
    def combo_count(self) -> float:
        """Número de combos ponderado por peso."""
        return sum(self.weights.values())

    def classes(self) -> set[str]:
        return {hand_class(a, b) for a, b in self.weights}

    def sampler(self, rnd: random.Random | None = None):
        """Devuelve una función sin argumentos que saca un combo según los pesos."""
        combos = list(self.weights)
        if not combos:
            raise ValueError("Rango vacío")
        cum, acc = [], 0.0
        for c in combos:
            acc += self.weights[c]
            cum.append(acc)
        choices = (rnd or random).choices
        return lambda: choices(combos, cum_weights=cum)[0]
