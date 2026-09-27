"""Herramienta de calibración: marcas con el ratón dónde está cada cosa.

Uso (con la mesa de PokerStars abierta y **siendo tu turno**, para que se vean
los botones):

    python -m poker_bot.capture.calibrate --seats 6 --bb 2
    python -m poker_bot.capture.calibrate --seats 6 --in-bb           # la mesa muestra ciegas
    python -m poker_bot.capture.calibrate --image captura.png --seats 6 --in-bb

En cada paso se abre la captura con una instrucción arriba: arrastra un
rectángulo y pulsa ENTER (o ESPACIO). Con C lo saltas si no aplica.

Orden de los asientos: **el tuyo primero y luego en el sentido de las agujas
del reloj**. Al final se guarda ``data/calibration.json`` y una imagen de
comprobación ``data/calibration_preview.png`` con todas las zonas dibujadas.
"""

from __future__ import annotations

import argparse
import sys
import time
from typing import Callable

import cv2
import numpy as np

from poker_bot.vision.calibration import DATA_DIR, DEFAULT_PATH, Calibration, Rect, SeatRegions
from poker_bot.vision.reader import color_hist

# picker(instrucción, imagen, zonas ya marcadas) -> Rect o None si se salta
Picker = Callable[[str, np.ndarray, list[Rect]], "Rect | None"]


def interpolate_board(first: Rect, last: Rect) -> list[Rect]:
    """Las 5 cartas del board a partir de la primera y la quinta."""
    out = []
    for i in range(5):
        t = i / 4
        out.append(Rect(round(first.x + (last.x - first.x) * t), round(first.y + (last.y - first.y) * t),
                        round(first.w + (last.w - first.w) * t), round(first.h + (last.h - first.h) * t)))
    return out


def run_calibration(table_img: np.ndarray, table: Rect, pick: Picker, seats: int,
                    big_blind: float = 1.0, amounts_in_bb: bool = False,
                    four_color: bool = True) -> Calibration:
    """Pide todas las zonas con ``pick`` y construye la calibración."""
    marked: list[Rect] = []

    def ask(label: str, required: bool = True) -> Rect | None:
        while True:
            r = pick(label, table_img, marked)
            if r is not None and r.w > 2 and r.h > 2:
                marked.append(r)
                return r
            if not required:
                return None
            print(f"  '{label}' es obligatorio, márcalo por favor.")

    hero = [ask("Tu carta 1 (la de la izquierda, entera)"), ask("Tu carta 2 (entera)")]
    b1 = ask("Board: 1ª carta del flop (si no hay, marca dónde aparece; mismo tamaño que tus cartas)")
    b5 = ask("Board: 5ª carta, el river (o dónde aparece)")
    board = interpolate_board(b1, b5)
    marked.extend(board[1:4])
    pot = ask("Bote: SOLO el número")
    buttons = ask("Botones de acción (Fold / Call / Raise) — tiene que ser tu turno")
    felt = ask("Un trozo de tapete vacío (sin cartas, fichas ni texto)")

    seat_regions = []
    for i in range(seats):
        who = "TU asiento" if i == 0 else f"Asiento {i} (siguiente en sentido horario)"
        stack = ask(f"{who}: SOLO el número del stack")
        bet = ask(f"{who}: zona donde aparece su apuesta (fichas y número)")
        cards = hero[0] if i == 0 else ask(f"{who}: zona donde se ven sus cartas boca abajo")
        dealer = ask(f"{who}: sitio donde aparece el botón de dealer (D) cuando le toca")
        seat_regions.append(SeatRegions(stack=stack, bet=bet, cards=cards, dealer=dealer))

    return Calibration(
        table=table, hero_cards=hero, board=board, pot=pot, action_buttons=buttons, felt=felt,
        seats=seat_regions, big_blind=big_blind, amounts_in_bb=amounts_in_bb,
        four_color_deck=four_color,
        buttons_hist=color_hist(buttons.crop(table_img)).tolist(),
    )


def draw_preview(table_img: np.ndarray, calib: Calibration) -> np.ndarray:
    """Imagen de comprobación con todas las zonas etiquetadas."""
    img = table_img.copy()

    def box(r: Rect, color, label: str) -> None:
        cv2.rectangle(img, (r.x, r.y), (r.x + r.w, r.y + r.h), color, 2)
        cv2.putText(img, label, (r.x, max(12, r.y - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1,
                    cv2.LINE_AA)

    for i, r in enumerate(calib.hero_cards):
        box(r, (0, 255, 255), f"yo{i + 1}")
    for i, r in enumerate(calib.board):
        box(r, (255, 255, 0), f"b{i + 1}")
    box(calib.pot, (0, 200, 255), "bote")
    box(calib.action_buttons, (0, 0, 255), "botones")
    box(calib.felt, (200, 200, 200), "tapete")
    for i, s in enumerate(calib.seats):
        box(s.stack, (0, 255, 0), f"s{i} stack")
        box(s.bet, (255, 0, 255), f"s{i} apuesta")
        if i:
            box(s.cards, (255, 128, 0), f"s{i} cartas")
        box(s.dealer, (255, 255, 255), f"s{i} D")
    return img


# --------------------------------------------------------------------------- #
# Interfaz con ventanas de OpenCV
# --------------------------------------------------------------------------- #
def _fit(img: np.ndarray, max_w: int = 1500, max_h: int = 850) -> tuple[np.ndarray, float]:
    scale = min(1.0, max_w / img.shape[1], max_h / img.shape[0])
    if scale < 1.0:
        img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    return img, scale


def gui_picker(label: str, img: np.ndarray, marked: list[Rect]) -> Rect | None:
    shown = img.copy()
    for r in marked:
        cv2.rectangle(shown, (r.x, r.y), (r.x + r.w, r.y + r.h), (0, 255, 0), 1)
    shown, scale = _fit(shown)
    bar = np.zeros((34, shown.shape[1], 3), np.uint8)
    cv2.putText(bar, label + "   [ENTER=ok  C=saltar]", (8, 23), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                (255, 255, 255), 1, cv2.LINE_AA)
    canvas = np.vstack([bar, shown])
    print(f"-> {label}")
    x, y, w, h = cv2.selectROI("Calibracion", canvas, showCrosshair=True, fromCenter=False)
    if w == 0 or h == 0:
        return None
    y = max(0, y - bar.shape[0])
    return Rect(round(x / scale), round(y / scale), round(w / scale), round(h / scale))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Calibración de la mesa")
    ap.add_argument("--seats", type=int, required=True, help="número de asientos de la mesa")
    ap.add_argument("--bb", type=float, default=1.0, help="valor de la ciega grande en fichas")
    ap.add_argument("--in-bb", action="store_true", help="la mesa ya muestra las cantidades en ciegas")
    ap.add_argument("--two-color", action="store_true", help="baraja de 2 colores (no recomendado)")
    ap.add_argument("--image", help="usar una captura guardada en vez de la pantalla")
    ap.add_argument("--delay", type=float, default=5.0, help="segundos antes de capturar")
    ap.add_argument("--out", default=str(DEFAULT_PATH))
    args = ap.parse_args(argv)

    if args.image:
        screen = cv2.imread(args.image)
        if screen is None:
            print(f"No puedo abrir {args.image}", file=sys.stderr)
            return 2
    else:
        from poker_bot.capture.screen import grab_full_screen
        print(f"Pon la mesa a la vista (y que sea TU TURNO). Capturo en {args.delay:.0f} s…")
        time.sleep(args.delay)
        screen = grab_full_screen()

    print("Paso 1: marca TODA la mesa (el marco de la ventana de juego).")
    t = gui_picker("Marca TODA la mesa", screen, [])
    if t is None:
        print("Cancelado.")
        return 1
    table_img = t.crop(screen)
    calib = run_calibration(table_img, t, gui_picker, args.seats, args.bb, args.in_bb,
                            not args.two_color)
    cv2.destroyAllWindows()

    calib.save(args.out)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(DATA_DIR / "calibration_table.png"), table_img)
    preview = draw_preview(table_img, calib)
    cv2.imwrite(str(DATA_DIR / "calibration_preview.png"), preview)
    print(f"Guardado en {args.out}. Revisa data/calibration_preview.png (pulsa una tecla para cerrar).")
    cv2.imshow("Comprobacion", _fit(preview)[0])
    cv2.waitKey(0)
    cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    sys.exit(main())
