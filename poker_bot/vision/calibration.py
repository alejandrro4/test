"""Calibración: dónde está cada cosa en tu mesa.

Todas las zonas se guardan en píxeles **relativos a la zona de la mesa**
(``table``), que a su vez está en coordenadas de pantalla. Así, si mueves la
ventana basta con volver a marcar la zona de la mesa.

Los asientos van en el **sentido de las agujas del reloj empezando por el
tuyo** (asiento 0 = tú). Ese orden es el que usa el motor para las posiciones.

Se guarda en ``data/calibration.json``; lo genera ``python -m poker_bot.capture.calibrate``.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
DEFAULT_PATH = DATA_DIR / "calibration.json"


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int

    def crop(self, img):
        """Recorte de una imagen numpy (alto, ancho, canales)."""
        return img[self.y:self.y + self.h, self.x:self.x + self.w]

    @classmethod
    def from_list(cls, v) -> "Rect":
        return cls(*[int(round(x)) for x in v])

    def to_list(self) -> list[int]:
        return [self.x, self.y, self.w, self.h]


@dataclass
class SeatRegions:
    stack: Rect          # número del stack
    bet: Rect            # zona donde aparece su apuesta en la calle
    cards: Rect          # zona donde se ven sus cartas (dorsos) si sigue en la mano
    dealer: Rect         # sitio donde aparece el botón de dealer si le toca


@dataclass
class Calibration:
    table: Rect                        # en coordenadas de pantalla
    hero_cards: list[Rect]             # 2 zonas
    board: list[Rect]                  # 5 zonas
    pot: Rect
    action_buttons: Rect               # botones Fold/Call/Raise
    felt: Rect                         # un trozo de tapete vacío (color de referencia)
    seats: list[SeatRegions]           # seats[0] = tú
    big_blind: float = 1.0             # valor de la ciega grande en las unidades de la mesa
    amounts_in_bb: bool = False        # la mesa muestra las cantidades ya en ciegas grandes
    pot_includes_bets: bool = False    # el bote mostrado ya suma las apuestas de la calle
    four_color_deck: bool = True       # baraja de 4 colores (♠ negro, ♥ rojo, ♦ azul, ♣ verde)
    # Parte de la carta donde está el número (fracciones x, y, ancho, alto)
    rank_box: tuple[float, float, float, float] = (0.0, 0.0, 0.5, 0.5)
    buttons_hist: list[float] = field(default_factory=list)  # huella de color de los botones visibles
    turn_threshold: float = 0.6

    def __post_init__(self) -> None:
        # Puede llegar como array de numpy (float32): el JSON solo admite floats normales
        self.buttons_hist = [float(x) for x in self.buttons_hist]
        self.rank_box = tuple(float(x) for x in self.rank_box)

    # ------------------------------------------------------------------ #
    def to_dict(self) -> dict:
        d = asdict(self)
        # Los Rect se guardan como listas [x, y, w, h] para que el JSON sea legible
        def conv(v):
            if isinstance(v, dict) and set(v) == {"x", "y", "w", "h"}:
                return [v["x"], v["y"], v["w"], v["h"]]
            if isinstance(v, dict):
                return {k: conv(x) for k, x in v.items()}
            if isinstance(v, list):
                return [conv(x) for x in v]
            return v
        return conv(d)

    @classmethod
    def from_dict(cls, d: dict) -> "Calibration":
        r = Rect.from_list
        return cls(
            table=r(d["table"]),
            hero_cards=[r(x) for x in d["hero_cards"]],
            board=[r(x) for x in d["board"]],
            pot=r(d["pot"]),
            action_buttons=r(d["action_buttons"]),
            felt=r(d["felt"]),
            seats=[SeatRegions(**{k: r(v) for k, v in s.items()}) for s in d["seats"]],
            big_blind=float(d.get("big_blind", 1.0)),
            amounts_in_bb=bool(d.get("amounts_in_bb", False)),
            pot_includes_bets=bool(d.get("pot_includes_bets", False)),
            four_color_deck=bool(d.get("four_color_deck", True)),
            rank_box=tuple(d.get("rank_box", (0.0, 0.0, 0.5, 0.5))),
            buttons_hist=list(d.get("buttons_hist", [])),
            turn_threshold=float(d.get("turn_threshold", 0.6)),
        )

    def save(self, path: str | Path = DEFAULT_PATH) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path = DEFAULT_PATH) -> "Calibration":
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(
                f"No hay calibración en {path}. Ejecuta: python -m poker_bot.capture.calibrate")
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))
