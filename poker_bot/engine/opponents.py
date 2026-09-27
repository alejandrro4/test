"""Modelado de rivales: estadísticas, clasificación y ajustes explotativos.

Las estadísticas se suavizan con una media "a priori" (lo típico en partidas
caseras) para que con pocas manos no salgan valores extremos: tras 3 manos
un amigo con VPIP 100 % no es necesariamente un maníaco.

Cómo se usan en el motor:
  * ``fold_factor``: multiplica la frecuencia con la que el rival se retira
    frente a una apuesta. <1 = paga de más (calling station) -> menos faroles
    y más value fino; >1 = se tira de más -> más faroles y robos.
  * ``aggression_factor``: cuánto más ancho apuesta/sube de lo normal; si es
    alto, su rango de apuesta tiene más aire y pagamos más ligero.
  * ``open_percent`` / ``vpip_percent``: anchura de sus rangos preflop.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

# Valores a priori (población de partidas caseras entre amigos)
PRIOR_VPIP = 0.32
PRIOR_PFR = 0.14
PRIOR_3BET = 0.06
PRIOR_AF = 1.5
PRIOR_FOLD_TO_CBET = 0.45
PRIOR_WTSD = 0.32
PRIOR_WEIGHT = 12  # "manos ficticias" de la media a priori

MIN_HANDS_FOR_RANGES = 20  # a partir de aquí sus rangos salen de sus estadísticas


def _smooth(hits: int, opportunities: int, prior: float, weight: int = PRIOR_WEIGHT) -> float:
    return (hits + prior * weight) / (opportunities + weight)


@dataclass
class OpponentStats:
    name: str
    hands: int = 0
    vpip: int = 0                 # manos en las que metió dinero voluntariamente preflop
    pfr: int = 0                  # manos en las que subió preflop
    three_bet: int = 0
    three_bet_opp: int = 0
    postflop_aggr: int = 0        # apuestas + subidas postflop
    postflop_calls: int = 0
    cbet_faced: int = 0
    fold_to_cbet: int = 0
    saw_flop: int = 0
    went_to_showdown: int = 0
    won_showdown: int = 0

    # ------------------------------------------------------------------ #
    # Estadísticas suavizadas (0..1)
    # ------------------------------------------------------------------ #
    @property
    def vpip_rate(self) -> float:
        return _smooth(self.vpip, self.hands, PRIOR_VPIP)

    @property
    def pfr_rate(self) -> float:
        return min(_smooth(self.pfr, self.hands, PRIOR_PFR), self.vpip_rate)

    @property
    def three_bet_rate(self) -> float:
        return _smooth(self.three_bet, self.three_bet_opp, PRIOR_3BET)

    @property
    def af(self) -> float:
        """Factor de agresión postflop: (apuestas + subidas) / calls."""
        w = PRIOR_WEIGHT / 2
        return (self.postflop_aggr + PRIOR_AF * w) / (self.postflop_calls + w)

    @property
    def fold_to_cbet_rate(self) -> float:
        return _smooth(self.fold_to_cbet, self.cbet_faced, PRIOR_FOLD_TO_CBET)

    @property
    def wtsd_rate(self) -> float:
        return _smooth(self.went_to_showdown, self.saw_flop, PRIOR_WTSD)

    # ------------------------------------------------------------------ #
    # Clasificación y ajustes
    # ------------------------------------------------------------------ #
    @property
    def style(self) -> str:
        """Etiqueta legible: roca, TAG, LAG, calling station, maníaco, pasivo..."""
        loose = self.vpip_rate > 0.30
        tight = self.vpip_rate < 0.20
        aggressive = self.af > 2.2 or self.pfr_rate > 0.6 * self.vpip_rate
        passive = self.af < 1.2 and self.pfr_rate < 0.4 * self.vpip_rate
        if loose and passive:
            return "calling station"
        if loose and aggressive:
            return "maníaco" if self.vpip_rate > 0.45 else "LAG"
        if tight and passive:
            return "roca"
        if tight or (not loose and aggressive):
            return "TAG"
        return "regular"

    @property
    def fold_factor(self) -> float:
        """Multiplicador sobre la frecuencia de fold "de equilibrio"."""
        f = self.fold_to_cbet_rate / PRIOR_FOLD_TO_CBET
        # Quien va mucho a showdown paga de más
        f *= (PRIOR_WTSD / self.wtsd_rate) ** 0.5
        return max(0.4, min(1.6, f))

    @property
    def aggression_factor(self) -> float:
        return max(0.6, min(1.8, (self.af / PRIOR_AF) ** 0.5))

    @property
    def open_percent(self) -> float:
        return 100 * self.pfr_rate

    @property
    def vpip_percent(self) -> float:
        return 100 * self.vpip_rate

    @property
    def reliable(self) -> bool:
        return self.hands >= MIN_HANDS_FOR_RANGES

    def summary(self) -> str:
        return (f"{self.name}: {self.style} · VPIP {self.vpip_rate:.0%} · PFR {self.pfr_rate:.0%} · "
                f"AF {self.af:.1f} · fold a c-bet {self.fold_to_cbet_rate:.0%} ({self.hands} manos)")

    def to_dict(self) -> dict:
        return asdict(self)


def unknown(name: str = "?") -> OpponentStats:
    """Perfil por defecto (sin datos): usa solo los valores a priori."""
    return OpponentStats(name=name)
