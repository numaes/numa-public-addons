#!/bin/bash
# El shebang no es decorativo: sin el, ./start.sh lo toma dash, que no conoce
# `source`, no activa el venv y odoo-bin muere con ModuleNotFoundError: babel.
cd "$(dirname "$0")"
# La ruta absoluta al config es lo que hace identificable el ambiente en `ps`: varios
# ambientes (produccion, prueba) conviven como directorios hermanos y todos lanzan el mismo
# odoo-bin. Es tambien lo que usa stop.sh para no apagar el ambiente equivocado.
# Se calcula en EJECUCION (de ahi los $ escapados): resolverlo al generar dejaria clavada
# la ruta de la maquina donde se corrio el instalador.
CURRENT_DIR="$(pwd)"
source venv/bin/activate

# Arrancar es el fin del mantenimiento.
rm -f mantenimiento.lock

# Que hay corriendo aca. El addons_path es una lista de directorios y nada en Odoo
# registra en que commit esta cada uno, asi que "que version esta desplegada" termina
# siendo arqueologia. Se escribe en cada arranque, que es el unico momento en que la
# respuesta es exacta. Tambien deja anotado el venv: si el ambiente se clono copiando el
# directorio, el venv copiado sigue apuntando al original y aca se ve.
{
    echo "arrancado:  $(date -Is)"
    echo "venv:       $(python3 -c 'import sys; print(sys.prefix)' 2>/dev/null)"
    echo "--- repositorios ---"
    SEEN=""
    for d in "$CURRENT_DIR" "$CURRENT_DIR"/*/ "$CURRENT_DIR"/../*/; do
        [ -d "$d/.git" ] || continue
        p="$(cd "$d" && pwd)"
        case " $SEEN " in *" $p "*) continue ;; esac
        SEEN="$SEEN $p"
        REV="$(git -C "$p" rev-parse --short HEAD 2>/dev/null)"
        BR="$(git -C "$p" rev-parse --abbrev-ref HEAD 2>/dev/null)"
        printf '%-10s %-14s %s\n' "$REV" "$BR" "$p"
    done
    echo "--- paquetes ---"
    python3 -m pip freeze 2>/dev/null
} > deployed.txt

ODOO_BIN=../numa-public-odoo-18.0-numa/odoo-bin

# odoo-bin CREA la base que nombra -d si no existe, con base instalado y el usuario admin con
# clave "admin". Asi entraron a los servidores de mr-group en 2026, dos veces: alguien corrio
# `./start.sh -d <nombre con un error de tipeo>` (un guion por un guion bajo), Odoo creo una
# base vacia con admin/admin, y un escaner la encontro en minutos. Por eso aca -d solo acepta
# bases que existen. Para crear una a proposito: ./start.sh --crear-base -d <base> [-i modulos]
CREAR_BASE=0
BASES=()
ARGS=()
SIGUIENTE_ES_BASE=0
for a in "$@"; do
    if [ "$SIGUIENTE_ES_BASE" -eq 1 ]; then BASES+=("$a"); SIGUIENTE_ES_BASE=0; ARGS+=("$a"); continue; fi
    case "$a" in
        --crear-base) CREAR_BASE=1; continue ;;
        -d|--database) SIGUIENTE_ES_BASE=1 ;;
        --database=*) BASES+=("${a#--database=}") ;;
        -d?*) BASES+=("${a#-d}") ;;
    esac
    ARGS+=("$a")
done
if [ "${#ARGS[@]}" -eq 0 ]; then set --; else set -- "${ARGS[@]}"; fi
# db_name en el config tiene el mismo efecto que -d.
CFG_DB="$(sed -n 's/^db_name *= *//p' odoo.config | head -1)"
[ "${#BASES[@]}" -eq 0 ] && [ -n "$CFG_DB" ] && [ "$CFG_DB" != "False" ] && BASES+=("$CFG_DB")

FALTAN=()
for lista in "${BASES[@]}"; do
    IFS=',' read -r -a nombres <<< "$lista"
    for b in "${nombres[@]}"; do
        EXISTE="$(psql -X -At -d postgres -v nombre="$b" <<'SQL' 2>/dev/null
SELECT 1 FROM pg_database WHERE datname = :'nombre';
SQL
)"
        # Si PostgreSQL no contesta no se puede saber; odoo-bin fallara solo y con su propio mensaje.
        [ $? -eq 0 ] && [ "$EXISTE" != "1" ] && FALTAN+=("$b")
    done
done

if [ "${#FALTAN[@]}" -gt 0 ] && [ "$CREAR_BASE" -eq 0 ]; then
    echo "No existe la base: ${FALTAN[*]}" >&2
    echo "Odoo la crearia con el usuario admin y clave 'admin'. No arranco." >&2
    echo "Bases que existen:" >&2
    psql -X -At -d postgres -c "SELECT '    ' || datname FROM pg_database WHERE NOT datistemplate AND datname <> 'postgres' ORDER BY 1" >&2
    echo "Si era un error de tipeo, corregi el nombre. Para crearla a proposito:" >&2
    echo "    ./start.sh --crear-base -d ${FALTAN[0]} -i base" >&2
    exit 1
fi

if [ "$CREAR_BASE" -eq 1 ]; then
    [ "${#BASES[@]}" -gt 0 ] || { echo "--crear-base necesita la base: ./start.sh --crear-base -d <base> -i base" >&2; exit 1; }
    [ "${#FALTAN[@]}" -gt 0 ] || { echo "--crear-base: ${BASES[*]} ya existe, no hay nada que crear." >&2; exit 1; }
    # Se crea y se para (--stop-after-init): la base nueva no se sirve ni un segundo con admin/admin.
    # Despues se le pone al admin una clave al azar, que se muestra una sola vez.
    "$ODOO_BIN" -c "$CURRENT_DIR/odoo.config" "$@" --stop-after-init || exit $?
    for b in "${FALTAN[@]}"; do
        CLAVE_ADMIN="$(head -c 1024 /dev/urandom | tr -dc A-Za-z0-9 | head -c 20)"
        # La clave va por el entorno, no por argumentos: los argumentos se ven en ps.
        CLAVE_ADMIN="$CLAVE_ADMIN" "$ODOO_BIN" shell -c "$CURRENT_DIR/odoo.config" -d "$b" --no-http --log-level=warn <<'PY' || exit $?
import os
env.ref('base.user_admin').password = os.environ['CLAVE_ADMIN']
env.cr.commit()
PY
        echo "Base '$b' creada. Usuario admin, clave: $CLAVE_ADMIN"
        echo "Guardala ahora: no se vuelve a mostrar. Arranca el ambiente con ./onboot.sh --si-no-corre"
    done
    exit 0
fi

exec "$ODOO_BIN" -c "$CURRENT_DIR/odoo.config" "$@"
