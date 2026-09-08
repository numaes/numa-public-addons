#!/bin/bash
# Apagado ordenado. Un `kill -9` al master no le da a Odoo la oportunidad de cerrar
# workers ni conexiones, deja workers huerfanos (se ven en el log como "Parent changed"
# seguidos de "exiting" hasta minuto y medio despues) y puede matar un wkhtmltopdf en
# curso -- que es como aparece un "Wkhtmltopdf failed (error code: -9)" sin que haya OOM.
cd "$(dirname "$0")"
[ -f running-odoo.pid ] || { echo "no hay running-odoo.pid"; exit 0; }
PID=$(cat running-odoo.pid)
if ! kill -0 "$PID" 2>/dev/null; then
    echo "el pid $PID ya no corre"; rm -f running-odoo.pid; exit 0
fi
echo "apagando odoo (pid $PID) con SIGTERM..."
kill -TERM "$PID"
for i in $(seq 1 30); do
    kill -0 "$PID" 2>/dev/null || { echo "apagado limpio en ${i}s"; rm -f running-odoo.pid; exit 0; }
    sleep 1
done
echo "no respondio en 30s, SIGKILL como ultimo recurso"
kill -9 "$PID" 2>/dev/null || true
rm -f running-odoo.pid
