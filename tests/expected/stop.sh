#!/bin/bash
# Apagado ordenado de ESTE ambiente, y solo de este.
#
# Varios ambientes conviven como directorios hermanos -- produccion y prueba, cada uno con
# su venv, su odoo.config y su puerto -- y todos lanzan el mismo odoo-bin. Cualquier
# apagado que busque procesos por patron de nombre (`pkill -f odoo-bin`) alcanza a los
# vecinos. Aca no se busca por nombre en ningun momento:
#
#   1. el pid sale de running-odoo.pid, y se verifica contra la ruta absoluta del config
#      que start.sh le pasa a odoo-bin -- un pidfile viejo puede nombrar un pid reciclado
#      por un proceso ajeno, y matar eso seria matar algo de otro;
#   2. los workers se capturan como hijos de ESE pid, y se capturan ANTES de tocar al
#      padre: apenas el master muere, los hijos quedan huerfanos reparentados a init y ya
#      no hay forma de saber de quien eran;
#   3. antes de matar a cada superviviente se vuelve a verificar que siga siendo de este
#      ambiente, por si el pid se reciclo entre la captura y el remate.
#
# Un `kill -9` al master, sin nada de esto, dejaba workers huerfanos hasta minuto y medio
# y podia matar un wkhtmltopdf en curso -- que es como aparece un
# "Wkhtmltopdf failed (error code: -9)" en el log sin que haya OOM por ningun lado.
cd "$(dirname "$0")"
ENV_DIR="$(pwd)"

# El candado, ANTES de matar nada. Un apagado deliberado es, por definicion,
# mantenimiento: la supervision del cron no tiene que arrancar un segundo Odoo sobre la
# misma base mientras corre un `-u`.
#
# El orden es la parte que importa, y se aprendio de la unica manera. Escribirlo al final
# deja una ventana entre "el master ya murio y el pidfile ya no esta" y "el candado ya
# esta puesto". En produccion esa ventana duro tres segundos y el cron de los cinco
# minutos cayo justo adentro: apago a las 09:10:02, el cron disparo a las 09:10:00, y
# arranco un Odoo nuevo que despues se quedo sin pidfile porque stop.sh lo borro detras
# suyo.
#
# Se escribe aunque el ambiente ya este apagado: quien corre stop.sh esta por hacer algo.
# El candado caduca solo -- un mantenimiento abandonado no puede dejar el ambiente caido
# para siempre -- y lo borra el proximo arranque.
{ date +%s; echo "detenido por stop.sh el $(date '+%F %T')"; } > mantenimiento.lock

es_de_este_ambiente () {  # es_de_este_ambiente <pid>
    [ -r "/proc/$1/cmdline" ] || return 1
    tr '\0' ' ' < "/proc/$1/cmdline" | grep -qF "$ENV_DIR/odoo.config"
}

[ -f running-odoo.pid ] || { echo "no hay running-odoo.pid"; exit 0; }
PID=$(cat running-odoo.pid)

if ! kill -0 "$PID" 2>/dev/null; then
    echo "el pid $PID ya no corre"; rm -f running-odoo.pid; exit 0
fi

if ! es_de_este_ambiente "$PID"; then
    echo "el pid $PID no corresponde a $ENV_DIR -- no lo toco." >&2
    echo "running-odoo.pid quedo desactualizado; borralo a mano si estas seguro." >&2
    exit 1
fi

# Capturar los workers ahora, mientras el padre todavia esta y la relacion es visible.
HIJOS=$(pgrep -P "$PID" 2>/dev/null)

echo "apagando odoo de $ENV_DIR (pid $PID) con SIGTERM..."
kill -TERM "$PID" 2>/dev/null
for i in $(seq 1 30); do
    kill -0 "$PID" 2>/dev/null || { echo "apagado limpio en ${i}s"; break; }
    sleep 1
done
if kill -0 "$PID" 2>/dev/null; then
    echo "no respondio en 30s, SIGKILL como ultimo recurso"
    kill -9 "$PID" 2>/dev/null
fi

# Workers que hayan sobrevivido al padre. Solo los capturados, y solo si siguen siendo
# nuestros: nunca por patron.
for h in $HIJOS; do
    kill -0 "$h" 2>/dev/null && es_de_este_ambiente "$h" && kill -TERM "$h" 2>/dev/null
done
sleep 2
for h in $HIJOS; do
    if kill -0 "$h" 2>/dev/null && es_de_este_ambiente "$h"; then
        echo "  worker $h no cerro solo, SIGKILL"
        kill -9 "$h" 2>/dev/null
    fi
done

rm -f running-odoo.pid
