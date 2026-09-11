#!/usr/bin/env bash
# Descarga las velas históricas del universo definido en user_data/config.json
# (pair_whitelist) para los timeframes 1d y 4h, desde 2017-01-01 hasta hoy.
#
# Para pares que no existían aún en 2017 (p.ej. ADA se listó en Binance a
# mediados de 2018), freqtrade simplemente descarga desde la fecha en que
# empieza a existir el par: no falla, solo trae menos historia para ese par.
#
# Requiere que el daemon de Docker esté corriendo en la máquina donde se
# ejecuta este script (tu PC/servidor, no el sandbox de esta sesión).
#
# Uso:
#   ./scripts/download_data.sh

set -euo pipefail
cd "$(dirname "$0")/.."

docker compose run --rm freqtrade download-data \
    --config user_data/config.json \
    --timeframes 1d 4h \
    --timerange 20170101- \
    --erase
