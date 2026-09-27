"""Modo en vivo: lee tu mesa sola y te dice la jugada en cuanto es tu turno.

    python -m poker_bot.live                 # abre http://127.0.0.1:8000 y empieza a mirar
    python -m poker_bot.live --lan           # también en el móvil (misma wifi)
    python -m poker_bot.live --replay capturas/   # prueba con capturas guardadas

Bucle (8 veces por segundo por defecto):
  captura de la mesa → lectura (cartas, números, turno) → seguimiento de la
  mano → si es tu turno y la lectura es fiable: decisión → página web (y voz).

Nunca hace clics: solo mira y recomienda.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import threading
import time
import traceback
from typing import Any

from poker_bot.engine.decision import decide
from poker_bot.vision.reader import TableRead

DEFAULT_FPS = 8.0
DEFAULT_BUDGET_MS = 600.0


class LiveFeed:
    """Última "foto" del asistente, compartida entre el bucle y la web."""

    def __init__(self):
        self._cond = threading.Condition()
        self._snap: dict[str, Any] = {"seq": 0, "status": "Arrancando…", "decision": None,
                                      "seen": None, "problems": [], "paused": False}

    def publish(self, **fields) -> None:
        with self._cond:
            snap = dict(self._snap)
            snap.update(fields)
            if snap != self._snap:
                snap["seq"] = self._snap["seq"] + 1
                self._snap = snap
                self._cond.notify_all()

    def snapshot(self) -> dict[str, Any]:
        with self._cond:
            return dict(self._snap)

    def wait_newer(self, seq: int, timeout: float) -> dict[str, Any]:
        """Espera a que haya una foto más nueva que ``seq`` (o se acabe el tiempo)."""
        with self._cond:
            self._cond.wait_for(lambda: self._snap["seq"] != seq, timeout=timeout)
            return dict(self._snap)


def seen_dict(raw: TableRead) -> dict[str, Any]:
    return {
        "hero": raw.hero_cards,
        "board": raw.board,
        "pot": raw.pot,
        "dealer": raw.dealer_seat,
        "my_turn": raw.my_turn,
        "seats": [{"stack": s.stack, "bet": s.bet, "cards": s.has_cards} for s in raw.seats],
    }


def decision_dict(d, elapsed_total_ms: float, chips_per_bb: float | None = None) -> dict[str, Any]:
    bb = d.big_blind
    return {
        "action": d.action.value,
        "amount_bb": d.amount / bb,
        "headline": d.headline(chips_per_bb),
        "equity": d.equity,
        "ev_bb": d.ev_bb,
        "reason": d.reason,
        "speech": d.speech(),
        "elapsed_ms": round(elapsed_total_ms),
        "alternatives": [{"action": o.action.value, "amount_bb": o.amount / bb,
                          "ev_bb": None if o.ev is None else o.ev / bb} for o in d.alternatives],
    }


class LiveAssistant:
    def __init__(self, source, reader, tracker, feed: LiveFeed, library=None,
                 fps: float = DEFAULT_FPS, budget_ms: float = DEFAULT_BUDGET_MS,
                 chips_per_bb: float | None = None):
        self.source = source
        self.reader = reader
        self.tracker = tracker
        self.feed = feed
        self.library = library
        self.fps = fps
        self.budget_ms = budget_ms
        self.chips_per_bb = chips_per_bb   # para dar la cantidad en fichas si la mesa usa fichas
        self.paused = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_hash = None
        self._last_raw: TableRead | None = None
        self._turn_started: float | None = None

    # -- control --
    def start(self) -> None:
        self._thread = threading.Thread(target=self.run, name="live", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)

    def set_paused(self, paused: bool) -> None:
        self.paused = paused
        self.feed.publish(paused=paused, status="En pausa" if paused else "Mirando la mesa…")

    # -- bucle --
    def run(self) -> None:
        from poker_bot.capture.screen import paced

        for _ in paced(self.fps):
            if self._stop.is_set() or getattr(self.source, "finished", False):
                break
            if self.paused:
                continue
            try:
                self.step()
            except Exception as e:  # noqa: BLE001 - el bucle nunca debe morir
                traceback.print_exc()
                self.feed.publish(status=f"Error leyendo la mesa: {e}", decision=None)

    def step(self) -> None:
        """Un frame: captura, lectura, seguimiento y (si toca) decisión."""
        frame = self.source.grab()
        h = hashlib.sha1(frame[::3, ::3].tobytes()).digest()
        if h == self._last_hash and self._last_raw is not None:
            raw = self._last_raw                 # pantalla igual: no hace falta releer
        else:
            t = time.perf_counter()
            raw = self.reader.read(frame)
            self._last_raw, self._last_hash = raw, h
            if raw.my_turn and self._turn_started is None:
                self._turn_started = t

        upd = self.tracker.update(raw)
        pending = len(self.library.pending()) if self.library else 0
        fields: dict[str, Any] = {"status": upd.status, "problems": upd.problems,
                                  "seen": seen_dict(raw), "pending_glyphs": pending}
        if not raw.my_turn:
            self._turn_started = None
            fields["decision"] = None
            if upd.state is not None:            # el seguidor aún no ha visto el cambio estable
                fields["status"] = "Leyendo la mesa…"
        elif upd.state is not None and upd.new_decision:
            d = decide(upd.state, budget_ms=self.budget_ms)
            started = self._turn_started or time.perf_counter()
            fields["decision"] = decision_dict(d, (time.perf_counter() - started) * 1000,
                                               self.chips_per_bb)
        elif upd.state is None:
            fields["decision"] = None            # tu turno pero lectura dudosa: no recomendar
        self.feed.publish(**fields)


# --------------------------------------------------------------------------- #
def build(calibration_path=None, replay: str | None = None, tesseract: str | None = None,
          fps: float = DEFAULT_FPS, budget_ms: float = DEFAULT_BUDGET_MS):
    """Monta todas las piezas a partir de la calibración guardada."""
    from poker_bot.capture.screen import FileSource, ScreenSource
    from poker_bot.vision.calibration import DEFAULT_PATH, Calibration
    from poker_bot.vision.cards import CardReader, GlyphLibrary
    from poker_bot.vision.numbers import NumberReader
    from poker_bot.vision.reader import TableReader
    from poker_bot.vision.tracker import HandTracker

    calib = Calibration.load(calibration_path or DEFAULT_PATH)
    library = GlyphLibrary()
    cards = CardReader(library, calib.rank_box, calib.four_color_deck)
    reader = TableReader(calib, cards, NumberReader(library, tesseract))
    source = FileSource(replay, calib.table) if replay else ScreenSource(calib.table)
    tracker = HandTracker(pot_includes_bets=calib.pot_includes_bets)
    feed = LiveFeed()
    chips = None if calib.amounts_in_bb else calib.big_blind
    return LiveAssistant(source, reader, tracker, feed, library, fps, budget_ms, chips)


def main(argv: list[str] | None = None) -> int:
    from poker_bot.web.server import _lan_ip, make_server

    ap = argparse.ArgumentParser(description="Asistente en vivo: lee la mesa y recomienda")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--lan", action="store_true", help="accesible desde el móvil (misma wifi)")
    ap.add_argument("--fps", type=float, default=DEFAULT_FPS)
    ap.add_argument("--ms", type=float, default=DEFAULT_BUDGET_MS, help="tiempo máximo de cálculo")
    ap.add_argument("--replay", help="carpeta o imagen con capturas para probar sin jugar")
    ap.add_argument("--tesseract", help="ruta a tesseract.exe si no está en el PATH")
    ap.add_argument("--calibration", help="ruta del JSON de calibración")
    args = ap.parse_args(argv)

    try:
        live = build(args.calibration, args.replay, args.tesseract, args.fps, args.ms)
    except (FileNotFoundError, RuntimeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    server = make_server("0.0.0.0" if args.lan else "127.0.0.1", args.port, live=live)
    live.start()
    print(f"Asistente en vivo: http://127.0.0.1:{args.port}")
    if args.lan:
        print(f"Desde el móvil: http://{_lan_ip()}:{args.port}")
    print("Ctrl+C para salir.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        live.stop()
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
