"""Seguimiento de la mano frame a frame.

Recibe lecturas en bruto (``TableRead``) y:
  * espera a que la lectura sea **estable** (igual en 2 frames seguidos) para
    no reaccionar a animaciones a medias (fichas moviéndose, cartas girando);
  * detecta **mano nueva** (cambian tus cartas) y **calle nueva** (más cartas en el board);
  * deduce las **acciones** de cada jugador comparando con la lectura anterior:
    sube su apuesta por encima de la máxima → sube/apuesta (all-in si se queda
    sin stack); la iguala → paga; pierde las cartas → se retira;
  * cuando es **tu turno** y todo lo necesario se ha leído bien, construye el
    ``GameState`` para el motor de decisión. Si falta algo, NO lo inventa:
    devuelve qué no ha podido leer.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from poker_bot.core.game_state import Action, ActionType, GameState, PlayerState, Street
from poker_bot.vision.reader import TableRead

STABLE_FRAMES = 2
EPS = 1e-6


@dataclass
class TrackerUpdate:
    status: str                          # texto corto para la página
    state: GameState | None = None       # listo para decidir (solo en tu turno)
    new_decision: bool = False           # el estado ha cambiado desde la última decisión
    problems: list[str] = field(default_factory=list)


class HandTracker:
    def __init__(self, pot_includes_bets: bool = False, stable_frames: int = STABLE_FRAMES):
        self.pot_includes_bets = pot_includes_bets
        self.stable_frames = stable_frames
        self.hand_id = 0
        self.hero_cards: tuple[str, str] | None = None
        self.dealer: int | None = None
        self.street: Street = Street.PREFLOP
        self.actions: list[Action] = []
        self.prev: TableRead | None = None
        self.last_actor: int | None = None
        self._pending_key = None
        self._pending_count = 0
        self._processed_key = None
        self._decided_key = None
        self._last_update = TrackerUpdate("Esperando la mesa…")

    # ------------------------------------------------------------------ #
    def update(self, raw: TableRead) -> TrackerUpdate:
        key = raw.key()
        if key != self._pending_key:
            self._pending_key, self._pending_count = key, 1
        else:
            self._pending_count += 1
        if self._pending_count < self.stable_frames or key == self._processed_key:
            # Aún no es estable, o ya se procesó: se repite el último estado
            # pero sin pedir otra decisión
            self._last_update = replace(self._last_update, new_decision=False)
            return self._last_update
        self._processed_key = key
        self._last_update = self._process(raw)
        return self._last_update

    # ------------------------------------------------------------------ #
    def _process(self, raw: TableRead) -> TrackerUpdate:
        hero = raw.hero_cards
        if not all(hero):
            if not raw.seats[0].has_cards:
                return TrackerUpdate("Esperando a que te repartan", problems=raw.problems)
            return TrackerUpdate("No reconozco tus cartas", problems=raw.problems)

        hero_t = (hero[0], hero[1])
        board = raw.board_cards
        if len(board) not in (0, 3, 4, 5):
            return TrackerUpdate("Leyendo el board…", problems=raw.problems)

        if hero_t != self.hero_cards:
            self._new_hand(raw, hero_t)
        else:
            new_street = Street.from_board(board)
            if _street_index(new_street) > _street_index(self.street):
                self.street = new_street
                self.last_actor = None
                # Las apuestas de la calle anterior ya están en el bote
                self.prev = _with_zero_bets(self.prev) if self.prev else None
            self._infer_actions(raw)
        self.prev = raw

        if not raw.my_turn:
            return TrackerUpdate(f"Mano en curso ({self.street.value}); esperando tu turno",
                                 problems=raw.problems)
        return self._build_state(raw)

    def _new_hand(self, raw: TableRead, hero: tuple[str, str]) -> None:
        self.hand_id += 1
        self.hero_cards = hero
        self.dealer = raw.dealer_seat
        self.street = Street.from_board(raw.board_cards)
        self.actions = []
        self.last_actor = None
        # Lo que ya hay apostado al empezar a seguir la mano
        if self.street is Street.PREFLOP:
            blinds = sorted((s for s in range(len(raw.seats)) if 0 < raw.seats[s].bet <= 1.0 + EPS),
                            key=lambda s: raw.seats[s].bet)
            for s in blinds:
                self.actions.append(Action(s, ActionType.POST_BLIND, Street.PREFLOP, raw.seats[s].bet))
            base = _with_bets(raw, {s: raw.seats[s].bet for s in blinds})
        else:
            base = _with_zero_bets(raw)
        self.prev = base
        self._infer_actions(raw)

    def _order(self, raw: TableRead) -> list[int]:
        """Orden de acción de los asientos en la calle actual, empezando tras el último que habló."""
        gs = _skeleton_state(raw, self.dealer if self.dealer is not None else raw.dealer_seat)
        if gs is None:
            return list(range(len(raw.seats)))
        order = gs.preflop_order() if self.street is Street.PREFLOP else gs.postflop_order()
        if self.last_actor in order:
            i = order.index(self.last_actor) + 1
            order = order[i:] + order[:i]
        return order

    def _infer_actions(self, raw: TableRead) -> None:
        prev = self.prev
        if prev is None or len(prev.seats) != len(raw.seats):
            return
        current_max = max((s.bet for s in prev.seats), default=0.0)
        for seat in self._order(raw):
            before, now = prev.seats[seat], raw.seats[seat]
            if seat != 0 and before.has_cards and not now.has_cards:
                self._add(seat, ActionType.FOLD, 0.0)
                continue
            if now.bet > before.bet + EPS:
                all_in = now.stack is not None and now.stack <= EPS
                if now.bet > current_max + EPS:
                    if all_in:
                        kind = ActionType.ALL_IN
                    elif current_max <= EPS and self.street is not Street.PREFLOP:
                        kind = ActionType.BET
                    else:
                        kind = ActionType.RAISE
                    current_max = now.bet
                else:
                    kind = ActionType.ALL_IN if all_in else ActionType.CALL
                self._add(seat, kind, now.bet)

    def _add(self, seat: int, kind: ActionType, amount: float) -> None:
        self.actions.append(Action(seat, kind, self.street, amount))
        self.last_actor = seat

    def _build_state(self, raw: TableRead) -> TrackerUpdate:
        problems = list(raw.problems)
        pot_read = raw.pot
        if pot_read is None and self.street is Street.PREFLOP:
            # Preflop muchas salas no muestran bote (o muestran 0): solo hay ciegas y apuestas
            pot_read = 0.0 if not self.pot_includes_bets else sum(s.bet for s in raw.seats)
        if pot_read is None:
            problems.append("no leo el bote")
        if raw.seats[0].stack is None:
            problems.append("no leo tu stack")
        dealer = self.dealer if self.dealer is not None else raw.dealer_seat
        if dealer is None:
            problems.append("no sé dónde está el botón")
        if any(s.has_cards and s.stack is None and s.bet <= EPS for s in raw.seats[1:]):
            problems.append("no leo el stack de algún rival")
        if problems:
            return TrackerUpdate("Es tu turno, pero no me fío de la lectura", problems=problems)

        gs = _skeleton_state(raw, dealer)
        pot = pot_read + (0.0 if self.pot_includes_bets else sum(s.bet for s in raw.seats))
        gs.pot = pot
        gs.hero_cards = list(self.hero_cards)
        gs.board = raw.board_cards
        gs.actions = list(self.actions)
        gs.is_hero_turn = True
        gs.assign_positions()
        key = (self.hand_id, gs.street, tuple((p.bet, p.in_hand) for p in gs.players), round(pot, 2))
        new = key != self._decided_key
        self._decided_key = key
        return TrackerUpdate("¡Tu turno!", state=gs, new_decision=new, problems=problems)


# --------------------------------------------------------------------------- #
def _street_index(s: Street) -> int:
    return [Street.PREFLOP, Street.FLOP, Street.TURN, Street.RIVER].index(s)


def _with_bets(raw: TableRead, bets: dict[int, float]) -> TableRead:
    seats = [replace(s, bet=bets.get(i, 0.0)) for i, s in enumerate(raw.seats)]
    return replace(raw, seats=seats)


def _with_zero_bets(raw: TableRead) -> TableRead:
    return _with_bets(raw, {})


def _skeleton_state(raw: TableRead, dealer: int | None) -> GameState | None:
    """GameState con jugadores y botón (sin cartas ni acciones), para órdenes y posiciones."""
    if dealer is None:
        return None
    players = []
    for i, s in enumerate(raw.seats):
        seated = s.has_cards or (s.stack or 0) > 0 or s.bet > 0
        players.append(PlayerState(
            seat=i, name="Tú" if i == 0 else f"Asiento {i}",
            stack=(s.stack or 0.0) if seated else 0.0, bet=s.bet,
            in_hand=s.has_cards, is_hero=(i == 0)))
    return GameState(hero_cards=[], board=[], pot=0.0, players=players,
                     dealer_seat=dealer, big_blind=1.0)
