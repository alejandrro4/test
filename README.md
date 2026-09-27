# Poker Bot (Texas Hold'em No Limit)

Asistente de póker en Python para partidas privadas con amigos, sin dinero.
Lee la mesa desde la pantalla, calcula la mejor jugada y la muestra en un
overlay; más adelante podrá además ejecutarla con clics (modo automático).

> **Juego limpio:** tus amigos saben que usas el asistente. Aun así, ten en
> cuenta que algunas plataformas (PokerStars entre ellas) prohíben el software
> de ayuda en tiempo real incluso en mesas privadas o de fichas gratis, y
> pueden cerrar la cuenta aunque todos los jugadores estén de acuerdo.

## Estado del proyecto

| # | Módulo | Estado |
|---|--------|--------|
| 0 | Estructura, dependencias, `GameState` | ✅ hecho |
| 3a | Evaluador de manos + rangos + equity Monte Carlo | ✅ hecho y testeado |
| 1 | Captura (`mss`) + herramienta de calibración | ⏳ siguiente |
| 2 | Lectura de mesa (cartas por template matching, OCR de cantidades, detección de turno) | pendiente |
| 3b | Preflop (tablas de rangos por posición, push/fold, equity vs all-in) | ✅ hecho y testeado |
| 3c | Postflop (EV por acción, textura, tamaños, faroles, bloqueadores, SPR) | ✅ hecho y testeado |
| 3d | Modelado de rivales: estadísticas, estilo y ajustes explotativos | ✅ hecho (falta guardar en SQLite) |
| — | Modo rápido: recomendación al instante escribiendo la situación (`cli.py`) | ✅ hecho |
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
│   ├── ranges.py         # rangos "TT+, ATs+, KQo:0.5, top:20"
│   ├── equity.py         # Monte Carlo multiway contra rangos, con límite de tiempo
│   ├── board.py          # textura del board y proyectos (color, escalera)
│   ├── history.py        # interpreta las acciones: quién abrió, 3-bet, limpers...
│   ├── opponents.py      # estadísticas de rivales, estilo y ajustes explotativos
│   ├── villain_range.py  # rango estimado de cada rival y cómo se estrecha
│   ├── preflop_charts.py # tablas de apertura / 3-bet / 4-bet / defensa / push
│   ├── preflop.py        # decisión preflop
│   ├── postflop.py       # decisión postflop por EV
│   ├── decision_types.py # Decision y Option (salida del cerebro)
│   └── decision.py       # punto de entrada: decide(GameState) -> Decision
├── quick.py              # crea un GameState a partir de pocos datos
├── cli.py                # recomendación instantánea por línea de comandos
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

## Recomendación al instante (modo rápido)

Las cantidades van en ciegas grandes.

```bash
# Preflop: abrir, defender, pagar un all-in
python -m poker_bot.cli pre AsKd --pos CO
python -m poker_bot.cli pre 7h7c --pos BB --opener BTN --size 2.5
python -m poker_bot.cli pre AdJc --pos BB --opener BTN --size 40 --allin

# Postflop: el rival pasa / el rival apuesta 4 en un bote de 9.5 (con su apuesta)
python -m poker_bot.cli post AhTh --board "Kh9h4c" --pot 5.5 --checked
python -m poker_bot.cli post As5s --board "Qs9s2d" --pot 9.5 --call 4 --oop
```

Salida de ejemplo:

```
SUBIR a 10 (10 BB) · equity 50% · EV +4.6 BB
Semi-farol con carta alta + proyecto de color al nuts: subida a 10 en board medio,
dos colores. Se retiran ~50%; si pagan, equity 47%.
Alternativas: raise 10: +4.58 | raise 12.8: +4.49 | call 4: +1.96 | fold 0: +0.00
(171 ms)
```

Otras opciones: `--villains 3`, `--vpre open|call|3bet`, `--stack`, `--vstack`,
`--players`, `--ms` (tiempo máximo). `--help` para verlas todas.

## Cómo piensa el bot

**Preflop.** Tablas de apertura según los jugadores que quedan detrás (sirven
para mesas de 2 a 10), tablas de 3-bet, pago, 4-bet y 5-bet con frecuencias
mixtas (A5s hace 3-bet la mitad de las veces), push/fold con 12 ciegas o menos,
y equity contra el rango del rival cuando pagar compromete el stack. Hace menos
3-bets de farol contra quien paga todo, y roba más si los de detrás se tiran
mucho.

**Postflop.** Se estima el rango de cada rival (según lo que hizo preflop y
cómo se estrecha con cada apuesta, pago o pase) y se calcula el EV de cada
opción: pasar, pagar, tirar y 2 o 3 tamaños de apuesta o subida elegidos por
textura (c-bets pequeñas en boards secos, grandes en mojados, overbets en el
river) y SPR (all-in cuando lo que queda es poco).

- **Fold equity:** el rival defiende la frecuencia mínima de equilibrio (MDF),
  corregida por su perfil, con la parte fuerte de su rango. Nunca tira doble
  pareja o mejor.
- **Bloqueadores:** el umbral de defensa se calcula sin nuestras cartas; si
  bloqueamos sus manos buenas, se tira más.
- **Faroles:** contra un rival equilibrado, farolear sin proyecto vale EV ≈ 0,
  así que solo se hace cuando gana con margen (bloqueadores, rival que se tira
  mucho). Los proyectos dan semi-faroles de forma natural.
- **Mezclas:** si dos opciones tienen casi el mismo EV, se alterna entre ellas
  para no ser predecible.
- **Rivales:** contra una calling station no hay faroles y hay más apuestas de
  valor finas y overbets con nuts; contra quien se tira mucho, más faroles.

Tiempo de decisión: 0,2–0,3 s con `eval7` y unos 1–1,2 s con `treys`.

## Calibración

*(Se documentará con el módulo 1.)*
