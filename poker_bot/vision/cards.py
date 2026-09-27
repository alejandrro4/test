"""Reconocimiento de cartas por plantillas que se aprenden solas.

Cómo funciona:
  1. ¿Hay carta? Una carta boca arriba es sobre todo blanca.
  2. Se recorta la esquina con el número (``rank_box``) y se separan los
     trazos de "tinta" (lo que no es blanco). Los trazos de arriba son el
     número (en el "10" son dos), el de debajo es el palo.
  3. **Palo por color** (baraja de 4 colores: ♠ negro, ♥ rojo, ♦ azul, ♣ verde).
     Con baraja de 2 colores se usa además una plantilla del símbolo.
  4. **Número por plantilla**: se normaliza el trazo a un tamaño fijo y se
     compara (correlación) con las plantillas guardadas en ``data/templates``.
  5. Si no se parece a ninguna, se guarda en ``data/templates/unknown`` y la
     página web te pregunta qué es. Con 13 respuestas (una por número) ya
     reconoce todas las cartas; es la "calibración de cartas", que se hace sola
     jugando.
"""

from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from poker_bot.core.cards import RANKS, SUITS
from poker_bot.vision.calibration import DATA_DIR

TEMPLATES_DIR = DATA_DIR / "templates"
GLYPH_SIZE = (20, 28)            # ancho, alto de un trazo normalizado
MATCH_THRESHOLD = 0.75           # correlación mínima para dar por buena una plantilla
WHITE_MIN = 170                  # un píxel es "blanco" si sus 3 canales superan esto
CARD_WHITE_FRACTION = 0.35       # fracción blanca mínima para considerar que hay carta


@dataclass
class CardRead:
    card: str | None             # "As", o None si no hay carta o no se reconoce
    present: bool                # hay una carta boca arriba
    unknown: bool = False        # hay carta pero el número (o palo) no se conoce aún


# --------------------------------------------------------------------------- #
# Utilidades de imagen
# --------------------------------------------------------------------------- #
def white_fraction(img: np.ndarray) -> float:
    if img.size == 0:
        return 0.0
    return float(np.mean(np.all(img >= WHITE_MIN, axis=2)))


def ink_mask(img: np.ndarray) -> np.ndarray:
    """Máscara (uint8 0/255) de lo que no es fondo blanco."""
    return np.where(np.all(img >= WHITE_MIN, axis=2), 0, 255).astype(np.uint8)


def normalize_glyph(mask: np.ndarray) -> np.ndarray:
    """Recorta el trazo a su caja y lo escala a ``GLYPH_SIZE`` (0/255)."""
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return np.zeros(GLYPH_SIZE[::-1], np.uint8)
    crop = mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    g = cv2.resize(crop, GLYPH_SIZE, interpolation=cv2.INTER_AREA)
    return np.where(g > 127, 255, 0).astype(np.uint8)


def glyph_hash(glyph: np.ndarray) -> str:
    return hashlib.sha1(glyph.tobytes()).hexdigest()[:12]


def split_rank_and_suit(corner_mask: np.ndarray) -> tuple[np.ndarray | None, np.ndarray | None]:
    """Separa la esquina en (máscara del número, máscara del palo).

    Los trazos del número son los componentes cuya parte superior queda cerca
    de la del primer trazo; el palo es el siguiente componente por debajo.
    """
    n, labels, stats, _ = cv2.connectedComponentsWithStats(corner_mask, connectivity=8)
    min_area = max(4, corner_mask.size * 0.004)
    comps = [i for i in range(1, n) if stats[i, cv2.CC_STAT_AREA] >= min_area]
    if not comps:
        return None, None
    comps.sort(key=lambda i: stats[i, cv2.CC_STAT_TOP])
    first = comps[0]
    top0 = stats[first, cv2.CC_STAT_TOP]
    h0 = stats[first, cv2.CC_STAT_HEIGHT]
    rank_ids = [i for i in comps if stats[i, cv2.CC_STAT_TOP] <= top0 + 0.4 * h0]
    rest = [i for i in comps if i not in rank_ids]
    rank = np.isin(labels, rank_ids).astype(np.uint8) * 255
    suit = None
    if rest:
        # El palo: el componente más grande de los de abajo
        big = max(rest, key=lambda i: stats[i, cv2.CC_STAT_AREA])
        suit = (labels == big).astype(np.uint8) * 255
    return rank, suit


def suit_color(img: np.ndarray, mask: np.ndarray) -> str:
    """Color dominante de la tinta: 'black', 'red', 'blue' o 'green'."""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    sel = mask > 0
    if not sel.any():
        return "black"
    h, s, v = hsv[..., 0][sel], hsv[..., 1][sel], hsv[..., 2][sel]
    colored = (s > 80) & (v > 60)
    if colored.mean() < 0.25:
        return "black"
    hc = h[colored]
    counts = {
        "red": int(np.sum((hc < 10) | (hc > 165))),
        "green": int(np.sum((hc >= 35) & (hc <= 90))),
        "blue": int(np.sum((hc >= 95) & (hc <= 135))),
    }
    return max(counts, key=counts.get)


_COLOR_TO_SUIT_4 = {"black": "s", "red": "h", "blue": "d", "green": "c"}
_COLOR_TO_SUITS_2 = {"black": ("s", "c"), "red": ("h", "d"), "blue": ("d",), "green": ("c",)}


# --------------------------------------------------------------------------- #
# Biblioteca de plantillas
# --------------------------------------------------------------------------- #
class GlyphLibrary:
    """Plantillas guardadas como PNG: números de carta ('rank'), palos ('suit')
    y dígitos de las cantidades ('digit').

    ``data/templates/rank/A_<hash>.png``, ``data/templates/digit/7_<hash>.png``...
    y las pendientes de etiquetar en ``data/templates/unknown/<tipo>_<hash>.png``.
    """

    VALID = {"rank": set(RANKS), "suit": set(SUITS), "digit": set("0123456789")}

    def __init__(self, root: str | Path = TEMPLATES_DIR):
        self.root = Path(root)
        self._lock = threading.Lock()
        self.templates: dict[str, list[tuple[str, np.ndarray]]] = {k: [] for k in self.VALID}
        self.reload()

    def reload(self) -> None:
        with self._lock:
            for kind in self.templates:
                items = []
                folder = self.root / kind
                if folder.exists():
                    for f in sorted(folder.glob("*.png")):
                        img = cv2.imread(str(f), cv2.IMREAD_GRAYSCALE)
                        if img is not None:
                            items.append((f.name.split("_")[0], img.astype(np.float32)))
                self.templates[kind] = items

    def known_labels(self, kind: str) -> set[str]:
        return {label for label, _ in self.templates[kind]}

    def count(self, kind: str, label: str) -> int:
        return sum(1 for lbl, _ in self.templates[kind] if lbl == label)

    def ranked(self, glyph: np.ndarray, kind: str,
               allowed: set[str] | None = None) -> list[tuple[str, float]]:
        """(etiqueta, mejor correlación) de cada etiqueta, de más a menos parecida."""
        g = glyph.astype(np.float32)
        with self._lock:
            items = list(self.templates[kind])
        best: dict[str, float] = {}
        for label, tpl in items:
            if allowed and label not in allowed:
                continue
            score = float(cv2.matchTemplate(g, tpl, cv2.TM_CCOEFF_NORMED)[0, 0])
            if score > best.get(label, -2.0):
                best[label] = score
        return sorted(best.items(), key=lambda kv: kv[1], reverse=True)

    def match(self, glyph: np.ndarray, kind: str,
              allowed: set[str] | None = None) -> tuple[str | None, float]:
        ranked = self.ranked(glyph, kind, allowed)
        if not ranked or ranked[0][1] < MATCH_THRESHOLD:
            return None, ranked[0][1] if ranked else -1.0
        return ranked[0]

    # -- aprendizaje --
    def save_unknown(self, glyph: np.ndarray, kind: str) -> str:
        """Guarda un trazo desconocido y devuelve su id.

        Si ya hay uno pendiente muy parecido (el mismo número en otro color o
        con otro antialiasing) no se guarda otro: así solo se pregunta una vez.
        """
        folder = self.root / "unknown"
        folder.mkdir(parents=True, exist_ok=True)
        g = glyph.astype(np.float32)
        for path in folder.glob(f"{kind}_*.png"):
            other = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
            if other is not None and other.shape == glyph.shape and \
                    float(cv2.matchTemplate(g, other.astype(np.float32), cv2.TM_CCOEFF_NORMED)[0, 0]) \
                    >= MATCH_THRESHOLD:
                return path.stem
        gid = f"{kind}_{glyph_hash(glyph)}"
        path = folder / f"{gid}.png"
        if not path.exists():
            cv2.imwrite(str(path), glyph)
        return gid

    def pending(self) -> list[str]:
        folder = self.root / "unknown"
        return sorted(p.stem for p in folder.glob("*.png")) if folder.exists() else []

    def pending_path(self, gid: str) -> Path:
        return self.root / "unknown" / f"{gid}.png"

    def label(self, gid: str, label: str) -> None:
        """Etiqueta un trazo pendiente: pasa a ser una plantilla."""
        kind, _, h = gid.partition("_")
        if kind not in self.VALID:
            raise ValueError(f"Tipo desconocido: {kind}")
        label = label.upper() if kind == "rank" else label.lower()
        if kind == "digit":
            label = label.strip()
        if kind == "rank" and label == "10":
            label = "T"
        if label not in self.VALID[kind]:
            raise ValueError(f"Etiqueta no válida para {kind}: {label}")
        src = self.pending_path(gid)
        if not src.exists():
            raise FileNotFoundError(gid)
        dst = self.root / kind / f"{label}_{h}.png"
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.replace(dst)
        self.reload()

    def learn(self, glyph: np.ndarray, kind: str, label: str) -> None:
        """Guarda una plantilla ya etiquetada (aprendizaje automático)."""
        if label not in self.VALID[kind]:
            raise ValueError(f"Etiqueta no válida para {kind}: {label}")
        path = self.root / kind / f"{label}_{glyph_hash(glyph)}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(path), glyph)
        self.reload()

    def discard(self, gid: str) -> None:
        """Descarta un trazo pendiente (p. ej. un recorte que no era una carta)."""
        path = self.pending_path(gid)
        if path.exists():
            path.unlink()


# --------------------------------------------------------------------------- #
# Lector de cartas
# --------------------------------------------------------------------------- #
class CardReader:
    def __init__(self, library: GlyphLibrary, rank_box=(0.0, 0.0, 0.5, 0.5),
                 four_color: bool = True, learn: bool = True):
        self.lib = library
        self.rank_box = rank_box
        self.four_color = four_color
        self.learn = learn

    def read(self, img: np.ndarray) -> CardRead:
        if white_fraction(img) < CARD_WHITE_FRACTION:
            return CardRead(None, present=False)
        h, w = img.shape[:2]
        fx, fy, fw, fh = self.rank_box
        corner = img[int(fy * h):int((fy + fh) * h), int(fx * w):int((fx + fw) * w)]
        rank_mask, suit_mask = split_rank_and_suit(ink_mask(corner))
        if rank_mask is None:
            return CardRead(None, present=True, unknown=True)

        # Palo
        color = suit_color(corner, suit_mask if suit_mask is not None else rank_mask)
        if self.four_color:
            suit = _COLOR_TO_SUIT_4[color]
        else:
            if suit_mask is None:
                return CardRead(None, present=True, unknown=True)
            allowed = set(_COLOR_TO_SUITS_2[color])
            suit_glyph = normalize_glyph(suit_mask)
            suit, _ = self.lib.match(suit_glyph, "suit", allowed) if len(allowed) > 1 else (next(iter(allowed)), 1.0)
            if suit is None:
                if self.learn:
                    self.lib.save_unknown(suit_glyph, "suit")
                return CardRead(None, present=True, unknown=True)

        # Número
        glyph = normalize_glyph(rank_mask)
        rank, _ = self.lib.match(glyph, "rank")
        if rank is None:
            if self.learn:
                self.lib.save_unknown(glyph, "rank")
            return CardRead(None, present=True, unknown=True)
        return CardRead(rank + suit, present=True)
