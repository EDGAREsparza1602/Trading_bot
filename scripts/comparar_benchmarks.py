#!/usr/bin/env python3
"""
Calcula el retorno de comprar-y-mantener (buy-and-hold) de BTC solo, y de
una canasta equal-weight con todo el universo de pares, para el mismo
rango de fechas que se usó en un backtest. Se usa para completar la
comparación que pide CRITERIOS.md/DATOS.md junto al reporte de
`freqtrade backtesting` (que ya trae internamente el retorno de la
canasta equal-weight como "Market change", pero no el de BTC solo).

Uso (desde dentro del contenedor de freqtrade, que ya tiene pandas/pyarrow):

    docker compose run --rm --entrypoint python freqtrade \
        scripts/comparar_benchmarks.py \
        --config user_data/config.json \
        --start 2017-08-17 --end 2025-09-10
"""
import argparse
import json
from pathlib import Path

import rapidjson

from freqtrade.data.history.datahandlers import get_datahandler
from freqtrade.enums import CandleType


def cargar_config(path: str) -> dict:
    with open(path) as f:
        return rapidjson.load(f, parse_mode=rapidjson.PM_COMMENTS | rapidjson.PM_TRAILING_COMMAS)


def retorno_periodo(df, columna="close"):
    df = df.dropna(subset=[columna])
    if df.empty:
        return None
    inicio = df[columna].iloc[0]
    fin = df[columna].iloc[-1]
    return (fin - inicio) / inicio


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", required=True, help="Ruta a user_data/config.json")
    ap.add_argument("--start", required=True, help="Fecha inicio YYYY-MM-DD")
    ap.add_argument("--end", required=True, help="Fecha fin YYYY-MM-DD")
    ap.add_argument("--timeframe", default="1d", help="Timeframe a usar para el precio (default 1d)")
    args = ap.parse_args()

    cfg = cargar_config(args.config)
    pares = cfg["exchange"]["pair_whitelist"]
    datadir = Path(cfg.get("datadir", "user_data/data/binance"))
    if not datadir.is_absolute():
        # Asumimos que este script corre desde la raíz del repo (o del
        # contenedor, donde /freqtrade es la raíz también).
        datadir = Path("user_data/data/binance")

    dh = get_datahandler(datadir, "feather")

    import pandas as pd

    inicio = pd.Timestamp(args.start, tz="UTC")
    fin = pd.Timestamp(args.end, tz="UTC")

    retornos = {}
    for pair in pares:
        df = dh.ohlcv_load(pair, args.timeframe, CandleType.SPOT)
        if df.empty:
            print(f"AVISO: no hay datos para {pair} en {args.timeframe}, se omite.")
            continue
        df = df[(df["date"] >= inicio) & (df["date"] <= fin)]
        r = retorno_periodo(df)
        if r is None:
            print(f"AVISO: sin datos de {pair} en el rango {args.start} -> {args.end}, se omite.")
            continue
        retornos[pair] = r

    if not retornos:
        print("No se pudo calcular ningún retorno. Revisa que los datos estén descargados y el rango de fechas.")
        return

    print(f"\nPeríodo: {args.start} -> {args.end}  (timeframe usado para precios: {args.timeframe})\n")
    print(f"{'Par':<10} {'Retorno buy-and-hold':>22}")
    print("-" * 34)
    for pair, r in retornos.items():
        print(f"{pair:<10} {r:>21.2%}")

    if "BTC/USDT" in retornos:
        print(f"\n>>> Buy-and-hold BTC/USDT: {retornos['BTC/USDT']:.2%}")
    else:
        print("\nAVISO: no se pudo calcular el retorno de BTC/USDT (revisa que esté en pair_whitelist y tenga datos).")

    canasta_equal_weight = sum(retornos.values()) / len(retornos)
    print(f">>> Canasta equal-weight ({len(retornos)} pares): {canasta_equal_weight:.2%}")
    print("\n(Este número de la canasta debería coincidir, o quedar muy cerca, del")
    print(" 'Market change' que reporta 'freqtrade backtesting' para el mismo rango:")
    print(" freqtrade calcula esa métrica exactamente igual, como el promedio simple")
    print(" del retorno de cada par del universo.)")


if __name__ == "__main__":
    main()
