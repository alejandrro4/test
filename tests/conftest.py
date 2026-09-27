import shutil
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent))

needs_tesseract = pytest.mark.skipif(shutil.which("tesseract") is None,
                                     reason="Tesseract no instalado")


@pytest.fixture
def library(tmp_path):
    """Biblioteca de plantillas con los 13 números aprendidos de la mesa sintética."""
    import synthetic as S
    from poker_bot.core.cards import RANKS
    from poker_bot.vision.cards import CardReader, GlyphLibrary

    lib = GlyphLibrary(tmp_path / "templates")
    reader = CardReader(lib, rank_box=(0.0, 0.0, 0.5, 0.6))
    for r in RANKS:
        img = np.full((S.CARD_H, S.CARD_W, 3), S.FELT, np.uint8)
        S.draw_card(img, S.Rect(0, 0, S.CARD_W, S.CARD_H), r + "s")
        reader.read(img)
        lib.label(lib.pending()[0], r)
    # Dígitos: se aprenden solos leyendo números de varias cifras (como con los stacks)
    if shutil.which("tesseract"):
        from poker_bot.vision.numbers import NumberReader
        nr = NumberReader(lib)
        for v in (1234, 5678, 90.5, 860):
            img = np.full((40, 120, 3), S.FELT, np.uint8)
            S.draw_number(img, S.Rect(0, 5, 120, 30), v)
            assert nr.read(img) == v
        assert lib.known_labels("digit") == set("0123456789")
    return lib


@pytest.fixture
def table_reader(library):
    import synthetic as S
    from poker_bot.vision.cards import CardReader
    from poker_bot.vision.numbers import NumberReader
    from poker_bot.vision.reader import TableReader, color_hist

    hist = color_hist(S.calibration().action_buttons.crop(S.render(my_turn=True)))
    calib = S.calibration(hist)
    return TableReader(calib, CardReader(library, calib.rank_box, calib.four_color_deck),
                       NumberReader(library))
