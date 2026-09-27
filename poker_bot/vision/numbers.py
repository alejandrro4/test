"""Lectura de cantidades (bote, stacks, apuestas).

Dos caminos:

1. **Plantillas de dígitos** (rápido, ~1 ms, exacto): el número se trocea en
   caracteres y cada dígito se compara con los aprendidos.
2. **Tesseract** (OCR) cuando aparece algo que aún no conoce. Si Tesseract lee
   un número de 2 o más cifras y el troceado cuadra (mismo nº de dígitos), cada
   dígito se guarda como plantilla: **los dígitos se aprenden solos** con los
   stacks de la mesa en las primeras manos.

Una cifra suelta leída solo por Tesseract no es fiable (confunde "0" y "4", por
ejemplo), así que se marca como dudosa. Lo dudoso nunca se trata como 0: el
lector lo avisa y el asistente no recomienda hasta leerlo bien. Los dígitos que
ni así se entienden aparecen en la página para que digas cuáles son.

Todo se **cachea por contenido**: si el recorte no cambia, no se vuelve a leer.
"""

from __future__ import annotations

import hashlib
import os
import re
import threading
from collections import OrderedDict
from dataclasses import dataclass

import cv2
import numpy as np

from poker_bot.vision.cards import GlyphLibrary, normalize_glyph

# Cada proceso de Tesseract con 1 hilo: se lanzan varios en paralelo y, si cada
# uno abre los suyos, se estorban (medido: 13 s en vez de 0,4 s).
os.environ.setdefault("OMP_THREAD_LIMIT", "1")

_CACHE_SIZE = 512
_NUM_RE = re.compile(r"\d[\d.,]*")
SCALE = 3                     # ampliación antes de binarizar
SEP_HEIGHT = 0.45             # un carácter más bajo que esto (× alto de dígito) es . o ,
DIGIT_MIN_SCORE = 0.8         # correlación mínima con una plantilla de dígito
DIGIT_MARGIN = 0.05           # ventaja mínima sobre el segundo dígito más parecido
MAX_TEMPLATES_PER_DIGIT = 6


class OcrUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class AmountRead:
    value: float | None
    status: str               # "empty" (no hay número), "ok" o "unreadable"


EMPTY = AmountRead(None, "empty")
UNREADABLE = AmountRead(None, "unreadable")


def parse_amount(text: str) -> float | None:
    """Convierte el texto leído en número.

    Acepta "1,234", "1.234", "1.234,5", "1,234.5", "12.5", "12,5", "$3.40", "15 BB".
    Si solo hay un tipo de separador: con 3 cifras detrás es de miles; si no, decimal.
    """
    m = _NUM_RE.search(text.replace(" ", ""))
    if not m:
        return None
    s = m.group(0).rstrip(".,")
    if "," in s and "." in s:
        dec = "," if s.rfind(",") > s.rfind(".") else "."
        thou = "." if dec == "," else ","
        s = s.replace(thou, "").replace(dec, ".")
    elif "," in s or "." in s:
        sep = "," if "," in s else "."
        parts = s.split(sep)
        if len(parts) > 2 or len(parts[-1]) == 3:
            s = "".join(parts)                  # separador de miles
        else:
            s = parts[0] + "." + parts[1]       # decimal
    try:
        return float(s)
    except ValueError:
        return None


def preprocess(img: np.ndarray) -> np.ndarray:
    """Texto negro sobre fondo blanco, ampliado y con margen."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    gray = cv2.resize(gray, None, fx=SCALE, fy=SCALE, interpolation=cv2.INTER_CUBIC)
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if np.mean(bw) < 127:          # fondo oscuro: invertir
        bw = 255 - bw
    return cv2.copyMakeBorder(bw, 10, 10, 10, 10, cv2.BORDER_CONSTANT, value=255)


@dataclass
class _Char:
    mask: np.ndarray          # máscara 0/255 del carácter (en la imagen ampliada)
    top: int
    bottom: int
    is_sep: bool


def segment(pre: np.ndarray) -> list[_Char]:
    """Trocea el número en caracteres (de izquierda a derecha)."""
    ink = (pre < 128).astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    comps = [i for i in range(1, n) if stats[i, cv2.CC_STAT_AREA] >= 6 * SCALE]
    if not comps:
        return []
    h_max = max(stats[i, cv2.CC_STAT_HEIGHT] for i in comps)
    chars = []
    for i in sorted(comps, key=lambda i: stats[i, cv2.CC_STAT_LEFT]):
        x, y, w, h = (int(stats[i, k]) for k in (cv2.CC_STAT_LEFT, cv2.CC_STAT_TOP,
                                                 cv2.CC_STAT_WIDTH, cv2.CC_STAT_HEIGHT))
        mask = (labels[y:y + h, x:x + w] == i).astype(np.uint8) * 255
        chars.append(_Char(mask, y, y + h, is_sep=h < SEP_HEIGHT * h_max))
    return chars


def _chars_to_text(chars: list[_Char], digits: list[str]) -> str:
    """Une dígitos reconocidos y separadores (coma si baja de la línea base)."""
    baseline = max((c.bottom for c in chars if not c.is_sep), default=0)
    h = max((c.bottom - c.top for c in chars if not c.is_sep), default=1)
    out, it = [], iter(digits)
    for c in chars:
        if c.is_sep:
            out.append("," if c.bottom > baseline + 0.08 * h else ".")
        else:
            out.append(next(it))
    return "".join(out)


class NumberReader:
    def __init__(self, library: GlyphLibrary | None = None, tesseract_cmd: str | None = None):
        try:
            import pytesseract
        except ImportError as e:  # pragma: no cover - depende del entorno
            raise OcrUnavailable("Falta pytesseract: pip install pytesseract") from e
        if tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
        try:
            pytesseract.get_tesseract_version()
        except Exception as e:  # pragma: no cover
            raise OcrUnavailable(
                "No encuentro Tesseract. Instálalo (Windows: instalador de UB Mannheim) o "
                "indica la ruta con --tesseract") from e
        self._tess = pytesseract
        self.library = library
        self._cache: OrderedDict[str, AmountRead] = OrderedDict()
        self._lock = threading.Lock()   # se lee desde varios hilos a la vez
        self.calls = 0                  # nº de llamadas reales a Tesseract

    # ------------------------------------------------------------------ #
    def read(self, img: np.ndarray) -> float | None:
        """Atajo: el número o None (vacío o ilegible)."""
        return self.read_ex(img).value

    def read_ex(self, img: np.ndarray) -> AmountRead:
        if img.size == 0:
            return EMPTY
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
        if int(gray.max()) - int(gray.min()) < 40:
            return EMPTY                         # zona sin contraste: no hay número
        key = hashlib.sha1(img.tobytes()).hexdigest()
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
        result = self._read_uncached(img)
        if result.status == "ok":                # lo dudoso se reintenta (quizá ya se enseñó)
            with self._lock:
                self._cache[key] = result
                if len(self._cache) > _CACHE_SIZE:
                    self._cache.popitem(last=False)
        return result

    # ------------------------------------------------------------------ #
    def _read_uncached(self, img: np.ndarray) -> AmountRead:
        pre = preprocess(img)
        chars = segment(pre)
        glyphs = [normalize_glyph(c.mask) for c in chars if not c.is_sep]

        # 1) Plantillas
        if self.library is not None and glyphs:
            labels = [self._match_digit(g) for g in glyphs]
            if all(labels):
                value = parse_amount(_chars_to_text(chars, labels))
                if value is not None:
                    return AmountRead(value, "ok")

        # 2) Tesseract
        with self._lock:
            self.calls += 1
        text = ""
        for psm in (7, 8):
            text = self._tess.image_to_string(
                pre, config=f"--psm {psm} -c tessedit_char_whitelist=0123456789.,")
            if parse_amount(text) is not None:
                break
        value = parse_amount(text)
        if self.library is None:
            return AmountRead(value, "ok") if value is not None else UNREADABLE
        text_digits = [ch for ch in text if ch.isdigit()]
        if value is not None and len(glyphs) >= 2 and len(text_digits) == len(glyphs):
            self._learn(glyphs, text_digits)
            return AmountRead(value, "ok")
        # Dudoso: los dígitos que no conoce quedan para que la persona los enseñe
        for g in glyphs:
            if self._match_digit(g) is None:
                self.library.save_unknown(g, "digit")
        return UNREADABLE

    def _match_digit(self, glyph: np.ndarray) -> str | None:
        ranked = self.library.ranked(glyph, "digit")
        if not ranked:
            return None
        best_label, best = ranked[0]
        second = next((s for lbl, s in ranked[1:] if lbl != best_label), -1.0)
        if best >= DIGIT_MIN_SCORE and best - second >= DIGIT_MARGIN:
            return best_label
        return None

    def _learn(self, glyphs: list[np.ndarray], labels: list[str]) -> None:
        for g, label in zip(glyphs, labels):
            if self._match_digit(g) == label:
                continue                         # ya lo conoce
            if self.library.count("digit", label) < MAX_TEMPLATES_PER_DIGIT:
                self.library.learn(g, "digit", label)
