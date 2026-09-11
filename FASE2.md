# Fase 2 — Estrategia y backtest

Todos los comandos están en formato **PowerShell** (Windows), para correr
desde la carpeta del repo (`Trading_bot`). El backtick `` ` `` al final de
línea continúa el comando en la siguiente línea, igual que en Fase 1.

## 0. La estrategia

El código está en `user_data/strategies/TendenciaMomentumATR.py`, con
comentarios en español explicando cada parte. Resumen de la lógica:

- **Entrada:** la EMA rápida cruza hacia arriba de la EMA lenta (cruce
  alcista), el precio cierra por encima de la EMA lenta, y la
  volatilidad (ATR como % del precio) está por encima de un mínimo —
  este es el "filtro de volatilidad" que evita operar en mercados
  planos donde los cruces son ruido.
- **Salida normal:** cruce bajista de las mismas EMAs (fin de la
  tendencia).
- **Stop-loss:** fijado en el momento de entrar, a una distancia de
  `atr_stop_mult × ATR` por debajo del precio de entrada. No es un
  trailing stop — el precio de stop queda fijo durante toda la
  operación (estrategia simple, como acordamos).
- **Tamaño de cada operación:** se calcula para que, si se llega al
  stop-loss, la pérdida sea exactamente 1.5% del capital total (dentro
  del rango 1-2% que definiste).
- **Límite de pérdida diaria:** si la cuenta pierde ≥3% en un día UTC,
  se pausan nuevas entradas hasta el día siguiente (las posiciones ya
  abiertas no se tocan).
- **Kill switch:** si el drawdown total desde el máximo histórico de
  capital llega a ≥20%, se bloquean nuevas entradas Y se fuerza el
  cierre de todas las posiciones abiertas. Requiere reinicio manual del
  bot para desactivarse (a propósito: no queremos que se "auto-perdone"
  solo).
- Solo posiciones largas (Binance spot no permite cortos).
- Sin take-profit fijo: dejamos correr la tendencia.

Parámetros optimizables por hyperopt (máximo 4, como acordamos):
`ema_fast_len`, `ema_slow_len`, `min_atr_pct`, `atr_stop_mult`. El
riesgo por operación (1.5%), el límite de pérdida diaria (3%) y el
kill switch (20%) son fijos — **no** se optimizan, para que el
optimizador no "descubra" que arriesgar más da mejores números
históricos.

**Cómo la validé sin poder correr un backtest real aquí** (este sandbox
no tiene red hacia Binance): verifiqué cada método contra el código
fuente real de freqtrade instalado (`custom_stoploss`,
`custom_stake_amount`, `bot_loop_start`, etc. — firmas exactas), confirmé
que la estrategia carga sin errores con `freqtrade list-strategies`, y
corrí pruebas unitarias con datos sintéticos que confirmaron: los
indicadores no generan NaN después del calentamiento, las señales de
entrada/salida se generan correctamente y respetan el filtro de
volatilidad, el stop-loss queda fijo (no se mueve como un trailing), el
tamaño de posición calcula el riesgo correctamente, y el kill
switch/pausa diaria se activan y resetean como se espera. Lo que NO pude
probar aquí es la integración completa con datos reales de Binance —
eso lo vamos a ver juntos en tu primera corrida real.

## 1. Backtest inicial (parámetros por defecto, datos NO reservados)

Rango: desde el inicio de los datos hasta el día antes de la ventana
reservada (`DATOS.md`: reservado = 2025-09-11 en adelante).

```powershell
docker compose run --rm freqtrade backtesting `
    --config user_data/config.json `
    --strategy TendenciaMomentumATR `
    --timeframe 4h `
    --timerange 20170101-20250911 `
    --fee 0.001 `
    --dry-run-wallet 10000 `
    --breakdown month
```

Pégame la tabla de resultados completa que imprime al final (retorno
total, Sharpe, Sortino, Calmar, drawdown máximo, win rate, profit
factor, número de operaciones, "Market change").

## 2. Chequeo de sesgos: lookahead-analysis

Busca si la estrategia está usando sin querer información del futuro
(look-ahead bias) — por ejemplo, un indicador mal calculado que "ve"
datos de velas que en la vida real todavía no existían.

```powershell
docker compose run --rm freqtrade lookahead-analysis `
    --config user_data/config.json `
    --config user_data/config-lookahead.json `
    --strategy TendenciaMomentumATR `
    --timerange 20170101-20250911 `
    --allow-limit-orders
```

Nota sobre este comando (por si te preguntas por qué tiene dos `--config`):
`lookahead-analysis` fuerza internamente órdenes de mercado, lo que choca
con nuestro `entry_pricing.price_side = "same"` (pensado para órdenes
límite, la configuración real de dry-run/live). En teoría el flag
`--allow-limit-orders` evita ese forzado, pero es un bug conocido de esta
versión de freqtrade: el flag existe en la CLI pero nunca llega a
aplicarse al config real, así que no funciona (lo dejamos igual por si
una versión futura lo arregla). El segundo `--config
user_data/config-lookahead.json` es nuestro workaround: pisa solo
`entry_pricing.price_side`/`exit_pricing.price_side` a `"other"` (lo que
exige freqtrade para órdenes de mercado), sin tocar nada más de la
configuración real — ese archivo solo se usa para este comando.

Si reporta algún hallazgo, pégamelo — puede requerir ajustar el código
antes de seguir.

## 3. Chequeo de sesgos: recursive-analysis

Busca problemas donde un indicador da resultados distintos según cuántas
velas históricas tenga disponibles al momento de calcularlo (lo cual
generaría resultados de backtest poco confiables).

```powershell
docker compose run --rm freqtrade recursive-analysis `
    --config user_data/config.json `
    --strategy TendenciaMomentumATR `
    --timerange 20170101-20250911
```

## 4. Hyperopt (máximo 4 parámetros, 100 configuraciones)

Optimiza los 4 parámetros usando `SharpeHyperOptLossDaily` — Sharpe
calculado sobre retornos diarios y anualizado con 365 días, exactamente
el mismo método que usamos en `CRITERIOS.md` para el criterio de éxito
(así el optimizador busca directamente lo que nos importa, no solo
retorno bruto).

```powershell
docker compose run --rm freqtrade hyperopt `
    --config user_data/config.json `
    --strategy TendenciaMomentumATR `
    --hyperopt-loss SharpeHyperOptLossDaily `
    --spaces buy sell `
    --epochs 100 `
    --timerange 20170101-20250911 `
    --fee 0.001 `
    --dry-run-wallet 10000
```

**Importante sobre el número de configuraciones:** `--epochs 100`
significa que se probaron 100 combinaciones de parámetros (no es fuerza
bruta exhaustiva, usa un optimizador bayesiano que va acotando la
búsqueda). Ese es el número que hay que reportar — 100 configuraciones
probadas sobre ~8 años de datos es razonable para 4 parámetros, pero
quiero que lo tengas presente: con pocas operaciones históricas, cuantas
más configuraciones se prueban, más fácil es que el mejor resultado sea
suerte estadística y no una ventaja real. Por eso no vamos a aumentar
mucho los epochs "a ver si sale algo mejor".

Al terminar, freqtrade guarda automáticamente los mejores parámetros en
`user_data/strategies/TendenciaMomentumATR.json` — ese archivo se aplica
solo la próxima vez que corras backtesting con esta estrategia, sin
tocar el código. Pégame la tabla resumen que imprime hyperopt al final
(mejor resultado, y algunos parámetros probados).

## 5. Backtest con los parámetros optimizados (mismo rango, datos NO reservados)

Mismo comando que el paso 1 — como el archivo `TendenciaMomentumATR.json`
ya existe, freqtrade usa automáticamente los parámetros optimizados:

```powershell
docker compose run --rm freqtrade backtesting `
    --config user_data/config.json `
    --strategy TendenciaMomentumATR `
    --timeframe 4h `
    --timerange 20170101-20250911 `
    --fee 0.001 `
    --dry-run-wallet 10000 `
    --breakdown month
```

Pégame esta tabla también, para comparar contra el paso 1.

## 6. Comparación contra buy-and-hold BTC y canasta equal-weight

`freqtrade backtesting` ya te da la canasta equal-weight como "Market
change" en la tabla de resultados (es exactamente el promedio del
retorno de cada par del universo en el período). Para el buy-and-hold de
BTC solo, corre:

```powershell
docker compose run --rm --entrypoint python freqtrade `
    scripts/comparar_benchmarks.py `
    --config user_data/config.json `
    --start 2017-08-17 --end 2025-09-10
```

(Ajusta `--start` si tu `list-data` de Fase 1 mostró una fecha de inicio
distinta para BTC/USDT.)

## 7. Validación final: UNA sola corrida sobre los datos reservados

**Solo se corre una vez.** Es la ventana 2025-09-11 → hoy que separamos
en `DATOS.md` y que no tocamos hasta ahora.

```powershell
docker compose run --rm freqtrade backtesting `
    --config user_data/config.json `
    --strategy TendenciaMomentumATR `
    --timeframe 4h `
    --timerange 20250911- `
    --fee 0.001 `
    --dry-run-wallet 10000 `
    --breakdown month

docker compose run --rm --entrypoint python freqtrade `
    scripts/comparar_benchmarks.py `
    --config user_data/config.json `
    --start 2025-09-11 --end 2026-09-11
```

Pégame ambas salidas. Con esto arme el reporte final de Fase 2: retorno
neto, Sharpe, Sortino, drawdown máximo, win rate, profit factor, número
de operaciones, comparado contra buy-and-hold BTC y la canasta
equal-weight — y te doy mi opinión honesta sobre si esto justifica pasar
a Fase 3 (dry-run piloto) o no.

## Orden de ejecución (resumen)

1. Backtest inicial (parámetros por defecto)
2. lookahead-analysis
3. recursive-analysis
4. hyperopt (100 epochs, 4 parámetros)
5. Backtest con parámetros optimizados
6. Comparación contra BTC buy-and-hold
7. Validación única sobre datos reservados

Ve pegándome los resultados de cada paso — no hace falta que corras
todo antes de mostrarme nada; si algo falla o da un resultado raro en el
paso 1, mejor lo resolvemos antes de gastar tiempo en hyperopt.
