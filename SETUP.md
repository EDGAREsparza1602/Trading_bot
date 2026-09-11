# Fase 1 — Entorno y datos

Esta guía asume que la corres en **tu propia máquina o un servidor tuyo**
(no en esta sesión de Claude Code en la nube): ahí es donde vamos a
descargar datos reales de Binance y, más adelante en Fase 3, donde va a
quedar corriendo el bot en dry-run durante meses. Esta sesión no tiene
salida de red hacia Binance ni almacenamiento permanente, así que preparé
todo el código pero la ejecución real te toca a ti — te explico cada
comando para que entiendas qué hace.

## Requisitos previos

- **Docker** y **Docker Compose** instalados. Si usas Docker Desktop
  (Mac/Windows) o Docker Engine (Linux), ya trae `docker compose`
  incluido. Verifica con:

  ```bash
  docker --version
  docker compose version
  ```

- Que el daemon de Docker esté corriendo (en Linux: `sudo systemctl
  status docker`; en Mac/Windows: que Docker Desktop esté abierto).
- No necesitas cuenta en Binance ni API keys para nada de lo que sigue
  (dry-run y descarga de datos usan solo la API pública).

## 1. Clonar/actualizar el repo

```bash
git clone https://github.com/EDGAREsparza1602/Trading_bot.git
cd Trading_bot
git checkout claude/freqtrade-crypto-trading-experiment-axfiwn
git pull
```

## 2. Qué es cada archivo que ya está en el repo

- **`docker-compose.yml`**: define el servicio `freqtrade` usando la
  imagen oficial `freqtradeorg/freqtrade:stable`. Monta la carpeta
  `./user_data` dentro del contenedor, que es donde freqtrade guarda
  config, estrategias, datos descargados y resultados.
- **`user_data/config.json`**: configuración del bot.
  - `"dry_run": true` — modo simulado, fijo para todo el proyecto.
  - `"exchange.name": "binance"`, `"key"/"secret"` vacíos — no hacen
    falta credenciales para dry-run ni para descargar datos públicos.
  - `"exchange.pair_whitelist"` — el universo de 6 pares (ver
    `DATOS.md` para la justificación de cada uno).
  - `"fee": 0.001` — comisión de 0.1% por lado, como decidiste.
  - `"telegram.enabled": false` y `"api_server.enabled": false` — los
    activaremos en Fase 3.
- **`scripts/download_data.sh`**: descarga las velas históricas.
- **`DATOS.md`**: qué datos se descargan, por qué, y cuál es la
  ventana reservada ("datos sagrados") que no se toca hasta el final.

## 3. Descargar las velas históricas

```bash
docker compose pull       # baja la imagen oficial de freqtrade (~600 MB)
./scripts/download_data.sh
```

Este script corre por dentro:

```bash
docker compose run --rm freqtrade download-data \
    --config user_data/config.json \
    --timeframes 1d 4h \
    --timerange 20170101- \
    --erase
```

- `download-data`: subcomando de freqtrade que descarga velas OHLCV
  (open/high/low/close/volume) desde la API pública del exchange
  configurado (Binance).
- `--timeframes 1d 4h`: descarga velas diarias y de 4 horas (ver
  `DATOS.md` sobre por qué ambas).
- `--timerange 20170101-`: desde el 1 de enero de 2017 hasta hoy (el
  guion final sin fecha de cierre significa "hasta la fecha actual").
  Para pares que no existían en 2017, freqtrade trae la historia desde
  que sí existen — no falla.
- `--erase`: borra datos previos de esos pares/timeframes antes de
  descargar, para asegurar que no queden huecos si corres el script
  más de una vez.

Los datos quedan en `user_data/data/binance/` como archivos `.feather`
(un `.json`/`.feather` por par y timeframe). Esa carpeta está en
`.gitignore` — no se sube al repo porque pesa mucho y se puede
regenerar en cualquier momento con este mismo script.

Esto puede tardar varios minutos (son ~9 años de velas de 4h para 6
pares). Si el proceso se corta a mitad, simplemente vuelve a correr el
script: con `--erase` queda limpio.

## 4. Verificar que los datos se descargaron bien

```bash
docker compose run --rm freqtrade list-data --config user_data/config.json
```

Debe listarte los 6 pares en ambos timeframes, con su rango de fechas.
Revisa en particular:

- BTC/USDT y ETH/USDT deberían empezar cerca de 2017-2018 (según
  cuándo Binance tiene histórico público disponible).
- ADA/USDT y XRP/USDT probablemente empiecen un poco después (se
  listaron más tarde).
- Todos deberían llegar hasta prácticamente "hoy".

Si algún par se ve con muchos menos datos de lo esperado, puede ser un
problema de conectividad a mitad de la descarga — vuelve a correr
`./scripts/download_data.sh`.

## 5. (Opcional) Entorno virtual de Python en vez de Docker

Docker es el camino recomendado (así lo pediste), pero si en algún
momento prefieres no usar Docker, freqtrade también se instala con pip.
Ya lo probé en esta sesión y funciona sin problemas, incluyendo TA-Lib:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install freqtrade
freqtrade --version
```

Con esta vía, los comandos son los mismos pero sin el prefijo
`docker compose run --rm freqtrade`, por ejemplo:

```bash
freqtrade download-data --config user_data/config.json --timeframes 1d 4h --timerange 20170101- --erase
```

## Checklist de fin de Fase 1

- [ ] Docker y Docker Compose funcionando en tu máquina.
- [ ] `./scripts/download_data.sh` corrido sin errores.
- [ ] `freqtrade list-data` muestra los 6 pares en 1d y 4h con rango de
      fechas razonable (varios años).
- [ ] Entiendes qué es la ventana reservada de `DATOS.md` (2025-09-11 →
      hoy) y que no se toca hasta el final de Fase 2.

Cuando confirmes que la descarga terminó bien (puedes pegarme la salida
de `list-data` si quieres que la revise), seguimos con **Fase 2:
estrategia y backtest**.
