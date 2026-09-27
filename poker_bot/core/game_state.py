"""Modelo de datos del estado de la mesa.

``GameState`` es el contrato entre la capa de visión (que lo rellena leyendo
la pantalla) y el motor de decisión (que lo consume). No sabe nada de
píxeles ni de OCR: solo describe la mano en curso.

Todas las cantidades se guardan en fichas (float) tal como aparecen en la
mesa; las propiedades ``*_bb`` las expresan en ciegas grandes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Street(str, Enum):
    PREFLOP = "preflop"
    FLOP = "flop"
    TURN = "turn"
    RIVER = "river"

    @classmethod
    def from_board(cls, board: list[str]) -> "Street":
        """Deduce la calle a partir del número de cartas comunitarias."""
        mapping = {0: cls.PREFLOP, 3: cls.FLOP, 4: cls.TURN, 5: cls.RIVER}
        if len(board) not in mapping:
            raise ValueError(f"Número de cartas comunitarias imposible: {len(board)}")
        return mapping[len(board)]


class ActionType(str, Enum):
    FOLD = "fold"
    CHECK = "check"
    CALL = "call"
    BET = "bet"
    RAISE = "raise"
    ALL_IN = "all_in"
    POST_BLIND = "post_blind"


@dataclass
class Action:
    """Una acción observada en la mano (de cualquier jugador)."""
    seat: int
    type: ActionType
    street: Street
    amount: float = 0.0   # cantidad total apostada en la calle tras la acción


# Nombres de posición por tamaño de mesa, empezando por el botón y siguiendo
# el sentido de las agujas del reloj (BTN, SB, BB, UTG, ...).
_POSITIONS_BY_SIZE: dict[int, list[str]] = {
    2: ["BTN", "BB"],   # heads-up: el botón es también la ciega pequeña
    3: ["BTN", "SB", "BB"],
    4: ["BTN", "SB", "BB", "CO"],
    5: ["BTN", "SB", "BB", "UTG", "CO"],
    6: ["BTN", "SB", "BB", "UTG", "HJ", "CO"],
    7: ["BTN", "SB", "BB", "UTG", "MP", "HJ", "CO"],
    8: ["BTN", "SB", "BB", "UTG", "UTG1", "MP", "HJ", "CO"],
    9: ["BTN", "SB", "BB", "UTG", "UTG1", "UTG2", "MP", "HJ", "CO"],
    10: ["BTN", "SB", "BB", "UTG", "UTG1", "UTG2", "MP", "MP1", "HJ", "CO"],
}


@dataclass
class PlayerState:
    seat: int                     # índice del asiento en la calibración (0..N-1)
    name: str = ""
    stack: float = 0.0            # fichas que le quedan detrás (sin contar la apuesta actual)
    bet: float = 0.0              # lo que tiene puesto en la calle actual
    in_hand: bool = True          # False si ha foldeado o el asiento está vacío
    is_hero: bool = False
    position: str = ""            # se rellena con GameState.assign_positions()


@dataclass
class GameState:
    hero_cards: list[str]
    board: list[str]
    pot: float                    # bote de calles anteriores + apuestas actuales
    players: list[PlayerState]
    dealer_seat: int
    big_blind: float
    is_hero_turn: bool = False
    actions: list[Action] = field(default_factory=list)
    confidence: float = 1.0       # 0..1, confianza global de la lectura de pantalla

    # ------------------------------------------------------------------ #
    # Propiedades derivadas
    # ------------------------------------------------------------------ #
    @property
    def street(self) -> Street:
        return Street.from_board(self.board)

    @property
    def hero(self) -> PlayerState:
        for p in self.players:
            if p.is_hero:
                return p
        raise ValueError("No hay ningún jugador marcado como héroe")

    @property
    def opponents_in_hand(self) -> list[PlayerState]:
        return [p for p in self.players if p.in_hand and not p.is_hero]

    @property
    def current_bet(self) -> float:
        """Apuesta máxima en la calle actual."""
        return max((p.bet for p in self.players if p.in_hand), default=0.0)

    @property
    def to_call(self) -> float:
        """Cuánto tiene que poner el héroe para igualar (limitado por su stack)."""
        return min(max(self.current_bet - self.hero.bet, 0.0), self.hero.stack)

    @property
    def effective_stack(self) -> float:
        """Stack efectivo: el menor entre el del héroe y el mayor rival vivo (contando apuestas)."""
        rivals = self.opponents_in_hand
        if not rivals:
            return self.hero.stack + self.hero.bet
        biggest = max(p.stack + p.bet for p in rivals)
        return min(self.hero.stack + self.hero.bet, biggest)

    @property
    def effective_stack_bb(self) -> float:
        return self.effective_stack / self.big_blind

    @property
    def pot_odds(self) -> float:
        """Equity mínima necesaria para pagar: to_call / (bote + to_call)."""
        if self.to_call <= 0:
            return 0.0
        return self.to_call / (self.pot + self.to_call)

    @property
    def spr(self) -> float:
        """Stack-to-pot ratio: stack efectivo restante / bote."""
        if self.pot <= 0:
            return float("inf")
        remaining = self.effective_stack - self.hero.bet
        return max(remaining, 0.0) / self.pot

    # ------------------------------------------------------------------ #
    # Posiciones
    # ------------------------------------------------------------------ #
    def assign_positions(self) -> None:
        """Asigna el nombre de posición a cada jugador sentado según el botón.

        Solo se cuentan asientos ocupados (stack > 0 o con apuesta) al inicio de
        la mano; los que ya han foldeado conservan su posición.
        """
        seated = sorted(
            (p for p in self.players if p.stack > 0 or p.bet > 0 or p.in_hand),
            key=lambda p: p.seat,
        )
        n = len(seated)
        if n < 2:
            return
        names = _POSITIONS_BY_SIZE.get(n) or _POSITIONS_BY_SIZE[10][:n]
        seats = [p.seat for p in seated]
        # Si el asiento del botón estuviera vacío, el botón efectivo es el
        # primer asiento ocupado anterior a él.
        btn_idx = max((i for i, s in enumerate(seats) if s <= self.dealer_seat), default=n - 1)
        for offset in range(n):
            seated[(btn_idx + offset) % n].position = names[offset]
