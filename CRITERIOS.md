# Criterios de éxito/fracaso — Experimento de trading algorítmico (dry-run)

**Fecha de registro:** 2026-09-11

> Este documento es un pre-registro. Los criterios aquí definidos **no se
> modifican después de ver resultados** de backtest ni de dry-run. Si en el
> futuro se decide cambiar algo, debe quedar registrado como una decisión
> nueva y explícita (con fecha y motivo), nunca como edición silenciosa de
> lo ya escrito aquí.

## Alcance del proyecto

- Proyecto **100% educativo / de investigación**. El objetivo es aprender y
  comprobar con datos si una estrategia simple de seguimiento de
  tendencia/momentum supera a "comprar y mantener BTC" (buy-and-hold),
  **no** generar ganancias reales.
- **En ningún momento se usará dinero real.** Todo el ciclo de vida del
  proyecto (backtest y ejecución en vivo) se hace en modo **dry-run** de
  freqtrade, con capital simulado. No se configurarán API keys de trading
  real del exchange.

## Condición de éxito

El experimento se considera **exitoso** si, tras acumular en dry-run:

- ≥ 3 meses de operación continua, **y**
- ≥ 50 operaciones cerradas,

se cumplen **todas** las siguientes condiciones sobre esa ventana:

1. **Retorno neto de costos** (comisiones incluidas) de la estrategia ≥
   retorno de comprar y mantener BTC en la misma ventana temporal.
2. **Sharpe ratio neto** (anualizado usando 365 días, sobre retornos
   netos de comisiones) **> 1**.
3. **Drawdown máximo ≤ 20%** sobre el capital simulado.

## Condición de fracaso

El experimento se considera **fallido** si:

- No se cumple alguna de las tres condiciones de éxito anteriores una vez
  alcanzados los ≥3 meses y ≥50 operaciones, **o**
- Se dispara el **kill switch** por drawdown total ≥ 20% en cualquier
  momento (esto termina el experimento inmediatamente, sin esperar a los
  3 meses).

## Regla del mes piloto

El **primer mes de dry-run es un piloto de depuración**: sirve para
detectar errores de configuración, bugs de la estrategia, problemas de
conectividad con el exchange/Telegram, etc. **Las operaciones y métricas
del mes piloto no cuentan para la evaluación de éxito/fracaso.** El
reloj de "≥3 meses y ≥50 operaciones" empieza a contar **después** de
cerrar el mes piloto y confirmar que el bot funciona de forma estable.

## Notas metodológicas (fijadas de antemano, no negociables post-hoc)

- Todas las métricas se calculan **netas de comisiones** (0.1% por lado,
  Binance spot).
- El Sharpe/Sortino se calculan sobre retornos diarios o por operación
  (se especificará en el código del reporte, pero el método de cálculo no
  cambia entre el reporte semanal 1 y el reporte final).
- La comparación contra "buy-and-hold BTC" usa el precio de BTC/USDT al
  inicio y fin de la misma ventana exacta que se está evaluando.
- Cualquier cambio de estrategia, parámetros o universo de monedas
  **durante** el dry-run de evaluación (no el piloto) invalida la
  ventana en curso: se documenta y se reinicia el conteo de 3
  meses/50 operaciones.

## Historial de cambios a este documento

| Fecha | Cambio | Motivo |
|-------|--------|--------|
| 2026-09-11 | Creación inicial (Fase 0) | Pre-registro antes de escribir cualquier código o backtest |
