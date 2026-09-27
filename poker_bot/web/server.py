"""Servidor web local: la página para meter la mano con clics y la API del cerebro.

Uso:
    python -m poker_bot.web.server            # solo este PC: http://127.0.0.1:8000
    python -m poker_bot.web.server --lan      # también desde el móvil en la misma wifi

Solo usa la librería estándar (http.server), así que no hace falta instalar
nada más. Todas las cantidades de la API van en ciegas grandes.
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from poker_bot.core.cards import InvalidCardError, parse_cards
from poker_bot.engine.decision import decide
from poker_bot.engine.opponents import STYLE_PRESETS
from poker_bot.quick import postflop_state, preflop_state
from poker_bot.stats.store import Store

STATIC = Path(__file__).parent / "static"
MAX_BODY = 64 * 1024
DEFAULT_BUDGET_MS = 1000.0


class ApiError(ValueError):
    """Error de datos del usuario: se devuelve como 400 con un mensaje legible."""


# --------------------------------------------------------------------------- #
# Lógica de la API (separada del HTTP para poder testearla directamente)
# --------------------------------------------------------------------------- #
def _num(d: dict, key: str, default: float, lo: float = 0.0, hi: float = 1e6) -> float:
    try:
        v = float(d.get(key, default))
    except (TypeError, ValueError):
        raise ApiError(f"'{key}' debe ser un número")
    if not lo <= v <= hi:
        raise ApiError(f"'{key}' fuera de rango ({lo}–{hi})")
    return v


def handle_decide(payload: dict, store: Store | None = None) -> dict:
    try:
        hero = parse_cards(payload.get("hero", []))
        board = parse_cards(payload.get("board", []))
    except InvalidCardError as e:
        raise ApiError(str(e))
    if len(hero) != 2:
        raise ApiError("Elige tus 2 cartas")
    if len(board) not in (0, 3, 4, 5):
        raise ApiError("El board debe tener 0, 3, 4 o 5 cartas")
    if set(hero) & set(board):
        raise ApiError("Hay cartas repetidas entre tu mano y el board")
    budget = _num(payload, "budget_ms", DEFAULT_BUDGET_MS, 50, 5000)
    rivals = [str(r) for r in payload.get("rivals", []) if str(r).strip()]
    profiles = store.profiles(rivals) if store else {}

    try:
        if not board:
            pre = payload.get("preflop", {})
            players = int(_num(pre, "players", 6, 2, 10))
            opener = pre.get("opener") or None
            names = {opener.upper(): rivals[0]} if opener and rivals else {}
            state = preflop_state(
                "".join(hero), str(pre.get("position", "")), players,
                _num(pre, "stack", 100, 1, 10000), opener,
                _num(pre, "open_size", 2.5, 1, 10000), bool(pre.get("all_in")), names,
            )
        else:
            post = payload.get("postflop", {})
            villains = int(_num(post, "villains", 1, 1, 8))
            names = rivals[:villains] + [f"Rival{i + 1}" for i in range(len(rivals), villains)]
            state = postflop_state(
                "".join(hero), "".join(board), _num(post, "pot", 0, 0.01, 1e6),
                _num(post, "to_call", 0, 0, 1e6), _num(post, "stack", 100, 0.01, 1e6),
                _num(post, "villain_stack", _num(post, "stack", 100, 0.01, 1e6), 0.01, 1e6),
                villains, bool(post.get("in_position", True)),
                str(post.get("villain_preflop", "call")), bool(post.get("villain_checked")), names,
            )
    except KeyError as e:
        raise ApiError(f"Posición no válida: {e}")
    except ValueError as e:
        raise ApiError(str(e))

    d = decide(state, profiles, budget_ms=budget)
    result = {
        "street": state.street.value,
        "action": d.action.value,
        "amount_bb": d.amount / state.big_blind,
        "headline": d.headline(),
        "equity": d.equity,
        "ev_bb": d.ev_bb,
        "reason": d.reason,
        "speech": d.speech(),
        "elapsed_ms": round(d.elapsed_ms),
        "alternatives": [
            {"action": o.action.value, "amount_bb": o.amount / state.big_blind,
             "ev_bb": None if o.ev is None else o.ev / state.big_blind}
            for o in d.alternatives
        ],
    }
    if store:
        store.log_decision(street=result["street"], hero=hero, board=board, rivals=rivals,
                           action=result["action"], amount_bb=result["amount_bb"],
                           equity=d.equity, ev_bb=d.ev_bb, reason=d.reason, request=payload)
    return result


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
class Handler(BaseHTTPRequestHandler):
    store: Store  # se asigna en make_server
    server_version = "PokerBot/1.0"

    def log_message(self, fmt: str, *args) -> None:   # silencio: sin ruido en la consola
        pass

    # -- utilidades --
    def _send(self, status: int, body: bytes, ctype: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, data) -> None:
        self._send(status, json.dumps(data, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise ApiError("Petición demasiado grande")
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            raise ApiError("JSON inválido")
        if not isinstance(data, dict):
            raise ApiError("Se esperaba un objeto JSON")
        return data

    def _dispatch(self, method: str) -> None:
        path = urlparse(self.path).path
        try:
            if method == "GET" and path in ("/", "/index.html"):
                self._send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
            elif method == "GET" and path == "/api/styles":
                self._json(200, list(STYLE_PRESETS))
            elif method == "GET" and path == "/api/friends":
                self._json(200, self.store.list_friends())
            elif method == "POST" and path == "/api/friends":
                b = self._body()
                try:
                    self.store.save_friend(str(b.get("name", "")), str(b.get("style", "normal")),
                                           str(b.get("notes", "")))
                except ValueError as e:
                    raise ApiError(str(e))
                self._json(200, self.store.list_friends())
            elif method == "DELETE" and path.startswith("/api/friends/"):
                self.store.delete_friend(unquote(path.rsplit("/", 1)[1]))
                self._json(200, self.store.list_friends())
            elif method == "POST" and path == "/api/decide":
                self._json(200, handle_decide(self._body(), self.store))
            elif method == "GET" and path == "/api/history":
                self._json(200, self.store.recent_decisions())
            else:
                self._json(404, {"error": "No encontrado"})
        except ApiError as e:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(e)})
        except Exception as e:  # noqa: BLE001 - nunca tumbar el servidor por una petición
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"Error interno: {e}"})

    def do_GET(self) -> None:
        self._dispatch("GET")

    def do_POST(self) -> None:
        self._dispatch("POST")

    def do_DELETE(self) -> None:
        self._dispatch("DELETE")


def make_server(host: str = "127.0.0.1", port: int = 8000, store: Store | None = None) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (Handler,), {"store": store or Store()})
    return ThreadingHTTPServer((host, port), handler)


def _lan_ip() -> str:
    """IP del PC en la red local (para abrir la página desde el móvil)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))   # no envía nada, solo elige la interfaz
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Página web del asistente de póker")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--lan", action="store_true", help="accesible desde otros dispositivos de la wifi")
    args = ap.parse_args(argv)
    host = "0.0.0.0" if args.lan else "127.0.0.1"
    server = make_server(host, args.port)
    print(f"Asistente listo en http://127.0.0.1:{args.port}")
    if args.lan:
        print(f"Desde el móvil (misma wifi): http://{_lan_ip()}:{args.port}")
    print("Ctrl+C para salir.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
