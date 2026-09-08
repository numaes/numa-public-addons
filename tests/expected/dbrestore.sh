#!/bin/bash
# Restaura un respaldo hecho por dbbackup.sh: base + filestore.
#
# Uso:   ./dbrestore.sh <base-destino> <archivo.tar.gz> [rol] [--production]
#
# POR DEFECTO LA COPIA SE NEUTRALIZA. Una restauracion de produccion en otra base sigue
# teniendo dentro los servidores de correo, los cron y el uuid de la original: apenas Odoo
# la abre empieza a mandar mails reales a clientes reales y a correr integraciones. Asi que
# salvo que pases --production, este script deja la copia:
#     - con un database.uuid nuevo        (no se hace pasar por la original)
#     - sin fecha de expiracion heredada
#     - con los cron desactivados
#     - con los servidores de correo entrante y saliente desactivados
# La version original de este archivo tenia esas tres lineas escritas y comentadas; el
# autor sabia del problema. Aca estan activas y ademas cubren correo y cron.
#
# Usa --production solo para restaurar sobre la base que realmente atiende usuarios.
set -euo pipefail

cd "$(dirname "$0")"

DATA_PATH="./data"
PRODUCTION=0
ARGS=()
for a in "$@"; do
    if [ "$a" = "--production" ]; then PRODUCTION=1; else ARGS+=("$a"); fi
done
set -- "${ARGS[@]:-}"

if [ $# -lt 2 ] || [ $# -gt 3 ]; then
    cat >&2 <<USAGE
Uso: $(basename "$0") <base-destino> <archivo.tar.gz> [rol] [--production]
     Sin --production la copia se neutraliza (uuid nuevo, cron y correo apagados).
Ejemplo: $(basename "$0") cm-restore-test ./database/cm-prod-18.0-20260908-124639.tar.gz
USAGE
    exit 1
fi

DB="$1"
BACKUP_FILE="$2"

[ -f "$BACKUP_FILE" ] || { echo "No existe el archivo '$BACKUP_FILE'." >&2; exit 1; }

if psql -d postgres -X -t -A -c "SELECT 1 FROM pg_database WHERE datname = '$DB'" | grep -q 1; then
    echo "La base '$DB' ya existe. Borrala primero si de verdad la queres reemplazar:" >&2
    echo "    dropdb '$DB'" >&2
    exit 1
fi

STAGE="$(mktemp -d -t dbrestore-XXXXXX)"
trap 'rm -rf "$STAGE"' EXIT

echo "Desempaquetando $BACKUP_FILE"
tar xzf "$BACKUP_FILE" -C "$STAGE"
[ -f "$STAGE/dump.pgc" ] || { echo "El archivo no contiene dump.pgc -- ¿es un respaldo de dbbackup.sh?" >&2; exit 1; }

[ -f "$STAGE/manifest" ] && { echo "Manifiesto del respaldo:"; sed 's/^/  /' "$STAGE/manifest"; }

OWNER="${3:-$(sed -n 's/^owner=//p' "$STAGE/manifest" 2>/dev/null)}"
OWNER="${OWNER:-$(whoami)}"

echo "Creando la base '$DB' (dueño: $OWNER)"
createdb -O "$OWNER" --encoding=UNICODE -T template0 "$DB"

echo "Restaurando el volcado..."
pg_restore -d "$DB" --no-owner --role="$OWNER" -j 2 "$STAGE/dump.pgc" 2>&1 | grep -v "^$" || true

echo "Restaurando el filestore..."
mkdir -p "$DATA_PATH/filestore"
rm -rf "${DATA_PATH:?}/filestore/$DB"
if [ -d "$STAGE/filestore" ]; then
    cp -a "$STAGE/filestore" "$DATA_PATH/filestore/$DB"
else
    mkdir -p "$DATA_PATH/filestore/$DB"
fi

if [ "$PRODUCTION" -eq 1 ]; then
    echo
    echo "*** --production: la copia queda TAL CUAL. Cron y correo activos, uuid original."
else
    echo "Neutralizando la copia..."
    psql -d "$DB" -X -q <<'SQL'
UPDATE ir_config_parameter SET value = gen_random_uuid()::text WHERE key = 'database.uuid';
DELETE FROM ir_config_parameter WHERE key IN ('database.expiration_date','database.expiration_reason');
DO $$
BEGIN
    IF to_regclass('ir_cron') IS NOT NULL THEN
        UPDATE ir_cron SET active = false;
    END IF;
    IF to_regclass('ir_mail_server') IS NOT NULL THEN
        UPDATE ir_mail_server SET active = false;
    END IF;
    IF to_regclass('fetchmail_server') IS NOT NULL THEN
        UPDATE fetchmail_server SET active = false, state = 'draft';
    END IF;
END $$;
SQL
    echo "  uuid nuevo, cron y servidores de correo desactivados."
    echo "  Para reactivarlos en la copia, hacelo a mano y a conciencia."
fi

echo
echo "Listo. Base '$DB' restaurada. Arrancala con:"
echo "    ./start.sh -d '$DB'"
