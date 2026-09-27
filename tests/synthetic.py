"""Mesa de póker sintética dibujada con OpenCV, con su calibración exacta.

Sirve para probar la lectura de pantalla sin PokerStars: baraja de 4 colores,
números blancos sobre cajas oscuras, dorsos rojos, botón de dealer blanco y
botones de acción rojos cuando es tu turno.
"""
from __future__ import annotations

import cv2
import numpy as np

from poker_bot.vision.calibration import Calibration, Rect, SeatRegions

W, H = 900, 600
FELT = (50, 110, 40)                      # BGR
SUIT_BGR = {"s": (20, 20, 20), "h": (30, 30, 210), "d": (200, 90, 20), "c": (40, 150, 40)}
CARD_W, CARD_H = 56, 78
FONT = cv2.FONT_HERSHEY_SIMPLEX

# Centro de cada asiento, en sentido horario empezando por el héroe (abajo)
SEAT_XY = [(450, 520), (150, 430), (150, 150), (450, 70), (750, 150), (750, 430)]
DEALER_XY = [(560, 470), (200, 500), (250, 110), (540, 110), (650, 110), (700, 500)]
BOARD_X0, BOARD_Y = 285, 250
POT_RECT = Rect(390, 205, 120, 30)
BUTTONS = Rect(600, 540, 290, 50)
FELT_RECT = Rect(20, 280, 60, 40)


def seat_regions(i: int) -> SeatRegions:
    x, y = SEAT_XY[i]
    toward = (np.array([450, 300]) - np.array([x, y]))
    toward = toward / (np.linalg.norm(toward) + 1e-9)
    bx, by = (np.array([x, y]) + toward * 110).astype(int)
    dx, dy = DEALER_XY[i]
    return SeatRegions(
        stack=Rect(x - 50, y + 20, 100, 28),
        bet=Rect(int(bx) - 45, int(by) - 14, 90, 28),
        cards=Rect(x - 30, y - 35, 60, 45),
        dealer=Rect(int(dx) - 15, int(dy) - 15, 30, 30),
    )


def hero_card_rects() -> list[Rect]:
    x, y = SEAT_XY[0]
    return [Rect(x - 60, y - 95, CARD_W, CARD_H), Rect(x + 4, y - 95, CARD_W, CARD_H)]


def board_rects() -> list[Rect]:
    return [Rect(BOARD_X0 + i * (CARD_W + 10), BOARD_Y, CARD_W, CARD_H) for i in range(5)]


def calibration(buttons_hist=None) -> Calibration:
    return Calibration(
        table=Rect(0, 0, W, H), hero_cards=hero_card_rects(), board=board_rects(), pot=POT_RECT,
        action_buttons=BUTTONS, felt=FELT_RECT, seats=[seat_regions(i) for i in range(6)],
        big_blind=1.0, amounts_in_bb=True, rank_box=(0.0, 0.0, 0.5, 0.6),
        buttons_hist=list(buttons_hist) if buttons_hist is not None else [],
    )


def draw_card(img, rect: Rect, card: str) -> None:
    x, y, w, h = rect.x, rect.y, rect.w, rect.h
    cv2.rectangle(img, (x, y), (x + w - 1, y + h - 1), (250, 250, 250), -1)
    color = SUIT_BGR[card[1]]
    text = "10" if card[0] == "T" else card[0]
    scale = 0.62 if text == "10" else 0.75
    cv2.putText(img, text, (x + 3, y + 22), FONT, scale, color, 2, cv2.LINE_AA)
    cv2.circle(img, (x + 12, y + 36), 6, color, -1, cv2.LINE_AA)
    cv2.circle(img, (x + w // 2 + 8, y + h // 2 + 12), 13, color, -1, cv2.LINE_AA)


def draw_number(img, rect: Rect, value, box=True) -> None:
    if value is None:
        return
    if box:
        cv2.rectangle(img, (rect.x, rect.y), (rect.x + rect.w, rect.y + rect.h), (35, 35, 35), -1)
    text = f"{value:g}"
    (tw, th), _ = cv2.getTextSize(text, FONT, 0.7, 2)
    cv2.putText(img, text, (rect.x + (rect.w - tw) // 2, rect.y + (rect.h + th) // 2), FONT, 0.7,
                (240, 240, 240), 2, cv2.LINE_AA)


def render(hero=("As", "Kd"), board=(), pot=1.5, seats=None, dealer=3, my_turn=False):
    """``seats``: lista de (stack, bet, has_cards) por asiento; None = asiento vacío."""
    seats = seats or [(100, 0, True)] * 6
    img = np.full((H, W, 3), FELT, np.uint8)
    for i, s in enumerate(seats):
        r = seat_regions(i)
        if s is None:
            continue
        stack, bet, has_cards = s
        draw_number(img, r.stack, stack)
        if bet:
            draw_number(img, r.bet, bet, box=False)
        if has_cards and i != 0:
            c = r.cards
            cv2.rectangle(img, (c.x + 5, c.y + 3), (c.x + c.w - 5, c.y + c.h - 3), (30, 30, 170), -1)
    if dealer is not None:
        d = seat_regions(dealer).dealer
        cv2.circle(img, (d.x + d.w // 2, d.y + d.h // 2), 12, (245, 245, 245), -1)
        cv2.putText(img, "D", (d.x + 8, d.y + 21), FONT, 0.55, (20, 20, 20), 2)
    for rect, card in zip(hero_card_rects(), hero or ()):
        if card:
            draw_card(img, rect, card)
    for rect, card in zip(board_rects(), board):
        draw_card(img, rect, card)
    draw_number(img, POT_RECT, pot)
    if my_turn:
        for k, label in enumerate(["FOLD", "CALL", "RAISE"]):
            x = BUTTONS.x + 5 + k * 95
            cv2.rectangle(img, (x, BUTTONS.y + 5), (x + 88, BUTTONS.y + 45), (40, 40, 190), -1)
            cv2.putText(img, label, (x + 10, BUTTONS.y + 32), FONT, 0.55, (255, 255, 255), 2)
    return img
