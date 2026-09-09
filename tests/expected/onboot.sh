#!/bin/bash
# Sin shebang, el `@reboot /bin/bash -c .../onboot.sh` del crontab termina ejecutando
# esto con /bin/sh (dash), que no conoce `source`: el venv no se activa y odoo-bin muere
# con ModuleNotFoundError. $CWD se interpola aca a proposito: cron arranca en otro
# directorio y necesita la ruta absoluta.
cd "/opt/cm-18.0" || exit 1

LOG=log/odoo-server.log
LOG_MAX=$((50 * 1024 * 1024))
LOG_KEEP=7

# Rotar antes de arrancar. Aca y no en start.sh porque este es el unico lugar que conoce
# la ruta del log: start.sh la recibe como argumento y tendria que parsearsela.
#
# Rotar ANTES de que odoo abra el archivo evita copytruncate y evita mandarle señales:
# el proceso nuevo crea el suyo limpio. Odoo 18 ya no trae rotacion propia -- la opcion
# `logrotate` existia en versiones viejas y fue removida.
#
# Solo rota pasado el umbral, para que un reinicio no deje fragmentos de kilobytes. El
# caso que esto NO cubre es un servidor que corre meses sin reiniciarse; para eso, una
# linea de cron:  0 4 * * * /bin/bash /opt/cm-18.0/onboot.sh --solo-rotar
if [ -f "$LOG" ] && [ "$(stat -c%s "$LOG" 2>/dev/null || echo 0)" -gt "$LOG_MAX" ]; then
    rm -f "$LOG.$LOG_KEEP.gz"
    i=$((LOG_KEEP - 1))
    while [ "$i" -ge 1 ]; do
        [ -f "$LOG.$i.gz" ] && mv -f "$LOG.$i.gz" "$LOG.$((i + 1)).gz"
        i=$((i - 1))
    done
    mv -f "$LOG" "$LOG.1" && gzip -f "$LOG.1"
    echo "onboot: log rotado (superaba $((LOG_MAX / 1024 / 1024)) MB), se conservan $LOG_KEEP"
fi

# Permite usar este mismo script desde cron solo para rotar, sin arrancar nada.
[ "$1" = "--solo-rotar" ] && exit 0

source venv/bin/activate
exec ./start.sh --pidfile=running-odoo.pid --logfile="$LOG" &
