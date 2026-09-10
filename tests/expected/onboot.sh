#!/bin/bash
# Arranque, rotacion del log y supervision de ESTE ambiente.
#
#   ./onboot.sh                  arranca (es lo que llama el @reboot del crontab)
#   ./onboot.sh --si-no-corre    arranca solo si no esta corriendo; para una linea de cron
#   ./onboot.sh --solo-rotar     rota el log y sale, sin arrancar nada
#
# Sin shebang, el `@reboot /bin/bash -c .../onboot.sh` del crontab termina ejecutando
# esto con /bin/sh (dash), que no conoce `source`: el venv no se activa y odoo-bin muere
# con ModuleNotFoundError. $CWD se interpola aca a proposito: cron arranca en otro
# directorio y necesita la ruta absoluta.
cd "/opt/cm-18.0" || exit 1

MODO="${1:-}"
LOG=log/odoo-server.log
LOG_MAX=$((50 * 1024 * 1024))
LOG_KEEP=7

# Un proceso es de este ambiente si su linea de comandos nombra NUESTRO config: varios
# ambientes conviven como directorios hermanos y todos lanzan el mismo odoo-bin.
es_de_este_ambiente () {
    [ -r "/proc/$1/cmdline" ] || return 1
    tr '\0' ' ' < "/proc/$1/cmdline" | grep -qF "$(pwd)/odoo.config"
}

# --si-no-corre: para una linea de cron cada pocos minutos. El @reboot solo cubre el
# reinicio de la maquina; si el master muere por cualquier otra razon, sin esto no lo
# levanta nadie. Silencioso mientras todo va bien, para no llenar el mail del cron.
if [ "$MODO" = "--si-no-corre" ]; then
    # Un apagado deliberado deja un candado. No arrancar encima de un mantenimiento en
    # curso; y que el candado caduque, para que uno abandonado no deje el ambiente caido
    # indefinidamente. Silencioso mientras el mantenimiento es reciente.
    MANTENIMIENTO_MAX=1800
    if [ -f mantenimiento.lock ]; then
        DESDE=$(head -1 mantenimiento.lock 2>/dev/null)
        case "$DESDE" in ''|*[!0-9]*) DESDE=0 ;; esac
        AHORA=$(date +%s)
        if [ "$DESDE" -gt 0 ] && [ $((AHORA - DESDE)) -lt "$MANTENIMIENTO_MAX" ]; then
            exit 0
        fi
        echo "$(date '+%F %T') candado de mantenimiento vencido; arranco igual"
        rm -f mantenimiento.lock
    fi
    if [ -f running-odoo.pid ]; then
        PID=$(cat running-odoo.pid)
        if kill -0 "$PID" 2>/dev/null && es_de_este_ambiente "$PID"; then
            exit 0
        fi
    fi
    # Que el pidfile no sirva no prueba que no este corriendo: puede haberse perdido o
    # quedado viejo, y de hecho uno apuntaba a un worker en vez de al master. Arrancar un
    # segundo Odoo sobre la misma base es mucho peor que no arrancar ninguno, asi que se
    # busca por linea de comandos antes de decidir.
    for _p in $(pgrep -f "odoo-bin" 2>/dev/null); do
        if es_de_este_ambiente "$_p"; then
            echo "$(date '+%F %T') corriendo como pid $_p pero sin pidfile valido; no arranco otro"
            exit 0
        fi
    done
    echo "$(date '+%F %T') no estaba corriendo; arrancando"
fi

# Rotar antes de arrancar. Aca y no en start.sh porque este es el unico lugar que conoce
# la ruta del log: start.sh la recibe como argumento y tendria que parsearsela. Rotar
# ANTES de que odoo abra el archivo evita copytruncate y evita mandarle señales: el
# proceso nuevo crea el suyo limpio. Odoo 18 ya no trae rotacion propia.
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

[ "$MODO" = "--solo-rotar" ] && exit 0

source venv/bin/activate
exec ./start.sh --pidfile=running-odoo.pid --logfile="$LOG" &
