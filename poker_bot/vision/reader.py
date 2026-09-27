"""Lectura de la mesa completa a partir de una captura.

Devuelve un ``TableRead`` "en bruto" (lo que se ve en ese frame). El
``HandTracker`` combina varios frames para saber qué ha hecho cada jugador.

Detecciones sin plantillas, comparando con el color del tapete (``felt``):
  * un jugador sigue en la mano si en su zona de cartas hay "algo" que no es tapete;
  * el botón de dealer está en el asiento cuya zona de dealer tiene más píxeles
    claros (el botón es blanco/amarillo; fichas y tapete son más oscuros);
  * es tu turno si la zona de botones se parece (histograma de color) a como
    estaba cuando calibraste en tu turno.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import cv2
import numpy as np

from poker_bot.vision.calibration import Calibration
from poker_bot.vision.cards import CardReader
from poker_bot.vision.numbers import NumberReader

FELT_DISTANCE = 60          # diferencia de color (suma de canales) para "no es tapete"
PRESENT_FRACTION = 0.25     # fracción de píxeles distintos al tapete para "hay algo"
BRIGHT_MIN = 200            # brillo (V de HSV) mínimo de los píxeles del botón de dealer
DEALER_FRACTION = 0.15      # fracción mínima de píxeles claros para ver el botón


@dataclass
class SeatRead:
    stack: float | None
    bet: float
    has_cards: bool


@dataclass
class TableRead:
    hero_cards: list[str | None]
    board: list[str | None]
    pot: float | None
    seats: list[SeatRead]
    dealer_seat: int | None
    my_turn: bool
    unknown_cards: int = 0                      # cartas vistas cuyo número aún no conoce
    problems: list[str] = field(default_factory=list)

    @property
    def board_cards(self) -> list[str]:
        """Cartas del board reconocidas y seguidas (se corta en el primer hueco)."""
        out = []
        for c in self.board:
            if c is None:
                break
            out.append(c)
        return out

    def key(self) -> tuple:
        """Huella para saber si dos lecturas son iguales (estabilidad entre frames)."""
        return (tuple(self.hero_cards), tuple(self.board), self.pot,
                tuple((s.stack, s.bet, s.has_cards) for s in self.seats),
                self.dealer_seat, self.my_turn)


def non_felt_fraction(img: np.ndarray, felt_bgr: np.ndarray) -> float:
    if img.size == 0:
        return 0.0
    diff = np.abs(img.astype(np.int16) - felt_bgr.astype(np.int16)).sum(axis=2)
    return float(np.mean(diff > FELT_DISTANCE))


def bright_fraction(img: np.ndarray) -> float:
    if img.size == 0:
        return 0.0
    return float(np.mean(img.max(axis=2) >= BRIGHT_MIN))


def color_hist(img: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    h = cv2.calcHist([hsv], [0, 1], None, [18, 8], [0, 180, 0, 256])
    return cv2.normalize(h, h).flatten()


class TableReader:
    def __init__(self, calib: Calibration, cards: CardReader, numbers: NumberReader):
        self.c = calib
        self.cards = cards
        self.numbers = numbers
        self._buttons_hist = (np.array(calib.buttons_hist, np.float32)
                              if calib.buttons_hist else None)
        # El OCR lanza un proceso de Tesseract por número: en paralelo va mucho más rápido
        self._pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="ocr")

    def felt_color(self, frame: np.ndarray) -> np.ndarray:
        return np.median(self.c.felt.crop(frame).reshape(-1, 3), axis=0)

    def is_my_turn(self, frame: np.ndarray) -> bool:
        if self._buttons_hist is None:
            return False
        h = color_hist(self.c.action_buttons.crop(frame))
        score = cv2.compareHist(self._buttons_hist, h, cv2.HISTCMP_CORREL)
        return score >= self.c.turn_threshold

    def _to_bb(self, v: float | None) -> float | None:
        if v is None:
            return None
        return v if self.c.amounts_in_bb else v / self.c.big_blind

    def read(self, frame: np.ndarray) -> TableRead:
        """``frame``: imagen BGR de la zona de la mesa (ya recortada)."""
        c = self.c
        felt = self.felt_color(frame)
        problems: list[str] = []

        hero_reads = [self.cards.read(r.crop(frame)) for r in c.hero_cards]
        board_reads = [self.cards.read(r.crop(frame)) for r in c.board]
        unknown = sum(r.unknown for r in hero_reads + board_reads)
        hero = [r.card for r in hero_reads]
        board = [r.card for r in board_reads]

        # Todos los números a la vez: [bote, stack0, apuesta0, stack1, apuesta1, ...]
        rects = [c.pot] + [r for s in c.seats for r in (s.stack, s.bet)]
        amounts = list(self._pool.map(lambda r: self.numbers.read_ex(r.crop(frame)), rects))
        values = [self._to_bb(a.value) for a in amounts]
        pot = values[0]
        if amounts[0].status == "unreadable":
            problems.append("no leo bien el bote")

        seats = []
        dealer_scores = []
        for i, s in enumerate(c.seats):
            stack = values[1 + 2 * i]
            bet = values[2 + 2 * i] or 0.0
            if i == 0:
                has_cards = any(r.present for r in hero_reads)
            else:
                has_cards = non_felt_fraction(s.cards.crop(frame), felt) >= PRESENT_FRACTION
            who = "tu" if i == 0 else f"del asiento {i}"
            if amounts[1 + 2 * i].status == "unreadable" and has_cards:
                problems.append(f"no leo bien el stack {who}")
            if amounts[2 + 2 * i].status == "unreadable":
                # Una apuesta ilegible nunca se toma como 0
                problems.append(f"no leo bien la apuesta {who}")
            seats.append(SeatRead(stack, bet, has_cards))
            dealer_scores.append(bright_fraction(s.dealer.crop(frame)))

        best = int(np.argmax(dealer_scores)) if dealer_scores else None
        dealer = best if best is not None and dealer_scores[best] >= DEALER_FRACTION else None
        if dealer is None:
            problems.append("no veo el botón de dealer")

        if unknown:
            problems.append(f"{unknown} carta(s) por aprender")
        return TableRead(hero, board, pot, seats, dealer, self.is_my_turn(frame), unknown, problems)
