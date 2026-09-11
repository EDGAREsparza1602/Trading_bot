# Fase 3 — Dry-run piloto de 1 mes

Todo esto corre en tu máquina (no en este sandbox). Nada acá usa dinero
real: `dry_run: true` está fijo en `user_data/config.json` y no lo toca
ningún archivo de esta fase.

## 0. Qué cambia respecto a Fase 1-2

- `user_data/config-live.json`: activa Telegram y una API interna
  (solo para un chequeo de salud automático), leyendo credenciales
  desde variables de entorno — nunca en texto plano en el repo.
- `docker-compose.yml`: ahora define un `command:` de arranque
  (`trade`, dry-run), un healthcheck, y un segundo servicio
  (`autoheal`) que reinicia el bot solo si deja de responder.
- `scripts/reporte_semanal.py`: genera un reporte HTML con las
  métricas de `CRITERIOS.md` y la comparación contra BTC.

## 1. Crear el bot de Telegram

1. En Telegram, buscá **@BotFather** y abrile un chat.
2. Enviale `/newbot`. Te va a pedir un nombre (cualquiera, ej.
   "Mi Bot Cripto Experimento") y un username que termine en "bot"
   (ej. `mi_experimento_cripto_bot`).
3. BotFather te da un **token** con este formato:
   `123456789:ABCdefGhIJKlmnOpQRstUVwxyZ`. Guardalo, es el único
   momento en que lo ves completo.
4. Ahora necesitás tu **chat_id**. Enviale cualquier mensaje a tu bot
   recién creado (ej. "hola"), y después abrí en tu navegador (reemplazá
   `<TOKEN>` por el tuyo):

   ```
   https://api.telegram.org/bot<TOKEN>/getUpdates
   ```

   Vas a ver una respuesta JSON. Buscá `"chat":{"id":` — ese número
   (puede ser negativo si es un grupo) es tu `chat_id`.

## 2. Configurar tu `.env`

```powershell
copy .env.example .env
notepad .env
```

Completá:

```
FREQTRADE__TELEGRAM__TOKEN=123456789:ABCdefGhIJKlmnOpQRstUVwxyZ
FREQTRADE__TELEGRAM__CHAT_ID=987654321

FREQTRADE__API_SERVER__USERNAME=elegir_cualquier_usuario
FREQTRADE__API_SERVER__PASSWORD=elegir_cualquier_password
FREQTRADE__API_SERVER__JWT_SECRET_KEY=<32+ caracteres al azar>
```

Para generar el `jwt_secret_key` en PowerShell:

```powershell
-join ((48..57)+(97..122)|Get-Random -Count 40 |%{[char]$_})
```

**`.env` está en `.gitignore` — nunca se sube al repo.** Si en algún
momento `git status` te muestra `.env` como archivo nuevo para
commitear, algo anda mal: avisame antes de seguir.

## 3. Arrancar el dry-run

```powershell
docker compose pull
docker compose up -d
```

`docker compose pull` baja también la imagen de `autoheal` (chica,
unos segundos). `up -d` deja todo corriendo en segundo plano.

Anotá la fecha y hora de este momento — la vas a necesitar como
`--inicio-piloto` para el reporte semanal (ver más abajo). Este es el
día 1 del mes piloto de `CRITERIOS.md`: las operaciones de los
primeros 30 días no cuentan para la evaluación final, son solo para
depurar.

Verificá que arrancó bien:

```powershell
docker compose logs -f freqtrade
```

Deberías ver un mensaje de Telegram de "startup" llegando a tu chat en
los primeros minutos. `Ctrl+C` para dejar de seguir los logs (el bot
sigue corriendo).

## 4. Ver qué está pasando

**Telegram:** vas a recibir un mensaje por cada entrada/salida de
operación, cada vez que se dispare el límite de pérdida diaria o el
kill switch, y un mensaje de "startup" cada vez que el bot se reinicia
(que además te avisa indirectamente si se había colgado y el
healthcheck lo reinició solo).

**FreqUI (panel web):** abrí en tu navegador
**http://127.0.0.1:8080** — usuario y contraseña son los que pusiste
en `.env`. Vas a ver posiciones abiertas, historial de operaciones,
capital, y gráficos de velas con las entradas/salidas marcadas. Si la
página no carga la interfaz (solo un JSON), corré una vez:

```powershell
docker compose exec freqtrade freqtrade install-ui
docker compose restart freqtrade
```

Este panel solo es accesible desde tu propia máquina (`127.0.0.1`), no
desde otras computadoras ni internet.

## 5. Reporte semanal

Corré esto una vez por semana (ajustá `--inicio-piloto` a la fecha real
en que arrancaste en el paso 3, y el nombre del archivo de salida a la
fecha de hoy):

```powershell
docker compose run --rm --entrypoint python freqtrade `
    scripts/reporte_semanal.py `
    --config user_data/config.json `
    --db-url sqlite:////freqtrade/user_data/tradesv3.dryrun.sqlite `
    --inicio-piloto 2026-09-15 `
    --salida user_data/reportes/reporte_2026-09-22.html
```

Esto genera un HTML en `user_data\reportes\` (ya mapeado a tu carpeta
local) con: capital actual, retorno total, Sharpe, Sortino, drawdown,
win rate, profit factor, comparación contra `CRITERIOS.md` y contra
buy-and-hold BTC, un gráfico de la curva de capital, y el log completo
de cada operación (fecha, par, precio de entrada/salida, tamaño, motivo
de entrada y de salida). Abrilo con doble clic, se ve en cualquier
navegador sin necesitar internet.

## 6. Si el kill switch se dispara

A diferencia del backtest, en dry-run el kill switch **sí** bloquea:
deja de abrir operaciones nuevas y fuerza el cierre de las que estén
abiertas. Vas a recibir un mensaje de Telegram bien visible avisando.
Requiere que **vos** decidas qué hacer — no se reactiva solo:

- Si querés investigar antes de reanudar: dejalo así, revisá qué pasó
  (mirá el reporte semanal, FreqUI, los logs).
- Para reanudar: `docker compose restart freqtrade` (esto crea una
  instancia nueva de la estrategia, con el kill switch reseteado).

Recordá: en el backtest de Fase 2 esto se disparó varias veces a lo
largo de 8 años y una vez durante el año de validación reservada — no
sería sorpresa que pase también durante el piloto.

## 7. Pausar o detener

```powershell
docker compose stop      # pausa todo, se puede reanudar con "up -d"
docker compose down      # baja los contenedores (la base de datos en
                          # user_data/ no se borra, sigue en tu disco)
```

## Checklist de Fase 3

- [ ] Bot de Telegram creado, token y chat_id en `.env`
- [ ] `docker compose up -d` corriendo, mensaje de "startup" recibido
- [ ] FreqUI accesible en http://127.0.0.1:8080
- [ ] Primer reporte semanal generado sin errores
- [ ] Fecha de inicio del piloto anotada (para saber cuándo termina el
      mes de depuración y empieza a contar la evaluación real)

Avisame cuando tengas esto corriendo y el primer reporte generado —
revisamos juntos que todo se vea razonable antes de dejarlo corriendo
el mes completo.
