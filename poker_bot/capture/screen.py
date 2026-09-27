"""Fuentes de imágenes de la mesa.

* ``ScreenSource``: captura en vivo solo la zona de la mesa con ``mss``
  (rápido: ~5–15 ms por captura).
* ``FileSource``: reproduce capturas guardadas (una imagen o una carpeta),
  para probar la lectura sin estar jugando o para depurar con tus capturas.

Ambas devuelven imágenes BGR (formato de OpenCV) del tamaño de la mesa.
"""

from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np

from poker_bot.vision.calibration import Rect


class ScreenSource:
    def __init__(self, table: Rect):
        import mss  # import aquí: en tests no hace falta pantalla

        self._sct = mss.mss()
        self.region = {"left": table.x, "top": table.y, "width": table.w, "height": table.h}

    def grab(self) -> np.ndarray:
        shot = np.asarray(self._sct.grab(self.region))   # BGRA
        return cv2.cvtColor(shot, cv2.COLOR_BGRA2BGR)


def grab_full_screen(monitor: int = 1) -> np.ndarray:
    """Captura de la pantalla entera (para la calibración)."""
    import mss

    with mss.mss() as sct:
        shot = np.asarray(sct.grab(sct.monitors[monitor]))
    return cv2.cvtColor(shot, cv2.COLOR_BGRA2BGR)


class FileSource:
    """Reproduce imágenes: cada ``grab()`` devuelve la siguiente (en bucle opcional).

    Si las imágenes son capturas de pantalla completa, se recortan a ``table``.
    """

    def __init__(self, path: str | Path, table: Rect | None = None, loop: bool = False,
                 frames_per_image: int = 3):
        p = Path(path)
        files = sorted(f for f in p.iterdir() if f.suffix.lower() in (".png", ".jpg", ".jpeg", ".bmp")) \
            if p.is_dir() else [p]
        if not files:
            raise FileNotFoundError(f"No hay imágenes en {p}")
        self.images = []
        for f in files:
            img = cv2.imread(str(f))
            if img is None:
                raise ValueError(f"No puedo abrir {f}")
            if table and (img.shape[1] > table.w or img.shape[0] > table.h):
                img = table.crop(img)
            self.images.append(img)
        self.loop = loop
        # Cada imagen se repite varios frames para que el seguidor la vea "estable"
        self.frames_per_image = frames_per_image
        self._i = 0

    @property
    def finished(self) -> bool:
        return not self.loop and self._i >= len(self.images) * self.frames_per_image

    def grab(self) -> np.ndarray:
        n = len(self.images) * self.frames_per_image
        idx = min(self._i, n - 1) if not self.loop else self._i % n
        self._i += 1
        return self.images[idx // self.frames_per_image]


def paced(fps: float):
    """Generador que marca el ritmo del bucle de captura (duerme lo que sobre)."""
    period = 1.0 / fps
    nxt = time.perf_counter()
    while True:
        yield
        nxt += period
        delay = nxt - time.perf_counter()
        if delay > 0:
            time.sleep(delay)
        else:
            nxt = time.perf_counter()
