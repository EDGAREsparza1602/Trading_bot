# Especificación de datos — Fase 1

Fijado el 2026-09-11, antes de correr ningún backtest. No se cambia
después de ver resultados (igual que `CRITERIOS.md`).

## Universo (6 pares, todos contra USDT, Binance spot)

| Par | Motivo |
|-----|--------|
| BTC/USDT | Activo de referencia (benchmark buy-and-hold). |
| ETH/USDT | Segunda mayor capitalización, alta liquidez, historial largo. |
| BNB/USDT | Token del propio exchange, liquidez muy alta, historial desde 2017. |
| LTC/USDT | Una de las altcoins más antiguas, comportamiento "beta de BTC" con poco ruido idiosincrático. |
| ADA/USDT | Alta capitalización, liquidez alta, historial desde 2018 (cubre el ciclo bajista de 2018). |
| XRP/USDT | Muy alta liquidez y capitalización. **Aviso:** tiene eventos idiosincráticos grandes (litigio con la SEC en EE.UU., 2020-2023) que provocan saltos de precio que no vienen de tendencia/momentum técnico — puede meter ruido a la estrategia. Se incluye porque así lo decidiste; lo vamos a vigilar en los resultados del backtest de Fase 2. |

## Timeframes

Se descargan **1d y 4h** para tener flexibilidad al escribir la
estrategia en Fase 2:

- **4h**: más señales, más fácil llegar a ≥50 operaciones cerradas en
  3 meses de dry-run (criterio de `CRITERIOS.md`) con una estrategia
  simple sobre 6 pares.
- **1d**: menos ruido intradía, útil como comparación y para el cálculo
  limpio de buy-and-hold.

La decisión final de qué timeframe usa la estrategia en vivo se toma en
Fase 2, con datos ya descargados en ambos.

## Rango de fechas y ventana reservada ("datos sagrados")

- Descarga: **2017-01-01 hasta hoy**, continua, sin huecos. Cada par
  trae la historia que exista desde que se listó en Binance (ADA y XRP
  no tendrán velas de 2017).
- Esto cubre: mercado bajista 2018, lateral 2019, alcista 2020-2021,
  bajista 2022 (Luna/FTX), y la recuperación/alcista 2023-2026.
- **Ventana reservada (holdout) para validación final:**
  **2025-09-11 → hoy** (últimos 12 meses exactos desde la fecha de este
  documento). Estos datos **no se tocan** durante el desarrollo de la
  estrategia, el backtest inicial, el lookahead/recursive-analysis ni el
  hyperopt de Fase 2. Solo se usan una vez, al final de Fase 2, para la
  corrida única de validación.
- Datos de entrenamiento/backtest de Fase 2: **todo lo anterior a
  2025-09-11**.

## Comisiones

- **0.1% por lado** (spot, Binance), fijado en `user_data/config.json`
  como `"fee": 0.001`, y se pasará explícitamente con `--fee 0.001` en
  los comandos de backtesting de Fase 2 para no depender de lo que
  devuelva la API pública.

## Fuente y método de descarga

- `freqtrade download-data` contra la API pública de Binance (no
  requiere API key). Ver `scripts/download_data.sh`.
- **Nota de esta sesión:** el sandbox donde se preparó este proyecto no
  tiene salida de red hacia Binance (bloqueado por política del
  entorno), así que la descarga real debe ejecutarse en tu máquina o
  servidor, donde sí hay red abierta. Ver `SETUP.md`.
