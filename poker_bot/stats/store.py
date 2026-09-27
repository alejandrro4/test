"""Almacenamiento en SQLite: amigos (con su estilo o estadísticas) y registro
de cada recomendación, para revisar la sesión y generar el resumen final.

Una sola conexión protegida con un lock: el servidor web atiende peticiones
en varios hilos, y SQLite no permite compartir conexiones sin cuidado.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

from poker_bot.engine.opponents import STYLE_PRESETS, OpponentStats, from_style

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "data" / "poker_bot.sqlite"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS friends (
    name  TEXT PRIMARY KEY,
    style TEXT NOT NULL DEFAULT 'normal',
    notes TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS decisions (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        REAL NOT NULL,
    street    TEXT NOT NULL,
    hero      TEXT NOT NULL,
    board     TEXT NOT NULL,
    rivals    TEXT NOT NULL,
    action    TEXT NOT NULL,
    amount_bb REAL NOT NULL,
    equity    REAL,
    ev_bb     REAL,
    reason    TEXT NOT NULL,
    request   TEXT NOT NULL
);
"""


class Store:
    def __init__(self, path: str | Path = DEFAULT_PATH):
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(_SCHEMA)

    # ------------------------------------------------------------------ #
    # Amigos
    # ------------------------------------------------------------------ #
    def list_friends(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute("SELECT name, style, notes FROM friends ORDER BY name").fetchall()
        return [dict(r) for r in rows]

    def save_friend(self, name: str, style: str = "normal", notes: str = "") -> None:
        name = name.strip()
        if not name:
            raise ValueError("El nombre no puede estar vacío")
        if style not in STYLE_PRESETS:
            raise ValueError(f"Estilo desconocido: {style!r}")
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO friends(name, style, notes) VALUES (?, ?, ?) "
                "ON CONFLICT(name) DO UPDATE SET style = excluded.style, notes = excluded.notes",
                (name, style, notes),
            )

    def delete_friend(self, name: str) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM friends WHERE name = ?", (name,))

    def profile(self, name: str) -> OpponentStats | None:
        with self._lock:
            row = self._conn.execute("SELECT style FROM friends WHERE name = ?", (name,)).fetchone()
        return from_style(name, row["style"]) if row else None

    def profiles(self, names: list[str]) -> dict[str, OpponentStats]:
        out = {}
        for n in names:
            p = self.profile(n)
            if p is not None:
                out[n] = p
        return out

    # ------------------------------------------------------------------ #
    # Registro de decisiones
    # ------------------------------------------------------------------ #
    def log_decision(self, *, street: str, hero: list[str], board: list[str], rivals: list[str],
                     action: str, amount_bb: float, equity: float | None, ev_bb: float | None,
                     reason: str, request: dict) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO decisions(ts, street, hero, board, rivals, action, amount_bb, equity,"
                " ev_bb, reason, request) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (time.time(), street, "".join(hero), "".join(board), ",".join(rivals), action,
                 amount_bb, equity, ev_bb, reason, json.dumps(request)),
            )

    def recent_decisions(self, limit: int = 20) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT ts, street, hero, board, rivals, action, amount_bb, equity, ev_bb, reason "
                "FROM decisions ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def close(self) -> None:
        with self._lock:
            self._conn.close()
