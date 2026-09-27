# Poker Bot (Texas Hold'em No Limit)

Asistente de póker en Python para partidas privadas con amigos, sin dinero.
**Mira tu mesa en la pantalla, sigue la mano y, cuando es tu turno, te dice al
instante qué hacer** (acción, cantidad, equity, EV y por qué) en una página
web que puedes tener en el PC o en el móvil. No hace clics: solo mira y recomienda.

> **Juego limpio:** tus amigos saben que usas el asistente. Aun así, ten en
> cuenta que algunas plataformas (PokerStars entre ellas) prohíben el software
> de ayuda en tiempo real incluso en mesas privadas o de fichas gratis, y
> pueden cerrar la cuenta aunque todos los jugadores estén de acuerdo.

## Cómo funciona

```
pantalla ──► captura (mss, 8/s) ──► lectura ──► seguimiento de la mano ──► cerebro ──► página web
             solo la zona          cartas,      quién subió, pagó,        preflop:     jugada + voz
             de la mesa            números,     se tiró; calle;           tablas;
                                   turno        tu turno                  postflop: EV
```

- **Lectura** (`vision/`): cartas por plantillas (el número) y color (el palo,
  baraja de 4 colores); cantidades por plantillas de dígitos que se aprenden
  solas con Tesseract; turno por el color de los botones; dealer y jugadores
  en la mano comparando con el tapete. Una mesa nueva se lee en unos 40 ms.
- **Seguimiento** (`vision/tracker.py`): espera a que la imagen esté estable
  (2 frames iguales) y deduce las acciones de cada rival comparando frames.
- **Seguridad:** si algo no se lee bien (una carta que aún no conoce, un número
  dudoso, el botón de dealer), **no recomienda** y te dice qué falla. Nunca
  trata un número ilegible como 0.

## Instalación

Requiere Python 3.10 o superior.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    ·    Mac/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
```

**Tesseract** (el OCR). En Windows, usa el instalador de UB Mannheim; si no
queda en el PATH, pasa su ruta con
`--tesseract "C:\Program Files\Tesseract-OCR\tesseract.exe"`. En Mac:
`brew install tesseract`.

**Evaluador de manos:** en Linux y Mac se instala `eval7` (rápido). En Windows
se usa `treys` (más lento: la decisión tarda en torno a 1 s en vez de 0,3 s).

### Ajustes recomendados en PokerStars

- **Baraja de 4 colores** (♠ negro, ♥ rojo, ♦ azul, ♣ verde): el palo se lee
  por el color, así que es casi imprescindible.
- **Mostrar cantidades en ciegas grandes**, si tu versión lo permite. Si no,
  indica el valor de la ciega grande al calibrar (`--bb`).
- No cambies el tamaño de la ventana de la mesa después de calibrar.

## Paso 1: calibrar (una vez)

Abre la mesa y espera a que sea **tu turno** (así se ven los botones). Después:

```bash
python -m poker_bot.capture.calibrate --seats 6 --in-bb     # la mesa muestra ciegas
python -m poker_bot.capture.calibrate --seats 6 --bb 20     # la mesa muestra fichas (ciega grande = 20)
```

A los 5 segundos hace una captura y te va pidiendo que marques zonas con el
ratón (arrastra un rectángulo y pulsa ENTER; con C saltas un paso):

1. Toda la mesa.
2. Tus dos cartas, la primera carta del flop y la del river (si aún no han
   salido, marca dónde aparecen).
3. El bote (**solo el número**), los botones de acción y un trozo de tapete vacío.
4. Cada asiento, **empezando por el tuyo y en el sentido de las agujas del
   reloj**: el número de su stack, dónde aparece su apuesta, dónde se ven sus
   cartas boca abajo y dónde aparece el botón de dealer cuando le toca.

Se guarda en `data/calibration.json` junto con `data/calibration_preview.png`,
una imagen con todas las zonas dibujadas para comprobarlas. Si mueves la
ventana, repite la calibración.

## Paso 2: jugar

```bash
python -m poker_bot.live            # abre http://127.0.0.1:8000
python -m poker_bot.live --lan      # y desde el móvil, en la misma wifi (la consola da la dirección)
```

La página muestra arriba la jugada en cuanto es tu turno: por ejemplo,
**SUBIR a 7.5 (7.5 BB)**, con la equity, el EV, el motivo y el EV de las
alternativas. Si la mesa muestra fichas, la cantidad sale en fichas, lista
para escribirla. Debajo, en **"Lo que veo"**, está todo lo que lee (cartas,
bote, stacks, apuestas y quién sigue en la mano), para que compruebes que
lee bien. Con **Voz** te lo dice en voz alta ("Sube a 3 ciegas").

**Las primeras manos:** cuando vea por primera vez el número de una carta
(A, K, Q…), aparece en la página **"Enséñame estos símbolos"**; tocas qué es y
ya lo reconoce siempre. Hacen falta los 13 números una sola vez. Los dígitos
de las cantidades los aprende solo con los stacks; si alguno se le resiste,
también te lo pregunta.

**Probar sin jugar:** guarda capturas de la mesa (pantalla completa o solo la
mesa) en una carpeta y reprodúcelas:

```bash
python -m poker_bot.live --replay capturas/ --fps 2
```

Opciones: `--fps` (capturas por segundo, 8 por defecto), `--ms` (tiempo máximo
de cálculo, 600 por defecto), `--port`, `--tesseract`, `--calibration`.

## Modo manual (sin leer la pantalla)

Si prefieres marcar tú la mano con clics, abre `http://127.0.0.1:8000/manual`
con el modo en vivo en marcha, o lanza solo la página manual:

```bash
python -m poker_bot.web.server
```

Y desde la terminal:

```bash
python -m poker_bot.cli pre AsKd --pos CO
python -m poker_bot.cli post As5s --board "Qs9s2d" --pot 9.5 --call 4 --oop
```

## Cómo piensa el bot

**Preflop.** Tablas de apertura según los jugadores que quedan detrás (sirven
para mesas de 2 a 10), tablas de 3-bet, pago, 4-bet y 5-bet con frecuencias
mixtas (A5s hace 3-bet la mitad de las veces), push/fold con 12 ciegas o menos,
y equity contra el rango del rival cuando pagar compromete el stack.

**Postflop.** Se estima el rango de cada rival (según lo que hizo preflop y
cómo se estrecha con cada apuesta, pago o pase) y se calcula el EV de cada
opción: pasar, pagar, tirar y 2 o 3 tamaños de apuesta o subida elegidos por
textura (c-bets pequeñas en boards secos, grandes en mojados, overbets en el
river) y SPR (all-in cuando lo que queda es poco).

- **Fold equity:** el rival defiende la frecuencia mínima de equilibrio (MDF)
  con la parte fuerte de su rango. Nunca tira doble pareja o mejor.
- **Bloqueadores:** el umbral de defensa se calcula sin nuestras cartas; si
  bloqueamos sus manos buenas, se tira más.
- **Faroles:** farolear sin proyecto contra un rival equilibrado vale EV ≈ 0,
  así que solo se hace cuando gana con margen. Los proyectos dan semi-faroles
  de forma natural.
- **Mezclas:** si dos opciones tienen casi el mismo EV, se alterna entre ellas
  para no ser predecible.
- **Rivales:** se asume un jugador típico de partida casera (algo suelto). No
  se guarda nada de nadie.

## Estructura

```
poker_bot/
├── core/            cartas y GameState (estado de la mano)
├── engine/          el cerebro: evaluador, rangos, equity Monte Carlo, preflop, postflop
├── vision/          calibración, cartas, números, lectura de la mesa, seguimiento de la mano
├── capture/         captura de pantalla (mss) y herramienta de calibración
├── web/             servidor local y páginas (en vivo y manual)
├── live.py          bucle del modo en vivo
├── quick.py, cli.py modo manual
data/                calibración y plantillas aprendidas (no se sube a git)
tests/               pytest (incluye una mesa sintética para probar la lectura)
```

## Tests

```bash
python -m pytest                        # todo (los de lectura necesitan Tesseract)
POKER_BOT_EVALUATOR=treys python -m pytest
```

`tests/synthetic.py` dibuja una mesa completa con OpenCV (cartas en 4 colores,
stacks, apuestas, botón de dealer y botones de acción) para probar la lectura
de punta a punta: las 52 cartas, los números, el dealer, el turno, el
seguimiento de la mano y la página en vivo.
