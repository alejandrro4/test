import json
import threading
import urllib.error
import urllib.request

import pytest

from poker_bot.web.server import ApiError, handle_decide, make_server


def test_decide_preflop():
    r = handle_decide({"hero": ["As", "Kd"], "preflop": {"position": "CO"}})
    assert r["street"] == "preflop" and r["action"] == "raise" and r["amount_bb"] == 2.5


def test_decide_postflop():
    r = handle_decide({"hero": ["7s", "7d"], "board": ["Kc", "7h", "2d"],
                       "postflop": {"pot": 5.5, "villain_checked": True}})
    assert r["action"] == "bet" and r["equity"] > 0.9


@pytest.mark.parametrize("req, msg", [
    ({"hero": ["As"]}, "2 cartas"),
    ({"hero": ["As", "As"]}, "repetidas"),
    ({"hero": ["As", "Kd"], "board": ["Qh", "7c"]}, "board"),
    ({"hero": ["As", "Kd"], "board": ["As", "7c", "2d"]}, "repetidas"),
    ({"hero": ["As", "Kd"], "preflop": {"position": "XX"}}, "Posiciones"),
    ({"hero": ["As", "Kd"], "preflop": {"position": "UTG", "opener": "CO"}}, "antes"),
    ({"hero": ["As", "Kd"], "board": ["Qh", "7c", "2d"], "postflop": {"pot": "mucho"}}, "número"),
    ({"hero": ["Zz", "Kd"]}, "inválida"),
])
def test_errores_legibles(req, msg):
    with pytest.raises(ApiError, match=msg):
        handle_decide(req)


@pytest.fixture(scope="module")
def base_url():
    server = make_server("127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def call(url, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def test_sin_modo_en_vivo_sirve_el_manual(base_url):
    status, body = call(base_url + "/")
    assert status == 200 and b"Elige tus cartas" in body
    assert call(base_url + "/api/live")[0] == 400
    assert call(base_url + "/api/glyphs")[0] == 400


def test_api_decide(base_url):
    status, body = call(base_url + "/api/decide", "POST", {"hero": ["As", "Kd"], "preflop": {"position": "BTN"}})
    assert status == 200 and json.loads(body)["action"] == "raise"
    assert call(base_url + "/api/decide", "POST", {"hero": ["As"]})[0] == 400
    assert call(base_url + "/nada")[0] == 404
