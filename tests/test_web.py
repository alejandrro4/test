import json
import threading
import urllib.error
import urllib.request

import pytest

from poker_bot.stats.store import Store
from poker_bot.web.server import ApiError, handle_decide, make_server


# ------------------------------- lógica ----------------------------------- #
def test_decide_preflop():
    r = handle_decide({"hero": ["As", "Kd"], "preflop": {"position": "CO"}})
    assert r["street"] == "preflop" and r["action"] == "raise" and r["amount_bb"] == 2.5


def test_decide_postflop_con_amigo():
    store = Store(":memory:")
    store.save_friend("Pepe", "calling station")
    req = {"hero": ["Ah", "3c"], "board": ["Kh", "9h", "4c", "2h", "7d"], "rivals": ["Pepe"],
           "postflop": {"pot": 20, "stack": 80, "villain_checked": True}}
    r = handle_decide(req, store)
    assert r["action"] == "check" and "calling station" in r["reason"]
    assert store.recent_decisions()[0]["rivals"] == "Pepe"


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


# -------------------------------- HTTP ------------------------------------ #
@pytest.fixture(scope="module")
def base_url():
    server = make_server("127.0.0.1", 0, Store(":memory:"))
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


def test_pagina(base_url):
    status, body = call(base_url + "/")
    assert status == 200 and b"Asistente" in body


def test_api_decide(base_url):
    status, body = call(base_url + "/api/decide", "POST",
                        {"hero": ["7s", "7d"], "board": ["Kc", "7h", "2d"],
                         "postflop": {"pot": 5.5, "villain_checked": True}})
    data = json.loads(body)
    assert status == 200 and data["action"] == "bet" and data["equity"] > 0.9


def test_api_amigos(base_url):
    status, body = call(base_url + "/api/friends", "POST", {"name": "Luis", "style": "roca"})
    assert status == 200 and json.loads(body)[0]["name"] == "Luis"
    status, body = call(base_url + "/api/friends/Luis", "DELETE")
    assert json.loads(body) == []


def test_api_errores(base_url):
    assert call(base_url + "/api/decide", "POST", {"hero": ["As"]})[0] == 400
    assert call(base_url + "/api/friends", "POST", {"name": "X", "style": "raro"})[0] == 400
    assert call(base_url + "/nada")[0] == 404
