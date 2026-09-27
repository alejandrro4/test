"""Recomendación instantánea desde la línea de comandos.

Ejemplos:
    python -m poker_bot.cli pre AsKd --pos CO
    python -m poker_bot.cli pre 7h7c --pos BB --opener BTN --size 2.5
    python -m poker_bot.cli pre AdJc --pos BB --opener BTN --size 40 --allin
    python -m poker_bot.cli post AhTh --board "Kh9h4c" --pot 5.5 --checked
    python -m poker_bot.cli post As5s --board "Qs9s2d" --pot 9.5 --call 4 --oop
"""

from __future__ import annotations

import argparse
import sys

from poker_bot.engine.decision import decide
from poker_bot.quick import postflop_state, preflop_state


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="poker_bot.cli", description="Mejor jugada al instante.")
    sub = ap.add_subparsers(dest="street", required=True)

    pre = sub.add_parser("pre", help="preflop")
    pre.add_argument("hand")
    pre.add_argument("--pos", required=True, help="tu posición: UTG, HJ, CO, BTN, SB, BB...")
    pre.add_argument("--players", type=int, default=6)
    pre.add_argument("--stack", type=float, default=100.0, help="stack en ciegas")
    pre.add_argument("--opener", help="posición del que ha subido")
    pre.add_argument("--size", type=float, default=2.5, help="tamaño de la subida en ciegas")
    pre.add_argument("--allin", action="store_true", help="la subida es un all-in")

    post = sub.add_parser("post", help="flop, turn o river")
    post.add_argument("hand")
    post.add_argument("--board", required=True)
    post.add_argument("--pot", type=float, required=True, help="bote total en ciegas (con la apuesta rival)")
    post.add_argument("--call", type=float, default=0.0, help="apuesta del rival a pagar")
    post.add_argument("--stack", type=float, default=100.0)
    post.add_argument("--vstack", type=float, help="stack del rival (por defecto igual al tuyo)")
    post.add_argument("--villains", type=int, default=1)
    post.add_argument("--oop", action="store_true", help="estás fuera de posición")
    post.add_argument("--vpre", default="call", choices=["call", "open", "3bet"],
                      help="qué hizo el rival preflop")
    post.add_argument("--checked", action="store_true", help="el rival ha pasado")
    for sp in (pre, post):
        sp.add_argument("--ms", type=float, default=1200, help="tiempo máximo de cálculo")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.street == "pre":
            state = preflop_state(args.hand, args.pos, args.players, args.stack,
                                  args.opener, args.size, args.allin)
        else:
            state = postflop_state(args.hand, args.board, args.pot, args.call, args.stack,
                                   args.vstack, args.villains, not args.oop, args.vpre, args.checked)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    d = decide(state, budget_ms=args.ms)
    print(d)
    if d.alternatives:
        print("Alternativas: " + " | ".join(
            f"{o.action.value} {o.amount:g}: {o.ev:+.2f}" for o in d.alternatives if o.ev is not None))
    print(f"({d.elapsed_ms:.0f} ms)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
