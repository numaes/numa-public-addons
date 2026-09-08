#!/bin/bash
# Respaldo logico de una base Odoo: volcado de PostgreSQL + filestore, en un solo archivo.
#
# Uso:   ./dbbackup.sh <base> [rol]
#        KEEP=14 ./dbbackup.sh <base>      # cuantos respaldos conservar (0 = todos)
#
# Produce  ./database/<base>-<fecha>.tar.gz  con dentro:
#     manifest     que base, que rol la posee, cuando, con que version de PostgreSQL
#     dump.pgc     pg_dump en formato custom -- permite restaurar una sola tabla
#     filestore/   los adjuntos de esa base
#
# Complementa al snapshot diario de la VM, no lo reemplaza: el snapshot cubre perder la
# maquina, esto cubre recuperar una tabla sin levantar una VM entera, y es un dominio de
# falla distinto (un snapshot copia fielmente la corrupcion logica que tenga la base).
#
# La version anterior de este archivo estaba destruida: alguien expandio sus variables el
# 2025-08-26 y guardo el resultado, dejando `if [ 0 -ne 2 ]` y `for DB in ; do`. No solo no
# respaldaba: no era sintaxis valida. Nadie se entero porque nada lo avisa.
set -euo pipefail

cd "$(dirname "$0")"

BACKUPDIR="./database"
FILESTOREDIR="./data/filestore"
KEEP="${KEEP:-14}"

if [ $# -lt 1 ] || [ $# -gt 2 ]; then
    cat >&2 <<USAGE
Uso: $(basename "$0") <base> [rol]
     Si se omite el rol, se usa el dueño actual de la base.
     KEEP=<n> conserva solo los n respaldos mas recientes de esa base (0 = todos).
Ejemplo: $(basename "$0") cm-prod-18.0
USAGE
    exit 1
fi

DB="$1"
DATE="$(date +%Y%m%d-%H%M%S)"

if ! psql -d postgres -X -t -A -c "SELECT 1 FROM pg_database WHERE datname = '$DB'" | grep -q 1; then
    echo "No existe la base '$DB'." >&2
    exit 1
fi

OWNER="${2:-$(psql -d postgres -X -t -A -c \
    "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = '$DB'")}"

STAGE="$(mktemp -d -t dbbackup-XXXXXX)"
trap 'rm -rf "$STAGE"' EXIT

echo "Respaldando '$DB' (dueño: $OWNER)"
mkdir -p "$BACKUPDIR"

echo "  volcando la base..."
pg_dump -Fc -Z6 -f "$STAGE/dump.pgc" "$DB"

echo "  verificando el volcado..."
TABLES=$(pg_restore -l "$STAGE/dump.pgc" | grep -c "TABLE DATA" || true)
if [ "$TABLES" -lt 1 ]; then
    echo "  el volcado no contiene datos -- abortando sin dejar archivo" >&2
    exit 1
fi
echo "  $TABLES tablas con datos"

if [ -d "$FILESTOREDIR/$DB" ]; then
    echo "  copiando filestore..."
    cp -a "$FILESTOREDIR/$DB" "$STAGE/filestore"
else
    echo "  (sin filestore en $FILESTOREDIR/$DB)"
    mkdir -p "$STAGE/filestore"
fi

cat > "$STAGE/manifest" <<MANIFEST
database=$DB
owner=$OWNER
created=$(date --iso-8601=seconds)
host=$(hostname)
pg_version=$(psql -d postgres -X -t -A -c "SHOW server_version")
tables_with_data=$TABLES
MANIFEST

OUT="$BACKUPDIR/$DB-$DATE.tar.gz"
echo "  empaquetando..."
tar czf "$OUT" -C "$STAGE" manifest dump.pgc filestore

echo "Listo: $OUT ($(du -h "$OUT" | cut -f1))"

if [ "$KEEP" -gt 0 ]; then
    # shellcheck disable=SC2012
    OLD=$(ls -1t "$BACKUPDIR/$DB"-*.tar.gz 2>/dev/null | tail -n +$((KEEP + 1)) || true)
    if [ -n "$OLD" ]; then
        echo "Purgando respaldos viejos (conservando $KEEP):"
        echo "$OLD" | while read -r f; do echo "  - $f"; rm -f "$f"; done
    fi
fi
