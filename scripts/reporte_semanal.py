#!/usr/bin/env python3
"""
Genera un reporte HTML con las métricas de CRITERIOS.md a partir de la
base de datos de trades del dry-run en curso, comparado contra
buy-and-hold de BTC y la canasta equal-weight del universo.

Pensado para correr semanalmente durante Fase 3, por ejemplo:

    docker compose run --rm --entrypoint python freqtrade \
        scripts/reporte_semanal.py \
        --config user_data/config.json \
        --db-url sqlite:////freqtrade/user_data/tradesv3.dryrun.sqlite \
        --inicio-piloto 2026-09-15 \
        --salida user_data/reportes/reporte_2026-09-22.html

--inicio-piloto marca cuándo empezó el mes piloto (que no cuenta para la
evaluación de éxito/fracaso, según CRITERIOS.md) — el reporte marca
claramente si todavía estás en el piloto o ya en la ventana de
evaluación real (piloto + 3 meses).
"""
import argparse
import html
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import rapidjson

from freqtrade.data.history.datahandlers import get_datahandler
from freqtrade.enums import CandleType
from freqtrade.persistence import Trade, init_db


def cargar_config(path: str) -> dict:
    with open(path) as f:
        return rapidjson.load(f, parse_mode=rapidjson.PM_COMMENTS | rapidjson.PM_TRAILING_COMMAS)


def retorno_periodo(df, columna="close"):
    df = df.dropna(subset=[columna])
    if df.empty:
        return None
    return (df[columna].iloc[-1] - df[columna].iloc[0]) / df[columna].iloc[0]


def calcular_benchmarks(cfg: dict, inicio: pd.Timestamp, fin: pd.Timestamp):
    pares = cfg["exchange"]["pair_whitelist"]
    datadir = Path("user_data/data/binance")
    dh = get_datahandler(datadir, "feather")

    retornos = {}
    for pair in pares:
        df = dh.ohlcv_load(pair, "1d", CandleType.SPOT)
        if df.empty:
            continue
        df = df[(df["date"] >= inicio) & (df["date"] <= fin)]
        r = retorno_periodo(df)
        if r is not None:
            retornos[pair] = r

    btc = retornos.get("BTC/USDT")
    canasta = sum(retornos.values()) / len(retornos) if retornos else None
    return btc, canasta


def sharpe_sortino_diarios(cierres: pd.DataFrame, dias_totales: int):
    """
    Calcula Sharpe y Sortino anualizados (365 días), sobre retornos
    diarios agregados a partir del profit_ratio de cada operación
    cerrada en su fecha de cierre. Mismo método que usamos en Fase 2
    (SharpeHyperOptLossDaily), para que el número sea comparable.
    """
    if cierres.empty or dias_totales < 2:
        return None, None

    diario = cierres.set_index("close_date")["profit_ratio"].resample("1D").sum()
    media = diario.mean()
    desvio = diario.std()
    downside = diario[diario < 0].std()

    dias_en_anio = 365
    sharpe = (media / desvio) * math.sqrt(dias_en_anio) if desvio and desvio > 0 else None
    sortino = (media / downside) * math.sqrt(dias_en_anio) if downside and downside > 0 else None
    return sharpe, sortino


def max_drawdown(curva_equity: pd.Series):
    if curva_equity.empty:
        return 0.0
    pico = curva_equity.cummax()
    caida = (curva_equity - pico) / pico
    return abs(caida.min())


def generar_svg_equity(fechas, valores, ancho=700, alto=220):
    if len(valores) < 2:
        return "<p>No hay suficientes datos todavía para graficar la curva de capital.</p>"

    minimo, maximo = min(valores), max(valores)
    rango = (maximo - minimo) or 1
    n = len(valores)
    puntos = []
    for i, v in enumerate(valores):
        x = 40 + (i / (n - 1)) * (ancho - 60)
        y = (alto - 30) - ((v - minimo) / rango) * (alto - 60)
        puntos.append(f"{x:.1f},{y:.1f}")
    polyline = " ".join(puntos)

    linea_inicial_y = (alto - 30) - ((valores[0] - minimo) / rango) * (alto - 60)

    return f"""
    <svg viewBox="0 0 {ancho} {alto}" width="100%" style="max-width:{ancho}px">
        <line x1="40" y1="{linea_inicial_y:.1f}" x2="{ancho - 20}" y2="{linea_inicial_y:.1f}"
              stroke="#94a3b8" stroke-dasharray="4,4" stroke-width="1"/>
        <polyline points="{polyline}" fill="none" stroke="#2563eb" stroke-width="2"/>
        <text x="40" y="16" font-size="12" fill="#334155">{maximo:,.0f} USDT</text>
        <text x="40" y="{alto - 8}" font-size="12" fill="#334155">{minimo:,.0f} USDT</text>
    </svg>
    """


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", required=True)
    ap.add_argument("--db-url", required=True)
    ap.add_argument("--inicio-piloto", required=True, help="Fecha YYYY-MM-DD de inicio del mes piloto")
    ap.add_argument("--salida", required=True, help="Ruta del archivo HTML a generar")
    args = ap.parse_args()

    cfg = cargar_config(args.config)
    init_db(args.db_url)

    inicio_piloto = pd.Timestamp(args.inicio_piloto, tz="UTC")
    fin_piloto = inicio_piloto + pd.Timedelta(days=30)
    ahora = pd.Timestamp.now(tz="UTC")
    en_piloto = ahora < fin_piloto

    todos = Trade.get_trades().all()
    cerrados = [t for t in todos if not t.is_open]
    abiertos = [t for t in todos if t.is_open]

    filas = []
    for t in cerrados:
        filas.append(
            {
                "pair": t.pair,
                "open_date": t.open_date_utc,
                "close_date": t.close_date_utc,
                "open_rate": t.open_rate,
                "close_rate": t.close_rate,
                "stake_amount": t.stake_amount,
                "enter_tag": t.enter_tag,
                "exit_reason": t.exit_reason,
                "profit_ratio": t.close_profit or 0.0,
                "profit_abs": t.close_profit_abs or 0.0,
            }
        )
    df_cerrados = pd.DataFrame(filas)

    # Solo operaciones cerradas DESPUÉS del piloto cuentan para la
    # evaluación de éxito/fracaso, según CRITERIOS.md.
    if not df_cerrados.empty:
        df_evaluacion = df_cerrados[df_cerrados["close_date"] >= fin_piloto]
    else:
        df_evaluacion = df_cerrados

    n_trades_totales = len(df_cerrados)
    n_trades_evaluacion = len(df_evaluacion)

    capital_inicial = cfg.get("dry_run_wallet", 10000)
    if not df_cerrados.empty:
        df_cerrados = df_cerrados.sort_values("close_date")
        df_cerrados["equity"] = capital_inicial + df_cerrados["profit_abs"].cumsum()
        equity_actual = df_cerrados["equity"].iloc[-1]
    else:
        equity_actual = capital_inicial

    retorno_total_pct = (equity_actual - capital_inicial) / capital_inicial

    ganadoras = (df_evaluacion["profit_ratio"] > 0).sum() if not df_evaluacion.empty else 0
    perdedoras = (df_evaluacion["profit_ratio"] <= 0).sum() if not df_evaluacion.empty else 0
    win_rate = ganadoras / n_trades_evaluacion if n_trades_evaluacion else None

    ganancia_bruta = df_evaluacion.loc[df_evaluacion["profit_abs"] > 0, "profit_abs"].sum() if not df_evaluacion.empty else 0
    perdida_bruta = -df_evaluacion.loc[df_evaluacion["profit_abs"] <= 0, "profit_abs"].sum() if not df_evaluacion.empty else 0
    profit_factor = (ganancia_bruta / perdida_bruta) if perdida_bruta > 0 else None

    dias_desde_inicio = (ahora - inicio_piloto).days
    sharpe, sortino = sharpe_sortino_diarios(df_evaluacion, dias_desde_inicio) if not df_evaluacion.empty else (None, None)

    dd = max_drawdown(df_cerrados["equity"]) if not df_cerrados.empty else 0.0

    btc_ret, canasta_ret = calcular_benchmarks(cfg, inicio_piloto, ahora)

    kill_switch_disparado = (df_cerrados["exit_reason"] == "kill_switch_drawdown_20pct").any() if not df_cerrados.empty else False

    svg_equity = generar_svg_equity(
        df_cerrados["close_date"].tolist() if not df_cerrados.empty else [],
        df_cerrados["equity"].tolist() if not df_cerrados.empty else [],
    )

    def fmt_pct(x):
        """Para valores que pueden ser + o - (retornos): siempre muestra el signo."""
        return f"{x:+.2%}" if x is not None else "—"

    def fmt_pct_mag(x):
        """Para magnitudes que nunca son negativas (win rate, drawdown): sin signo +."""
        return f"{x:.2%}" if x is not None else "—"

    def fmt_num(x, decimales=2):
        return f"{x:.{decimales}f}" if x is not None else "—"

    filas_tabla = ""
    for _, r in df_cerrados.sort_values("close_date", ascending=False).head(50).iterrows():
        color = "#16a34a" if r["profit_ratio"] > 0 else "#dc2626"
        filas_tabla += f"""
        <tr>
            <td>{r['close_date'].strftime('%Y-%m-%d %H:%M')}</td>
            <td>{html.escape(str(r['pair']))}</td>
            <td>{r['open_rate']:.4f}</td>
            <td>{r['close_rate']:.4f}</td>
            <td>{r['stake_amount']:.2f} USDT</td>
            <td>{html.escape(str(r['enter_tag'] or '-'))}</td>
            <td>{html.escape(str(r['exit_reason'] or '-'))}</td>
            <td style="color:{color}">{fmt_pct(r['profit_ratio'])}</td>
        </tr>
        """

    estado_piloto = (
        f'<span style="background:#fef3c7;color:#92400e;padding:2px 8px;border-radius:4px;">'
        f"En mes piloto (termina {fin_piloto.date()}) — estas operaciones NO cuentan para "
        f"la evaluación final</span>"
        if en_piloto
        else f'<span style="background:#dcfce7;color:#166534;padding:2px 8px;border-radius:4px;">'
        f"Piloto terminado — evaluando desde {fin_piloto.date()}</span>"
    )

    alerta_kill_switch = (
        '<div style="background:#fee2e2;border:1px solid #fca5a5;color:#991b1b;padding:12px;'
        'border-radius:8px;margin-bottom:16px;">🛑 El kill switch se disparó en algún momento '
        "de este período. Revisá los mensajes de Telegram para ver cuándo y por qué.</div>"
        if kill_switch_disparado
        else ""
    )

    html_final = f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>Reporte semanal — {ahora.date()}</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, Arial, sans-serif; background:#f8fafc; color:#1e293b; margin:0; padding:24px; }}
  .contenedor {{ max-width: 900px; margin: 0 auto; }}
  h1 {{ font-size: 22px; }}
  h2 {{ font-size: 16px; color:#475569; margin-top:32px; }}
  .kpis {{ display:grid; grid-template-columns: repeat(auto-fit, minmax(150px,1fr)); gap:12px; margin:16px 0; }}
  .kpi {{ background:white; border:1px solid #e2e8f0; border-radius:8px; padding:12px; }}
  .kpi .label {{ font-size:12px; color:#64748b; }}
  .kpi .valor {{ font-size:20px; font-weight:600; margin-top:4px; }}
  table {{ width:100%; border-collapse: collapse; background:white; font-size:13px; }}
  th, td {{ padding:6px 8px; border-bottom:1px solid #e2e8f0; text-align:left; }}
  th {{ background:#f1f5f9; }}
  .comparacion td, .comparacion th {{ text-align:right; }}
  .comparacion td:first-child, .comparacion th:first-child {{ text-align:left; }}
</style>
</head>
<body>
<div class="contenedor">
  <h1>Reporte semanal — dry-run TendenciaMomentumATR</h1>
  <p>Generado: {ahora.strftime('%Y-%m-%d %H:%M UTC')} — {estado_piloto}</p>
  {alerta_kill_switch}

  <div class="kpis">
    <div class="kpi"><div class="label">Capital actual</div><div class="valor">{equity_actual:,.2f} USDT</div></div>
    <div class="kpi"><div class="label">Retorno total</div><div class="valor">{fmt_pct(retorno_total_pct)}</div></div>
    <div class="kpi"><div class="label">Operaciones (evaluación)</div><div class="valor">{n_trades_evaluacion}</div></div>
    <div class="kpi"><div class="label">Win rate</div><div class="valor">{fmt_pct_mag(win_rate)}</div></div>
    <div class="kpi"><div class="label">Profit factor</div><div class="valor">{fmt_num(profit_factor)}</div></div>
    <div class="kpi"><div class="label">Sharpe (365d)</div><div class="valor">{fmt_num(sharpe)}</div></div>
    <div class="kpi"><div class="label">Sortino (365d)</div><div class="valor">{fmt_num(sortino)}</div></div>
    <div class="kpi"><div class="label">Drawdown máximo</div><div class="valor">{fmt_pct_mag(dd)}</div></div>
  </div>

  <h2>Curva de capital</h2>
  {svg_equity}

  <h2>Comparación contra CRITERIOS.md</h2>
  <table class="comparacion">
    <tr><th>Métrica</th><th>Estrategia</th><th>Umbral</th><th>¿Pasa?</th></tr>
    <tr><td>Retorno vs buy-and-hold BTC</td><td>{fmt_pct(retorno_total_pct)}</td><td>≥ {fmt_pct(btc_ret) if btc_ret is not None else '—'}</td>
        <td>{'✅' if (btc_ret is not None and retorno_total_pct >= btc_ret) else '❌'}</td></tr>
    <tr><td>Sharpe</td><td>{fmt_num(sharpe)}</td><td>&gt; 1</td>
        <td>{'✅' if (sharpe is not None and sharpe > 1) else '❌'}</td></tr>
    <tr><td>Drawdown máximo</td><td>{fmt_pct_mag(dd)}</td><td>≤ 20%</td>
        <td>{'✅' if dd <= 0.20 else '❌'}</td></tr>
    <tr><td>Operaciones cerradas (evaluación)</td><td>{n_trades_evaluacion}</td><td>≥ 50</td>
        <td>{'✅' if n_trades_evaluacion >= 50 else '❌'}</td></tr>
    <tr><td>Kill switch disparado</td><td colspan="2">{'Sí' if kill_switch_disparado else 'No'}</td>
        <td>{'❌' if kill_switch_disparado else '✅'}</td></tr>
  </table>
  <p style="font-size:12px;color:#64748b;">Canasta equal-weight del universo en el mismo período: {fmt_pct(canasta_ret) if canasta_ret is not None else '—'} (informativo, no es el criterio de éxito).</p>

  <h2>Operaciones recientes (últimas 50 cerradas)</h2>
  <p style="font-size:12px;color:#64748b;">Incluye operaciones del mes piloto (que no cuentan para las métricas de evaluación de arriba) — es el log completo de cada operación simulada.</p>
  <table>
    <tr><th>Cierre</th><th>Par</th><th>Precio entrada</th><th>Precio salida</th><th>Tamaño</th><th>Motivo entrada</th><th>Motivo salida</th><th>Resultado</th></tr>
    {filas_tabla if filas_tabla else '<tr><td colspan="8">Todavía no hay operaciones cerradas.</td></tr>'}
  </table>

  <p style="font-size:12px;color:#64748b;margin-top:24px;">
    Operaciones abiertas en este momento: {len(abiertos)}. Este reporte se genera desde
    la base de datos local del bot ({args.db_url}), no requiere red externa salvo para
    leer los precios de BTC de comparación (ya descargados localmente).
  </p>
</div>
</body>
</html>
"""

    salida = Path(args.salida)
    salida.parent.mkdir(parents=True, exist_ok=True)
    salida.write_text(html_final, encoding="utf-8")
    print(f"Reporte generado en: {salida}")


if __name__ == "__main__":
    main()
