"""Tablas de rangos preflop (100 ciegas, aproximación a soluciones GTO).

Las aperturas se indexan por **jugadores que quedan por hablar detrás** en
vez de por nombre de posición: así la misma tabla sirve para mesas de 2 a
10 jugadores (el UTG de 6-max y el HJ de 9-max tienen 5 detrás y abren
parecido).

Los pesos ``:0.5`` son frecuencias mixtas: esa mano se juega así la mitad
de las veces. Es lo que mantiene el juego equilibrado (no siempre 3-beteas
A5s, así que el rival no puede leerte).
"""

from __future__ import annotations

# --------------------------------------------------------------------------- #
# Apertura (RFI, raise first in) según jugadores detrás
# --------------------------------------------------------------------------- #
RFI: dict[int, str] = {
    # SB contra BB solo: sube o se tira (~45 %)
    1: "22+,A2s+,K2s+,Q4s+,J6s+,T6s+,96s+,85s+,75s+,64s+,54s,A2o+,K8o+,Q9o+,J9o+,T9o",
    # BTN (~45 %)
    2: "22+,A2s+,K2s+,Q2s+,J5s+,T6s+,96s+,85s+,74s+,64s+,53s+,A2o+,K8o+,Q9o+,J9o+,T8o+,98o",
    # CO (~28 %)
    3: "22+,A2s+,K6s+,Q8s+,J8s+,T8s+,97s+,86s+,76s,65s,54s,A8o+,KTo+,QTo+,JTo",
    # HJ (~20 %)
    4: "33+,A2s+,K8s+,Q9s+,J9s+,T8s+,98s,87s,76s,65s,ATo+,KJo+,QJo",
    # UTG de 6-max / LJ (~16 %)
    5: "44+,A2s+,K9s+,QTs+,J9s+,T9s,98s,87s,76s,AJo+,KQo",
    6: "55+,A3s+,KTs+,QTs+,JTs,T9s,98s,AJo+,KQo",
    7: "66+,A5s+,KTs+,QJs,JTs,T9s,AQo+,KQo:0.5",
    8: "77+,A9s+,KTs+,QJs,JTs,AQo+",
    9: "77+,ATs+,KJs+,QJs,AQo+",
}
# Botón heads-up: se abre casi todo
RFI_HEADS_UP = "top:80"


def rfi_range_text(players_behind: int, heads_up: bool = False) -> str:
    if heads_up:
        return RFI_HEADS_UP
    return RFI[max(1, min(players_behind, 9))]


# --------------------------------------------------------------------------- #
# Frente a una apertura: (categoría del que abre, categoría del héroe) -> (3-bet, call)
#   abridor: "early" (4+ detrás), "late" (CO/BTN), "sb" (SB contra BB)
#   héroe:   "ip" (no ciega), "sb", "bb"
# --------------------------------------------------------------------------- #
VS_OPEN: dict[tuple[str, str], tuple[str, str]] = {
    ("early", "ip"): (
        "QQ+,AK,A5s:0.5,A4s:0.5",
        "JJ-77,AQs-ATs,KQs-KJs,QJs,JTs,T9s,98s:0.5,AQo",
    ),
    ("late", "ip"): (
        "TT+,AQ+,AJs,KQs,A5s-A2s:0.6,K9s:0.4,76s:0.4,65s:0.4",
        "99-55,ATs-A6s,KJs-KTs,QTs+,J9s+,T9s,98s,87s,AJo,KQo",
    ),
    ("early", "sb"): ("QQ+,AK,AQs,A5s:0.5", ""),
    ("late", "sb"): (
        "99+,ATs+,KTs+,QJs,JTs,AQo+,KQo:0.5,A5s-A2s,76s:0.5,65s:0.5",
        "",
    ),
    ("early", "bb"): (
        "QQ+,AK,A5s:0.5",
        "JJ-22,AQs-A2s,KQs-K9s,QJs-Q9s,JTs-J9s,T9s-T8s,98s-97s,87s-86s,76s,65s,54s,"
        "AQo-ATo,KQo-KJo,QJo",
    ),
    ("late", "bb"): (
        "TT+,AQs+,AKo,KQs,A5s-A2s:0.5,K9s:0.4,J9s:0.3,65s:0.3",
        "99-22,AJs-A2s,KJs-K5s,QJs-Q7s,JTs-J7s,T9s-T7s,98s-96s,87s-85s,76s-75s,65s-64s,54s,"
        "AQo-A7o,KQo-K9o,QJo-Q9o,JTo-J9o,T9o,98o",
    ),
    ("sb", "bb"): (
        "99+,ATs+,KJs+,AJo+,A5s-A2s:0.6,76s:0.5,K8s:0.5",
        "88-22,A9s-A2s,KTs-K2s,Q2s+,J5s+,T6s+,96s+,85s+,74s+,64s+,53s+,"
        "A2o+,K5o+,Q8o+,J8o+,T8o+,98o,87o",
    ),
}

# --------------------------------------------------------------------------- #
# Frente a 3-bet (el héroe abrió): (4-bet, call en posición, call fuera de posición)
# --------------------------------------------------------------------------- #
VS_3BET_EARLY_OPEN = (
    "KK+,AKs,QQ:0.5,AKo:0.7,A5s:0.3,A4s:0.3",
    "QQ-99,AQs-ATs,AKo:0.3,AQo:0.5,KQs,KJs,QJs,JTs,T9s,98s:0.5,76s:0.3",
    "QQ-TT,AQs-AJs,KQs,AKo:0.3,JTs:0.5",
)
VS_3BET_LATE_OPEN = (
    "QQ+,AK,A5s-A4s:0.5,KQs:0.2",
    "JJ-66,AQs-A9s,KQs-KTs,QJs-QTs,JTs,T9s,98s,87s,76s,AQo,AJo:0.5,KQo:0.5",
    "JJ-88,AQs-ATs,KQs-KJs,QJs,JTs,T9s:0.5,AQo",
)

# Frente a 4-bet (el héroe hizo 3-bet): (5-bet all-in, call)
VS_4BET = ("KK+,AKs,AKo:0.6,QQ:0.5", "QQ:0.5,JJ:0.3,AKo:0.4")

# Rangos típicos que se asumen para rivales cuando no hay estadísticas
ASSUMED_3BET = "QQ+,AK,JJ:0.6,TT:0.3,AQs,AJs:0.4,KQs:0.5,A5s-A4s:0.5,76s:0.3,65s:0.3"
ASSUMED_4BET = "KK+,AKs,QQ:0.5,AKo:0.7,A5s:0.3"
ASSUMED_LIMP = "top:45"


# --------------------------------------------------------------------------- #
# Push/fold con stacks cortos: % de manos para ir all-in sin nadie delante
# (aproximación a los rangos de Nash a 10 ciegas, escalada por stack).
# --------------------------------------------------------------------------- #
PUSH_PCT_AT_10BB = {1: 58.0, 2: 40.0, 3: 30.0, 4: 24.0, 5: 20.0}


def push_percent(players_behind: int, stack_bb: float) -> float:
    base = PUSH_PCT_AT_10BB.get(players_behind, 16.0)
    return max(5.0, min(100.0, base * (10.0 / max(stack_bb, 1.0)) ** 0.7))
