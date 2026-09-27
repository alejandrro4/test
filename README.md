# Poker Bot (Texas Hold'em No Limit)

Asistente de póker en Python para partidas privadas con amigos, sin dinero.
Lee la mesa desde la pantalla, calcula la mejor jugada y la muestra en un
overlay; más adelante podrá además ejecutarla con clics (modo automático).

> **Juego limpio:** avisa a tus amigos de que usas el asistente, y revisa las
> condiciones de uso de la plataforma: muchas prohíben el software de ayuda en
> tiempo real y los bots, incluso en mesas privadas o de fichas gratis, y
> pueden cerrarte la cuenta.

## Estado del proyecto

| # | Módulo | Estado |
|---|--------|--------|
| 0 | Estructura, dependencias, `GameState` | ✅ hecho |
| 3a | Evaluador de manos + rangos + equity Monte Carlo | ✅ hecho y testeado |
| 1 | Captura (`mss`) + herramienta de calibración | ⏳ siguiente |
| 2 | Lectura de mesa (cartas por template matching, OCR de cantidades, detección de turno) | pendiente |
| 3b | Preflop (tablas de rangos por posición) | pendiente |
| 3c | Postflop (EV por acción, textura, tamaños, faroles, SPR) | pendiente |
| 3d | Modelado de rivales (SQLite: VPIP, PFR, AF, fold a c-bet...) | pendiente |
| 4 | Modo asistente: overlay PyQt + voz | pendiente |
| 5 | Modo automático: clics con verificación por OCR | pendiente |
| 6 | Seguridad: F12 de pánico, FAILSAFE, degradar a asistente, log de manos | pendiente |
| 7 | Resumen de sesión ("víctima favorita", mejor farol...) | pendiente |

## Estructura de carpetas

Las carpetas marcadas con `*` todavía no existen: se crean al llegar a su módulo.

```
poker_bot/
├── core/
│   ├── cards.py          # cartas como strings canónicos ("As", "Td"), parseo
│   └── game_state.py     # GameState, PlayerState, Street, Action, posiciones
├── engine/               # cerebro
│   ├── evaluator.py      # fuerza de mano (eval7, con respaldo treys)
│   ├── ranges.py         # rangos "TT+, ATs+, KQo:0.5", top X%
│   ├── equity.py         # Monte Carlo multiway contra rangos, con límite de tiempo
│   ├── preflop.py *      # tablas de apertura / 3-bet / 4-bet / defensa
│   ├── postflop.py *     # EV por acción, textura, sizing, SPR
│   └── opponents.py *    # estadísticas y ajustes explotativos
├── capture/ *            # mss + calibración (genera data/calibration.json)
├── vision/ *             # template matching de cartas, OCR, detección de turno
├── ui/ *                 # overlay y voz
├── automation/ *         # pyautogui + verificación
├── stats/ *              # SQLite, log de manos, resumen de sesión
└── main.py *             # bucle principal
data/ *                   # calibración, plantillas de cartas, base de datos (no se sube a git)
tests/                    # pytest, un fichero por módulo
```

## Instalación

Requiere Python 3.10 o superior.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    ·    Mac/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
```

- **Evaluador:** en Linux y Mac se instala `eval7` (C, rápido). En Windows se
  usa `treys` (Python puro), porque `eval7` no siempre tiene paquete
  precompilado. Si tienes compilador de C, puedes probar `pip install eval7`.
  El código elige solo el que esté disponible.
- **Tesseract** (para el módulo 2): en Windows, el instalador de UB Mannheim;
  en Mac, `brew install tesseract`.

## Tests

```bash
pytest                                  # todo
pytest tests/test_equity.py -v          # solo equity
POKER_BOT_EVALUATOR=treys pytest        # forzar el evaluador de respaldo
```

Los tests de equity comparan con valores de referencia (AA contra una mano
aleatoria ≈ 85,2 %, AKs contra QQ ≈ 46 %, proyecto de color contra un set
≈ 25,6 %...), comprueban que se respeta el tiempo máximo y que en el river
el resultado es exacto.

## Uso del motor de equity

```python
from poker_bot.core.cards import parse_cards
from poker_bot.engine.equity import calculate_equity
from poker_bot.engine.ranges import Range

r = calculate_equity(
    hero=parse_cards("AhKh"),
    board=parse_cards("Qh Jh 2c"),
    villain_ranges=[Range.parse("TT+, AQ+"), Range.top_percent(35)],  # un rango por rival
    iterations=10_000,
    time_budget_ms=300,
)
print(f"{r.equity:.1%} ({r.iterations} sims en {r.elapsed_ms:.0f} ms)")
```

Rendimiento medido: con `eval7`, 10 000 simulaciones heads-up tardan unos
50–60 ms y contra 3 rivales unos 120 ms. Con `treys`, unas 10 000 heads-up
caben en unos 280 ms; si no caben, el cálculo se corta al llegar al límite de
tiempo y devuelve lo que lleve.

## Calibración

*(Se documentará con el módulo 1.)*
