"""Servidor web local.

* ``/``        modo en vivo: lo que el bot ve de tu mesa y la jugada en tu turno.
* ``/manual``  modo manual: marcas la mano con clics (si no hay calibración).

API (cantidades en ciegas grandes):
* ``GET  /api/live/stream``      eventos en tiempo real (Server-Sent Events)
* ``POST /api/live/pause``       ``{"paused": true|false}``
* ``GET  /api/glyphs``           trazos de cartas pendientes de enseñar
* ``GET  /api/glyphs/<id>.png``  imagen de un trazo
* ``POST /api/glyphs/<id>``      ``{"label": "Q"}`` enseña qué es
* ``DELETE /api/glyphs/<id>``    lo descarta
* ``POST /api/decide``           decisión para una situación escrita a mano

Solo usa la librería estándar (http.server).
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

import cv2

from poker_bot.core.cards import InvalidCardError, parse_cards
from poker_bot.engine.decision import decide
from poker_bot.quick import postflop_state, preflop_state

STATIC = Path(__file__).parent / "static"
MAX_BODY = 64 * 1024
DEFAULT_BUDGET_MS = 1000.0
SSE_KEEPALIVE_S = 15.0


class ApiError(ValueError):
    """Error de datos del usuario: se devuelve como 400 con un mensaje legible."""


# --------------------------------------------------------------------------- #
# Modo manual
# --------------------------------------------------------------------------- #
def _num(d: dict, key: str, default: float, lo: float = 0.0, hi: float = 1e6) -> float:
    try:
        v = float(d.get(key, default))
    except (TypeError, ValueError):
        raise ApiError(f"'{key}' debe ser un número")
    if not lo <= v <= hi:
        raise ApiError(f"'{key}' fuera de rango ({lo}–{hi})")
    return v


def handle_decide(payload: dict) -> dict:
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

    try:
        if not board:
            pre = payload.get("preflop", {})
            state = preflop_state(
                "".join(hero), str(pre.get("position", "")), int(_num(pre, "players", 6, 2, 10)),
                _num(pre, "stack", 100, 1, 10000), pre.get("opener") or None,
                _num(pre, "open_size", 2.5, 1, 10000), bool(pre.get("all_in")),
            )
        else:
            post = payload.get("postflop", {})
            stack = _num(post, "stack", 100, 0.01, 1e6)
            state = postflop_state(
                "".join(hero), "".join(board), _num(post, "pot", 0, 0.01, 1e6),
                _num(post, "to_call", 0, 0, 1e6), stack,
                _num(post, "villain_stack", stack, 0.01, 1e6),
                int(_num(post, "villains", 1, 1, 8)), bool(post.get("in_position", True)),
                str(post.get("villain_preflop", "call")), bool(post.get("villain_checked")),
            )
    except KeyError as e:
        raise ApiError(f"Posición no válida: {e}")
    except ValueError as e:
        raise ApiError(str(e))

    d = decide(state, budget_ms=budget)
    bb = state.big_blind
    return {
        "street": state.street.value,
        "action": d.action.value,
        "amount_bb": d.amount / bb,
        "headline": d.headline(),
        "equity": d.equity,
        "ev_bb": d.ev_bb,
        "reason": d.reason,
        "speech": d.speech(),
        "elapsed_ms": round(d.elapsed_ms),
        "alternatives": [{"action": o.action.value, "amount_bb": o.amount / bb,
                          "ev_bb": None if o.ev is None else o.ev / bb} for o in d.alternatives],
    }


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
class Handler(BaseHTTPRequestHandler):
    live = None          # LiveAssistant (se asigna en make_server) o None
    server_version = "PokerBot/2.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args) -> None:   # sin ruido en la consola
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
        self._send(status, json.dumps(data, ensure_ascii=False).encode(),
                   "application/json; charset=utf-8")

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

    def _library(self):
        lib = getattr(self.live, "library", None)
        if lib is None:
            raise ApiError("El modo en vivo no está activo")
        return lib

    def _stream(self) -> None:
        """Server-Sent Events: manda cada foto nueva del asistente en cuanto existe."""
        if self.live is None:
            self._json(404, {"error": "El modo en vivo no está activo"})
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        feed = self.live.feed
        seq = -1
        try:
            while True:
                snap = feed.wait_newer(seq, timeout=SSE_KEEPALIVE_S)
                if snap["seq"] == seq:
                    self.wfile.write(b": keepalive\n\n")
                else:
                    seq = snap["seq"]
                    self.wfile.write(b"data: " + json.dumps(snap, ensure_ascii=False).encode() + b"\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    def _dispatch(self, method: str) -> None:
        path = urlparse(self.path).path
        try:
            if method == "GET" and path in ("/", "/live"):
                page = "live.html" if self.live is not None else "index.html"
                self._send(200, (STATIC / page).read_bytes(), "text/html; charset=utf-8")
            elif method == "GET" and path == "/manual":
                self._send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
            elif method == "POST" and path == "/api/decide":
                self._json(200, handle_decide(self._body()))
            elif method == "GET" and path == "/api/live":
                if self.live is None:
                    raise ApiError("El modo en vivo no está activo")
                self._json(200, self.live.feed.snapshot())
            elif method == "GET" and path == "/api/live/stream":
                self._stream()
            elif method == "POST" and path == "/api/live/pause":
                if self.live is None:
                    raise ApiError("El modo en vivo no está activo")
                self.live.set_paused(bool(self._body().get("paused")))
                self._json(200, {"paused": self.live.paused})
            elif method == "GET" and path == "/api/glyphs":
                self._json(200, self._library().pending())
            elif method == "GET" and path.startswith("/api/glyphs/") and path.endswith(".png"):
                gid = unquote(path[len("/api/glyphs/"):-4])
                img = cv2.imread(str(self._library().pending_path(gid)), cv2.IMREAD_GRAYSCALE)
                if img is None:
                    self._json(404, {"error": "No existe"})
                    return
                big = cv2.resize(255 - img, None, fx=3, fy=3, interpolation=cv2.INTER_NEAREST)
                self._send(200, cv2.imencode(".png", big)[1].tobytes(), "image/png")
            elif method == "POST" and path.startswith("/api/glyphs/"):
                gid = unquote(path[len("/api/glyphs/"):])
                try:
                    self._library().label(gid, str(self._body().get("label", "")))
                except (ValueError, FileNotFoundError) as e:
                    raise ApiError(f"No se pudo guardar: {e}")
                self._json(200, self._library().pending())
            elif method == "DELETE" and path.startswith("/api/glyphs/"):
                self._library().discard(unquote(path[len("/api/glyphs/"):]))
                self._json(200, self._library().pending())
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


def make_server(host: str = "127.0.0.1", port: int = 8000, live=None) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (Handler,), {"live": live})
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    return server


def _lan_ip() -> str:
    """IP del PC en la red local (para abrir la página desde el móvil)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))   # no envía nada, solo elige la interfaz
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Página del asistente de póker (modo manual)")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--lan", action="store_true", help="accesible desde otros dispositivos de la wifi")
    args = ap.parse_args(argv)
    server = make_server("0.0.0.0" if args.lan else "127.0.0.1", args.port)
    print(f"Modo manual en http://127.0.0.1:{args.port}")
    if args.lan:
        print(f"Desde el móvil (misma wifi): http://{_lan_ip()}:{args.port}")
    print("Para el modo en vivo usa: python -m poker_bot.live")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
