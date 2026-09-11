# -*- coding: utf-8 -*-
"""
TendenciaMomentumATR
=====================

Estrategia de seguimiento de tendencia/momentum con filtro de volatilidad,
para el experimento de dry-run descrito en CRITERIOS.md y DATOS.md.

IDEA GENERAL (en palabras simples)
-----------------------------------
1. Miramos dos medias móviles exponenciales (EMA): una "rápida" y una
   "lenta". Cuando la rápida cruza hacia arriba de la lenta, es una señal
   de que el precio empezó una tendencia alcista -> compramos.
   Cuando la rápida cruza hacia abajo de la lenta, la tendencia se dio
   vuelta -> vendemos (cerramos la posición).
2. Para no operar en mercados demasiado "planos" (donde los cruces de
   medias son puro ruido), exigimos que la volatilidad reciente (medida
   con el ATR, Average True Range) esté por encima de un mínimo. Ese es
   el "filtro de volatilidad".
3. El tamaño de cada operación y el stop-loss NO son un porcentaje fijo
   arbitrario: se calculan a partir del ATR, de forma que si el precio
   se mueve en contra hasta el stop, la pérdida sea exactamente el
   1-2% del capital total (gestión de riesgo "position sizing por ATR").
4. Además hay tres mecanismos de seguridad que no dependen de indicadores
   técnicos, sino que vigilan la cuenta completa: límite de pérdida
   diaria, kill switch por drawdown total, y un stop duro de emergencia.

Solo posiciones largas (long): operamos en Binance SPOT, que no permite
posiciones cortas nativas. can_short queda en False.

No hay take-profit fijo: dejamos correr la tendencia y solo salimos por
señal de cruce bajista, por el stop-loss basado en ATR, o por el kill
switch. Por eso minimal_roi está prácticamente desactivado (ver abajo).
"""

import logging
from datetime import datetime

from pandas import DataFrame
import talib.abstract as ta

from freqtrade.persistence import Trade
from freqtrade.strategy import DecimalParameter, IntParameter, IStrategy


logger = logging.getLogger(__name__)


class TendenciaMomentumATR(IStrategy):
    INTERFACE_VERSION = 3

    # ------------------------------------------------------------------
    # Configuración general de la estrategia
    # ------------------------------------------------------------------
    timeframe = "4h"
    can_short = False
    process_only_new_candles = True
    use_custom_stoploss = True
    position_adjustment_enable = False

    # ROI prácticamente desactivado (100 = +10000%): no usamos take-profit
    # fijo. La salida "normal" es el cruce bajista de EMAs (ver
    # populate_exit_trend); la salida de emergencia es custom_stoploss o
    # el kill switch.
    minimal_roi = {"0": 100}

    # Stop duro de seguridad. custom_stoploss() casi siempre va a devolver
    # algo más ajustado que esto, pero freqtrade exige un valor de
    # self.stoploss como tope MÁXIMO absoluto de pérdida por operación
    # (custom_stoploss nunca puede devolver algo peor que este número).
    # Es la última red de seguridad si algo falla en el cálculo por ATR
    # (por ejemplo, un ATR corrupto o NaN).
    stoploss = -0.10

    # Suficientes velas de precalentamiento para que la EMA lenta (hasta
    # 100 periodos en el rango de hyperopt) y el ATR tengan datos válidos
    # antes de generar la primera señal.
    startup_candle_count = 200

    order_types = {
        "entry": "limit",
        "exit": "limit",
        "stoploss": "market",
        "stoploss_on_exchange": False,
    }

    # ------------------------------------------------------------------
    # Parámetros optimizables por hyperopt (Fase 2).
    # Máximo 4, según lo acordado, para no inflar los resultados con un
    # espacio de búsqueda gigante:
    #   1) ema_fast_len   (espacio "buy")
    #   2) ema_slow_len   (espacio "buy")
    #   3) min_atr_pct    (espacio "buy")  -> filtro de volatilidad
    #   4) atr_stop_mult  (espacio "sell") -> distancia del stop-loss
    # ------------------------------------------------------------------
    ema_fast_len = IntParameter(10, 30, default=20, space="buy", optimize=True)
    ema_slow_len = IntParameter(40, 100, default=50, space="buy", optimize=True)
    min_atr_pct = DecimalParameter(
        0.10, 1.00, default=0.30, decimals=2, space="buy", optimize=True
    )
    atr_stop_mult = DecimalParameter(
        1.5, 4.0, default=2.0, decimals=1, space="sell", optimize=True
    )

    # Periodo del ATR: fijo, no se hyperoptea (mantenemos el espacio de
    # búsqueda pequeño, como pediste).
    atr_period = 14

    # ------------------------------------------------------------------
    # Parámetros de gestión de riesgo. Estos son decisiones de diseño
    # fijas del proyecto (ver README/CRITERIOS.md), no se optimizan con
    # hyperopt: no queremos que el optimizador "descubra" que arriesgar
    # más da mejores números en el pasado. Se pueden ajustar a mano si
    # decides cambiarlos, pero siempre de forma consciente.
    # ------------------------------------------------------------------
    riesgo_por_operacion_pct = 0.015  # 1.5% del capital total por operación (entre 1-2%)
    perdida_diaria_limite_pct = 0.03  # -3% en un día (UTC) -> se pausan nuevas entradas
    drawdown_kill_switch_pct = 0.20  # -20% desde el máximo histórico de capital -> kill switch

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        # --- Estado interno del kill switch (drawdown total) ---
        self._equity_peak: float | None = None
        self._kill_switch_active: bool = False

        # --- Estado interno del límite de pérdida diaria ---
        self._dia_actual = None
        self._equity_inicio_dia: float | None = None
        self._pausa_diaria_activa: bool = False

    def informative_pairs(self):
        return []

    # ------------------------------------------------------------------
    # Indicadores
    # ------------------------------------------------------------------
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Precalculamos la EMA para TODOS los valores posibles del rango
        # de hyperopt (10 a 30, y 40 a 100). Esto es más caro en memoria,
        # pero evita recalcular indicadores en cada "epoch" del hyperopt:
        # freqtrade solo tiene que elegir qué columna mirar. Fuera de
        # hyperopt, .range solo contiene el valor actual del parámetro,
        # así que no hay costo extra en backtesting/dry-run normales.
        for val in self.ema_fast_len.range:
            dataframe[f"ema_fast_{val}"] = ta.EMA(dataframe, timeperiod=val)
        for val in self.ema_slow_len.range:
            dataframe[f"ema_slow_{val}"] = ta.EMA(dataframe, timeperiod=val)

        dataframe["atr"] = ta.ATR(dataframe, timeperiod=self.atr_period)
        # ATR como % del precio de cierre: así el filtro de volatilidad
        # es comparable entre monedas de precios muy distintos (BTC a
        # $60,000 vs ADA a $0.40).
        dataframe["atr_pct"] = 100 * dataframe["atr"] / dataframe["close"]

        return dataframe

    # ------------------------------------------------------------------
    # Señal de entrada: cruce alcista de EMAs + volatilidad suficiente
    # ------------------------------------------------------------------
    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        ema_fast = dataframe[f"ema_fast_{self.ema_fast_len.value}"]
        ema_slow = dataframe[f"ema_slow_{self.ema_slow_len.value}"]

        # Cruce alcista: la EMA rápida pasa de estar por debajo a estar
        # por encima de la EMA lenta EN ESTA vela (no veladas anteriores:
        # comparamos el valor actual contra el de la vela anterior con
        # .shift(1), usando solo datos ya cerrados, sin look-ahead).
        cruce_alcista = (ema_fast > ema_slow) & (ema_fast.shift(1) <= ema_slow.shift(1))

        # Filtro de volatilidad: no operamos si el ATR% está por debajo
        # del mínimo (mercado demasiado "plano", cruces poco confiables).
        volatilidad_suficiente = dataframe["atr_pct"] >= self.min_atr_pct.value

        # Confirmación adicional de tendencia: el precio de cierre debe
        # estar por encima de la EMA lenta (no solo cruzando, sino ya
        # instalado en zona alcista).
        tendencia_confirmada = dataframe["close"] > ema_slow

        dataframe.loc[
            cruce_alcista
            & volatilidad_suficiente
            & tendencia_confirmada
            & (dataframe["volume"] > 0),
            ["enter_long", "enter_tag"],
        ] = (1, "cruce_ema_alcista")

        return dataframe

    # ------------------------------------------------------------------
    # Señal de salida "normal": cruce bajista de EMAs (fin de tendencia)
    # ------------------------------------------------------------------
    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        ema_fast = dataframe[f"ema_fast_{self.ema_fast_len.value}"]
        ema_slow = dataframe[f"ema_slow_{self.ema_slow_len.value}"]

        cruce_bajista = (ema_fast < ema_slow) & (ema_fast.shift(1) >= ema_slow.shift(1))

        dataframe.loc[
            cruce_bajista & (dataframe["volume"] > 0),
            ["exit_long", "exit_tag"],
        ] = (1, "cruce_ema_bajista")

        return dataframe

    # ------------------------------------------------------------------
    # Tamaño de la posición: 1.5% de riesgo del capital total, según la
    # distancia del stop-loss (en % del precio de entrada).
    #
    # Ejemplo con números: capital total = 10,000 USDT, riesgo = 1.5% =
    # 150 USDT. Si el stop-loss por ATR queda a un 3% por debajo del
    # precio de entrada, entonces el tamaño de la posición debe ser tal
    # que, si se llega al stop, se pierdan exactamente esos 150 USDT:
    #   tamaño = 150 USDT / 3% = 5,000 USDT de posición.
    # ------------------------------------------------------------------
    def custom_stake_amount(
        self,
        pair: str,
        current_time: datetime,
        current_rate: float,
        proposed_stake: float,
        min_stake: float | None,
        max_stake: float,
        leverage: float,
        entry_tag: str | None,
        side: str,
        **kwargs,
    ) -> float:
        if self._kill_switch_active or self._pausa_diaria_activa:
            # confirm_trade_entry ya debería haber bloqueado la entrada
            # antes de llegar aquí; esto es un cinturón de seguridad extra.
            return 0

        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe.empty:
            return proposed_stake

        atr = dataframe["atr"].iloc[-1]
        if atr != atr or atr is None or atr <= 0:  # atr != atr detecta NaN
            return proposed_stake

        capital_total = self.wallets.get_total_stake_amount()
        riesgo_dinero = capital_total * self.riesgo_por_operacion_pct

        distancia_stop = self.atr_stop_mult.value * atr
        distancia_stop_pct = distancia_stop / current_rate
        if distancia_stop_pct <= 0:
            return proposed_stake

        stake_calculado = riesgo_dinero / distancia_stop_pct

        # Si el tamaño calculado por riesgo es menor al mínimo que exige
        # el exchange, lo subimos al mínimo: en ese caso el riesgo real
        # de la operación queda un poco por encima del 1.5% objetivo
        # (efecto secundario conocido y documentado, no un bug).
        if min_stake is not None:
            stake_calculado = max(stake_calculado, min_stake)
        stake_calculado = min(stake_calculado, max_stake)

        return stake_calculado

    # ------------------------------------------------------------------
    # Stop-loss basado en ATR, FIJO (no trailing) desde la entrada.
    #
    # custom_stoploss() debe devolver la distancia al stop como fracción
    # relativa al precio ACTUAL (no al de entrada). Como queremos un
    # precio de stop fijo (no que se mueva con el precio), calculamos el
    # precio de stop una sola vez -al momento de la entrada- y lo
    # guardamos en trade.set_custom_data(). En cada llamada posterior
    # recuperamos ese precio guardado y recalculamos la distancia
    # relativa al precio actual. set_custom_data/get_custom_data quedan
    # guardados en la base de datos del bot, así que sobreviven a un
    # reinicio del bot (importante para Fase 3).
    # ------------------------------------------------------------------
    def custom_stoploss(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        after_fill: bool,
        **kwargs,
    ) -> float | None:
        if self._kill_switch_active:
            # Distancia positiva y mínima: fuerza el cierre casi de
            # inmediato. La salida "oficial" por kill switch la maneja
            # custom_exit(), esto es un refuerzo.
            return 0.001

        precio_stop = trade.get_custom_data("precio_stop_atr")

        if precio_stop is None:
            dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
            atr_en_entrada = None
            if not dataframe.empty:
                vela_previa = dataframe.loc[dataframe["date"] <= trade.open_date_utc]
                if not vela_previa.empty:
                    atr_en_entrada = vela_previa["atr"].iloc[-1]

            if atr_en_entrada is None or atr_en_entrada != atr_en_entrada or atr_en_entrada <= 0:
                # No hay ATR válido disponible: nos quedamos con el stop
                # duro (self.stoploss) hasta que en la próxima llamada sí
                # podamos calcular el ATR correctamente.
                return self.stoploss

            precio_stop = trade.open_rate - (self.atr_stop_mult.value * atr_en_entrada)
            trade.set_custom_data("precio_stop_atr", precio_stop)

        distancia = (precio_stop - current_rate) / current_rate
        return distancia

    # ------------------------------------------------------------------
    # Salida forzada cuando el kill switch está activo: cierra CUALQUIER
    # posición abierta, sin importar su señal técnica.
    # ------------------------------------------------------------------
    def custom_exit(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs,
    ) -> str | bool | None:
        if self._kill_switch_active:
            return "kill_switch_drawdown_20pct"
        return None

    # ------------------------------------------------------------------
    # Bloquea nuevas entradas mientras el kill switch o la pausa diaria
    # estén activos.
    # ------------------------------------------------------------------
    def confirm_trade_entry(
        self,
        pair: str,
        order_type: str,
        amount: float,
        rate: float,
        time_in_force: str,
        current_time: datetime,
        entry_tag: str | None,
        side: str,
        **kwargs,
    ) -> bool:
        if self._kill_switch_active:
            return False
        if self._pausa_diaria_activa:
            return False
        return True

    # ------------------------------------------------------------------
    # Se ejecuta en cada iteración del bot (no por par, una sola vez).
    # Acá vigilamos el capital TOTAL de la cuenta para:
    #   a) el kill switch por drawdown total (>= 20% desde el máximo
    #      histórico de capital) -> bloquea entradas Y fuerza el cierre
    #      de todas las posiciones abiertas.
    #   b) el límite de pérdida diaria (>= 3% de pérdida en el día UTC en
    #      curso) -> bloquea SOLO nuevas entradas; las posiciones ya
    #      abiertas siguen su curso normal (no se fuerzan a cerrar, a
    #      diferencia del kill switch).
    # ------------------------------------------------------------------
    def bot_loop_start(self, current_time: datetime, **kwargs) -> None:
        capital_total = self.wallets.get_total_stake_amount()

        # --- a) Kill switch por drawdown total ---
        if self._equity_peak is None or capital_total > self._equity_peak:
            self._equity_peak = capital_total

        drawdown_total = 0.0
        if self._equity_peak and self._equity_peak > 0:
            drawdown_total = 1 - (capital_total / self._equity_peak)

        if drawdown_total >= self.drawdown_kill_switch_pct and not self._kill_switch_active:
            self._kill_switch_active = True
            mensaje = (
                f"🛑 KILL SWITCH ACTIVADO: drawdown total de {drawdown_total:.1%} "
                f"(umbral: {self.drawdown_kill_switch_pct:.0%}). Se bloquean nuevas "
                f"entradas y se cerrarán todas las posiciones abiertas en cuanto "
                f"se evalúe cada par."
            )
            logger.warning(mensaje)
            self.dp.send_msg(mensaje, always_send=True)

        # --- b) Límite de pérdida diaria (calendario UTC) ---
        dia_de_hoy = current_time.date()
        if self._dia_actual != dia_de_hoy:
            self._dia_actual = dia_de_hoy
            self._equity_inicio_dia = capital_total
            self._pausa_diaria_activa = False

        perdida_hoy = 0.0
        if self._equity_inicio_dia and self._equity_inicio_dia > 0:
            perdida_hoy = 1 - (capital_total / self._equity_inicio_dia)

        if perdida_hoy >= self.perdida_diaria_limite_pct and not self._pausa_diaria_activa:
            self._pausa_diaria_activa = True
            mensaje = (
                f"⚠️ Límite de pérdida diaria alcanzado: -{perdida_hoy:.1%} en el día "
                f"(umbral: {self.perdida_diaria_limite_pct:.0%}). Se pausan nuevas "
                f"entradas hasta el próximo día UTC. Las posiciones ya abiertas NO "
                f"se cierran por esta razón."
            )
            logger.warning(mensaje)
            self.dp.send_msg(mensaje, always_send=True)
