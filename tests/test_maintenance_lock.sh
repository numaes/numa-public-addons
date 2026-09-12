#!/bin/bash
# Verifica el candado de mantenimiento: que un apagado deliberado impida que la
# supervision del cron arranque encima, y que el candado caduque.
#
#     ./tests/test_maintenance_lock.sh
#
# Existe por una ventana real. Durante un `-u` no hay pidfile; la linea de cron
# `onboot.sh --si-no-corre` lo lee como "se cayo" y arranca un segundo Odoo sobre la misma
# base mientras la actualizacion corre. Se estuvo a un minuto de que pasara en un
# despliegue: hubo que comentar la linea del crontab a mano.
#
# Corre contra tests/expected/*.sh, que es la salida fijada del generador, asi que
# tambien avisa si alguien toca esos scripts y se lleva el candado por delante.
set -uo pipefail

cd "$(dirname "$0")/.."
EXPECTED="$PWD/tests/expected"
FAILED=0
ok ()   { printf '  %-8s %s\n' "ok" "$1"; }
fail () { printf '  %-8s %s\n' "FALLA" "$1"; FAILED=$((FAILED + 1)); }

WORK="$(mktemp -d -t maint-lock-XXXXXX)"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/venv/bin" "$WORK/log"
: > "$WORK/venv/bin/activate"
: > "$WORK/odoo.config"

# onboot.sh lleva grabada la ruta de la instalacion; se la apuntamos al directorio de
# prueba. start.sh se reemplaza por un testigo: lo que importa es SI arranca, no que
# levante un Odoo de verdad.
sed "s#^cd \".*\" || exit 1#cd \"$WORK\" || exit 1#" "$EXPECTED/onboot.sh" > "$WORK/onboot.sh"
cp "$EXPECTED/stop.sh" "$WORK/stop.sh"
printf '#!/bin/bash\ntouch "%s/arranco.testigo"\n' "$WORK" > "$WORK/start.sh"
chmod +x "$WORK"/onboot.sh "$WORK"/stop.sh "$WORK"/start.sh

cd "$WORK"

echo "Con un mantenimiento en curso:"
{ date +%s; echo "detenido a mano"; } > mantenimiento.lock
rm -f arranco.testigo
OUT="$(./onboot.sh --si-no-corre 2>&1)"; RC=$?
[ "$RC" -eq 0 ]            && ok "sale sin error"           || fail "salio con codigo $RC"
[ ! -f arranco.testigo ]   && ok "no arranca encima"        || fail "arranco durante el mantenimiento"
[ -z "$OUT" ]              && ok "callado (no llena el mail del cron)" || fail "escribio: $OUT"
[ -f mantenimiento.lock ]  && ok "deja el candado puesto"   || fail "borro el candado"

echo
echo "Con un candado vencido:"
# Leido del propio script: atarlo a un numero fijo lo rompe cada vez que se ajusta
# cuanto puede durar un mantenimiento legitimo.
MAX=$(grep -m1 'MANTENIMIENTO_MAX=' onboot.sh | cut -d= -f2)
{ echo $(( $(date +%s) - MAX - 60 )); echo "abandonado"; } > mantenimiento.lock
rm -f arranco.testigo
OUT="$(./onboot.sh --si-no-corre 2>&1)"
sleep 1
grep -q "candado de mantenimiento vencido" <<< "$OUT" \
    && ok "avisa que estaba vencido"      || fail "no aviso del vencimiento"
[ -f arranco.testigo ]     && ok "arranca igual"            || fail "no arranco pese al vencimiento"
[ ! -f mantenimiento.lock ] && ok "limpia el candado vencido" || fail "dejo el candado vencido"

echo
echo "Sin candado y sin nada corriendo:"
rm -f arranco.testigo mantenimiento.lock
./onboot.sh --si-no-corre >/dev/null 2>&1
sleep 1
[ -f arranco.testigo ]     && ok "arranca, que es su trabajo" || fail "no arranco"

echo
echo "El orden dentro de stop.sh:"
# Esta es la comprobacion que faltaba. El candado al final deja una ventana entre "el
# master ya murio" y "el candado ya esta"; en produccion duro tres segundos y el cron de
# los cinco minutos cayo justo adentro. La invariante es estructural, asi que se verifica
# sobre el texto del script y no con un cronometro.
LOCK_LN=$(grep -n 'mantenimiento.lock' "$EXPECTED/stop.sh" | head -1 | cut -d: -f1)
# Sin el filtro de comentarios esto agarra la linea que explica por que no se usa
# `pkill -f odoo-bin`, que esta mucho antes que cualquier codigo.
KILL_LN=$(grep -n 'kill -' "$EXPECTED/stop.sh" | grep -v ':[[:space:]]*#' | head -1 | cut -d: -f1)
if [ -n "$LOCK_LN" ] && [ -n "$KILL_LN" ] && [ "$LOCK_LN" -lt "$KILL_LN" ]; then
    ok "el candado se escribe antes del primer kill (linea $LOCK_LN < $KILL_LN)"
else
    fail "el candado se escribe DESPUES de matar: linea $LOCK_LN, primer kill $KILL_LN"
fi

echo
echo "stop.sh deja el candado:"
rm -f mantenimiento.lock
# Un proceso que se hace pasar por el de este ambiente: stop.sh lo reconoce por la ruta
# absoluta del config en su linea de comandos, no por el nombre.
# El `; :` no es decorativo: con un solo comando, bash -c hace exec y se reemplaza la
# linea de comandos, que es justo lo que stop.sh mira para reconocer el ambiente.
bash -c 'sleep 60; :' "$WORK/odoo.config" &
FAKE=$!
echo "$FAKE" > running-odoo.pid
./stop.sh >/dev/null 2>&1
[ -f mantenimiento.lock ]  && ok "lo escribe al apagar"      || fail "no dejo candado al apagar"
head -1 mantenimiento.lock | grep -qE '^[0-9]+$' \
    && ok "la primera linea es la marca de tiempo" || fail "la marca de tiempo no es un numero"
kill "$FAKE" 2>/dev/null

echo
echo "Con el ambiente ya apagado:"
rm -f mantenimiento.lock running-odoo.pid
./stop.sh >/dev/null 2>&1
[ -f mantenimiento.lock ] \
    && ok "igual deja el candado: quien apaga esta por hacer algo" \
    || fail "no dejo candado con el ambiente ya apagado"

echo
if [ "$FAILED" -eq 0 ]; then echo "Todo bien."; exit 0; fi
echo "$FAILED comprobacion(es) fallaron."
exit 1
