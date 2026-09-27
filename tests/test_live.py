"""Modo en vivo de punta a punta sobre la mesa sintética."""
import json
import threading
import time
import urllib.request

import numpy as np
import pytest

import synthetic as S
from conftest import needs_tesseract
from poker_bot.live import LiveAssistant, LiveFeed
from poker_bot.vision.tracker import HandTracker
from poker_bot.web.server import make_server

pytestmark = needs_tesseract

SEATS = [(100, 0, True), (100, 0, True), (100, 0, True), (100, 0, True), (99.5, 0.5, True),
         (99, 1, True)]


class ListSource:
    def __init__(self, frames):
        self.frames = list(frames)

    def grab(self):
        return self.frames.pop(0) if len(self.frames) > 1 else self.frames[0]


def assistant(table_reader, frames):
    return LiveAssistant(ListSource(frames), table_reader, HandTracker(), LiveFeed(),
                         table_reader.cards.lib, budget_ms=300)


def test_recomienda_en_mi_turno_y_limpia_despues(table_reader):
    wait = S.render(hero=("As", "Ad"), pot=1.5, seats=SEATS, dealer=3, my_turn=False)
    turn = S.render(hero=("As", "Ad"), pot=1.5, seats=SEATS, dealer=3, my_turn=True)
    live = assistant(table_reader, [wait, wait, turn, turn, turn, wait, wait])
    for _ in range(2):
        live.step()
    assert live.feed.snapshot()["decision"] is None
    live.step()
    live.step()
    snap = live.feed.snapshot()
    d = snap["decision"]
    assert d and d["action"] == "raise" and "SUBIR" in d["headline"]
    assert snap["seen"]["hero"] == ["As", "Ad"] and snap["seen"]["dealer"] == 3
    assert d["elapsed_ms"] < 3000
    for _ in range(3):
        live.step()
    assert live.feed.snapshot()["decision"] is None


def test_carta_desconocida_no_recomienda(tmp_path, table_reader):
    from poker_bot.vision.cards import GlyphLibrary
    table_reader.cards.lib = GlyphLibrary(tmp_path)      # biblioteca vacía
    turn = S.render(hero=("As", "Ad"), pot=1.5, seats=SEATS, dealer=3, my_turn=True)
    live = assistant(table_reader, [turn] * 3)
    for _ in range(3):
        live.step()
    snap = live.feed.snapshot()
    assert snap["decision"] is None and snap["pending_glyphs"] >= 1


@pytest.fixture
def server(table_reader):
    turn = S.render(hero=("Kh", "Kd"), pot=1.5, seats=SEATS, dealer=3, my_turn=True)
    live = assistant(table_reader, [turn])
    srv = make_server("127.0.0.1", 0, live=live)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}"
    yield url, live
    srv.shutdown()
    srv.server_close()


def get(url):
    with urllib.request.urlopen(url, timeout=10) as r:
        return r.status, r.read()


def post(url, body, method="POST"):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def test_pagina_en_vivo(server):
    url, _ = server
    status, body = get(url + "/")
    assert status == 200 and b"Asistente en vivo" in body
    assert b"Asistente" in get(url + "/manual")[1]


def test_eventos_en_tiempo_real(server):
    url, live = server
    got = {}

    def listen():
        with urllib.request.urlopen(url + "/api/live/stream", timeout=10) as r:
            for line in r:
                if line.startswith(b"data: "):
                    snap = json.loads(line[6:])
                    if snap.get("decision"):
                        got["snap"] = snap
                        return

    t = threading.Thread(target=listen, daemon=True)
    t.start()
    time.sleep(0.2)
    for _ in range(3):
        live.step()
    t.join(timeout=10)
    assert got["snap"]["decision"]["action"] == "raise"


def test_pausa(server):
    url, live = server
    assert post(url + "/api/live/pause", {"paused": True}) == {"paused": True}
    assert live.paused and live.feed.snapshot()["paused"]
    post(url + "/api/live/pause", {"paused": False})
    assert not live.paused


def test_ensenar_cartas_desde_la_web(server):
    url, live = server
    lib = live.library
    img = np.full((S.CARD_H, S.CARD_W, 3), S.FELT, np.uint8)
    S.draw_card(img, S.Rect(0, 0, S.CARD_W, S.CARD_H), "Kh")
    # Olvidamos la K para que vuelva a preguntar
    for f in (lib.root / "rank").glob("K_*.png"):
        f.unlink()
    lib.reload()
    live.reader.cards.read(img)
    (gid,) = json.loads(get(url + "/api/glyphs")[1])
    status, png = get(url + f"/api/glyphs/{gid}.png")
    assert status == 200 and png[:4] == b"\x89PNG"
    assert post(url + f"/api/glyphs/{gid}", {"label": "K"}) == []
    assert live.reader.cards.read(img).card == "Kh"
