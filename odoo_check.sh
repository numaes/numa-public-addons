#!/bin/bash
# Revisa una instalacion de Odoo ya hecha y, si se lo pedis, la corrige.
#
#     ./odoo_check.sh [ruta]            solo informa, no toca nada
#     ./odoo_check.sh [ruta] --fix      aplica las correcciones, con backup de cada archivo
#
# Para que existe: los scripts de arranque, parada y respaldo los emite odoo_install.sh, y
# durante años los emitio mal -- heredocs sin comillas en el delimitador, asi que el shell
# expandia cada $VAR al GENERAR y lo que quedaba en disco eran valores congelados del
# momento de la instalacion. El dbbackup.sh de produccion estuvo mas de un año imprimiendo
# su mensaje de uso y saliendo, sin respaldar nada y sin que nada lo avisara. Cada
# instalacion viva tiene su propia copia de ese daño.
#
# No duplica los scripts: los extrae de odoo_install.sh, que esta al lado y es la unica
# fuente. Si los dos archivos se separan, no hay forma de que se separen en silencio.
#
# Lo que NO toca nunca: admin_passwd, addons_path, db_user, puertos, data_dir -- todo lo
# propio de la instalacion. De odoo.config solo ajusta las claves de dimensionamiento, y
# una por una.
set -uo pipefail

SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
INSTALLER="$SELF_DIR/odoo_install.sh"

TARGET="."
FIX=0
for a in "$@"; do
    case "$a" in
        --fix) FIX=1 ;;
        -h|--help) sed -n '2,20p' "$0" | sed 's/^# \?//'; exit 0 ;;
        *) TARGET="$a" ;;
    esac
done

[ -f "$INSTALLER" ] || { echo "No encuentro $INSTALLER" >&2; exit 1; }
cd "$TARGET" 2>/dev/null || { echo "No puedo entrar a '$TARGET'" >&2; exit 1; }
INSTALL_DIR="$(pwd)"

echo "Instalacion: $INSTALL_DIR"
[ -f odoo.config ] || { echo "  No hay odoo.config aca. ¿Es el directorio de una instalacion?" >&2; exit 1; }

# --- averiguar la version desde el arbol de Odoo que tiene al lado --------------------
OE_VERSION=""
for d in ../numa-public-odoo-*-numa; do
    [ -d "$d" ] || continue
    v="${d##*/numa-public-odoo-}"; v="${v%-numa}"
    OE_VERSION="$v"
done
if [ -z "$OE_VERSION" ]; then
    OE_VERSION="$(sed -n 's|.*numa-public-odoo-\([0-9.]*\)-numa.*|\1|p' odoo.config | head -1)"
fi
[ -n "$OE_VERSION" ] || { echo "  No pude deducir la version de Odoo." >&2; exit 1; }
echo "Version de Odoo: $OE_VERSION"
echo

ISSUES=0
FIXED=0
note ()  { printf '  %-8s %s\n' "$1" "$2"; }
bad ()   { note "REVISAR" "$1"; ISSUES=$((ISSUES + 1)); }
good ()  { note "ok" "$1"; }
did ()   { note "CORREGI" "$1"; FIXED=$((FIXED + 1)); }

backup () { cp -a "$1" "$1.bak-$(date +%Y%m%d-%H%M%S)"; }

# --------------------------------------------------------------------------------------
# 1. los scripts generados
# --------------------------------------------------------------------------------------
WORK="$(mktemp -d -t odoo-check-XXXXXX)"
trap 'rm -rf "$WORK"' EXIT

# Extraer los bloques `cat ... > ./<nombre> <<DELIM` del instalador y correrlos con los
# valores de ESTA instalacion.
awk '
    !inblock {
        if ($0 ~ /^[[:space:]]*cat[[:space:]].*>[[:space:]]*\.\/[A-Za-z0-9._-]+/ &&
            match($0, /<<[[:space:]]*'"'"'?[A-Za-z0-9_]+'"'"'?/)) {
            d = substr($0, RSTART + 2, RLENGTH - 2)
            gsub(/[[:space:]]|'"'"'/, "", d)
            delim = d; inblock = 1; print; next
        }
        next
    }
    { print }
    $0 == delim { inblock = 0 }
' "$INSTALLER" > "$WORK/generate.sh"

( cd "$WORK" && OE_VERSION="$OE_VERSION" CWD="$INSTALL_DIR" bash generate.sh ) 2>/dev/null

# --- autodefensa ----------------------------------------------------------------------
# Este script vale exactamente lo que valga el odoo_install.sh que tiene al lado. Corrido
# desde un checkout viejo reescribiria scripts buenos con los rotos, que es peor que no
# hacer nada. Asi que antes de tocar nada se verifica lo que el instalador acaba de emitir.
for f in start.sh stop.sh onboot.sh dbbackup.sh dbrestore.sh; do
    src="$WORK/$f"
    problema=""
    [ -f "$src" ] || problema="no lo genero"
    if [ -f "$src" ]; then
        bash -n "$src" 2>/dev/null              || problema="no es sintaxis valida"
        [ "$(head -1 "$src")" = "#!/bin/bash" ] || problema="sale sin shebang"
        grep -qE '^\s*if \[ [0-9]+ -ne [0-9]+ \]' "$src" && problema="sale con las variables expandidas"
        grep -qE '^\s*for [A-Z_]+ in ;'            "$src" && problema="sale con una lista vacia"
    fi
    if [ -n "$problema" ]; then
        echo "  ABORTA: el odoo_install.sh de $SELF_DIR emite un $f que $problema." >&2
        echo "          Este checkout de numa-public-addons esta desactualizado; corregirlo" >&2
        echo "          desde aca dejaria la instalacion peor. Actualiza el repo primero:" >&2
        echo "              git -C $SELF_DIR pull" >&2
        exit 2
    fi
done

echo "Scripts:"
for f in start.sh stop.sh onboot.sh dbbackup.sh dbrestore.sh; do
    [ -f "$WORK/$f" ] || { bad "$f: el instalador no lo genero (¿bloque renombrado?)"; continue; }
    if [ ! -f "$f" ]; then
        if [ "$FIX" -eq 1 ]; then
            cp "$WORK/$f" "$f"; chmod +x "$f"; did "$f: no existia, lo cree"
        else
            bad "$f: no existe"
        fi
    elif diff -q "$f" "$WORK/$f" >/dev/null 2>&1; then
        good "$f"
    else
        # Decir POR QUE difiere, no solo que difiere.
        why=""
        grep -qE '^\s*if \[ [0-9]+ -ne [0-9]+ \]' "$f" && why="$why variables expandidas al generar;"
        grep -qE '^\s*for [A-Z_]+ in ;'           "$f" && why="$why lista vacia (no es sintaxis valida);"
        [ "$(head -1 "$f")" != "#!/bin/bash" ]          && why="$why sin shebang;"
        # kill -9 solo es sintoma si NO hay un SIGTERM antes: el stop.sh correcto lo usa
        # como ultimo recurso despues de esperar 30s.
        grep -q 'kill -9' "$f" && ! grep -q 'kill -TERM' "$f" && why="$why apaga con kill -9 directo;"
        # Buscar procesos por patron de nombre alcanza a los ambientes vecinos, que corren
        # el mismo odoo-bin desde directorios hermanos.
        grep -qE 'pkill|killall' "$f" && why="$why mata por patron (alcanza a otros ambientes);"
        [ "$f" = "start.sh" ] && ! grep -q 'CURRENT_DIR' "$f" && why="$why no identifica el ambiente en ps;"
        [ -z "$why" ] && why=" difiere del generador"
        if [ "$FIX" -eq 1 ]; then
            backup "$f"; cp "$WORK/$f" "$f"; chmod +x "$f"; did "$f:$why reemplazado (backup guardado)"
        else
            bad "$f:$why"
        fi
    fi
done

# --------------------------------------------------------------------------------------
# 2. odoo.config: solo las claves de dimensionamiento, una por una
# --------------------------------------------------------------------------------------
echo
echo "odoo.config (dimensionamiento):"
cfg () { sed -n "s/^[[:space:]]*$1[[:space:]]*=[[:space:]]*//p" odoo.config | head -1; }
set_cfg () {  # set_cfg <clave> <valor> <por-que>
    if [ "$FIX" -eq 1 ]; then
        [ "$CFG_BACKED" = "0" ] && { backup odoo.config; CFG_BACKED=1; }
        if grep -qE "^[[:space:]]*$1[[:space:]]*=" odoo.config; then
            sed -i -E "s|^[[:space:]]*$1[[:space:]]*=.*|$1 = $2|" odoo.config
        else
            printf '%s = %s\n' "$1" "$2" >> odoo.config
        fi
        did "$1 -> $2 ($3)"
    else
        bad "$1: $3 (deberia ser $2)"
    fi
}
CFG_BACKED=0

CORES=$(nproc 2>/dev/null || echo 2)
WANT_WORKERS=$(( CORES * 2 + 1 )); [ "$WANT_WORKERS" -gt 9 ] && WANT_WORKERS=9
W="$(cfg workers)"
if [ -z "$W" ] || [ "$W" -lt 1 ] 2>/dev/null; then
    set_cfg workers "$WANT_WORKERS" "sin workers Odoo corre en un solo proceso: no hay pool"
    # Contra el valor que VA a tener, no contra el que tiene: en modo informe todavia no se
    # escribio, y derivar db_maxconn de workers=0 proponia 45 en vez de 8.
    W="$WANT_WORKERS"
else
    good "workers = $W"
fi

WANT_MAXCONN=$(( 90 / (W + 2) ))
MAXC="$(cfg db_maxconn)"
if [ -z "$MAXC" ] || [ $(( MAXC * (W + 2) )) -gt 90 ] 2>/dev/null; then
    set_cfg db_maxconn "$WANT_MAXCONN" "es POR PROCESO: ${MAXC:-64} x ($W workers + 2 crons) supera las 100 de PostgreSQL"
else
    good "db_maxconn = $MAXC (x $((W + 2)) procesos = $(( MAXC * (W + 2) )) <= 90)"
fi

HARD="$(cfg limit_memory_hard)"; SOFT="$(cfg limit_memory_soft)"
if [ -z "$HARD" ] || [ "$HARD" -lt 2147483648 ] 2>/dev/null; then
    set_cfg limit_memory_hard 4294967296 "wkhtmltopdf lo hereda como RLIMIT_AS; con menos de 2 GB Qt se queda sin espacio"
else
    good "limit_memory_hard = $HARD"
fi
HARD="$(cfg limit_memory_hard)"
if [ -z "$SOFT" ] || [ "$SOFT" -ge "$HARD" ] 2>/dev/null; then
    set_cfg limit_memory_soft 2147483648 "el blando debe ser MENOR que el duro, si no el reciclado ordenado nunca ocurre"
else
    good "limit_memory_soft = $SOFT (< $HARD)"
fi

TREAL="$(cfg limit_time_real)"
WANT_TREAL=900
if [ -z "$TREAL" ] || [ "$TREAL" -gt 1800 ] 2>/dev/null; then
    set_cfg limit_time_real "$WANT_TREAL" "${TREAL:-7200}s retiene el worker demasiado tiempo cuando algo se traba"
else
    good "limit_time_real = $TREAL"
    WANT_TREAL="$TREAL"
fi
# Contra el valor que limit_time_real VA a tener, no contra el que tiene: en modo informe
# todavia no se escribio, y calcular sobre un valor vacio proponia limit_time_cpu = 0.
TCPU="$(cfg limit_time_cpu)"
if [ -z "$TCPU" ] || [ "$TCPU" -ge "$WANT_TREAL" ] 2>/dev/null; then
    set_cfg limit_time_cpu $(( WANT_TREAL * 2 / 3 )) "debe quedar por debajo de limit_time_real ($WANT_TREAL)"
else
    good "limit_time_cpu = $TCPU (< $WANT_TREAL)"
fi

if [ "${OE_VERSION%%.*}" -ge 16 ] 2>/dev/null && grep -qE '^[[:space:]]*longpolling_port' odoo.config; then
    bad "longpolling_port: en Odoo >= 16 la opcion es gevent_port (es inerte, no urge)"
fi

# --------------------------------------------------------------------------------------
# 3. entorno: cosas que no estan en ningun archivo de esta instalacion
# --------------------------------------------------------------------------------------
echo
echo "Este ambiente:"
if [ -f running-odoo.pid ]; then
    PID=$(cat running-odoo.pid)
    if ! kill -0 "$PID" 2>/dev/null; then
        bad "running-odoo.pid apunta al pid $PID, que ya no corre (pidfile viejo)"
    elif tr '\0' ' ' < "/proc/$PID/cmdline" 2>/dev/null | grep -qF "$INSTALL_DIR/odoo.config"; then
        good "corriendo: pid $PID, $(pgrep -P "$PID" 2>/dev/null | wc -l) procesos hijos, identificable en ps"
    else
        # Un Odoo lanzado con el start.sh anterior no lleva la ruta absoluta del config, asi
        # que stop.sh -- que se niega a matar lo que no puede probar que es suyo -- no va a
        # poder pararlo. Es seguro, pero hay que saberlo.
        bad "corriendo (pid $PID) pero SIN la ruta absoluta del config en su linea de comandos:"
        note "" "      lo lanzo un start.sh anterior. stop.sh no va a poder pararlo."
        note "" "      Pararlo a mano una vez (kill -TERM $PID) y volver a arrancar."
    fi
else
    note "-" "no hay running-odoo.pid: este ambiente no esta corriendo, o se lanzo sin --pidfile"
fi

echo
echo "Entorno (solo informa, no lo corrige este script):"
if [ "$(swapon --show --noheadings 2>/dev/null | wc -l)" -eq 0 ]; then
    bad "sin swap: cualquier pico de memoria es una muerte inmediata en vez de degradacion"
else
    good "swap: $(swapon --show=SIZE --noheadings 2>/dev/null | tr -d ' \n')"
fi
SWAPPINESS=$(cat /proc/sys/vm/swappiness 2>/dev/null || echo '?')
[ "$SWAPPINESS" = "0" ] && bad "vm.swappiness = 0 anula el swap que exista"

if crontab -l 2>/dev/null | grep -q "@reboot.*$INSTALL_DIR/onboot.sh"; then
    good "@reboot en el crontab: vuelve sola tras un reinicio de la maquina"
else
    bad "sin @reboot en el crontab -- agregar: @reboot /bin/bash $INSTALL_DIR/onboot.sh"
fi

# El @reboot solo cubre el reinicio de la maquina. Si el master muere por cualquier otra
# razon no lo levanta nadie, y una caida de diez minutos se vuelve una de diez horas.
if crontab -l 2>/dev/null | grep -q -- "--si-no-corre.*$INSTALL_DIR/onboot.sh\|$INSTALL_DIR/onboot.sh.*--si-no-corre"; then
    good "supervision en el crontab: si el master muere, vuelve solo"
else
    bad "sin supervision -- agregar: */5 * * * * /bin/bash $INSTALL_DIR/onboot.sh --si-no-corre"
fi

LAST=$(ls -1t database/*.tar.gz 2>/dev/null | head -1)
if [ -n "$LAST" ]; then
    if find "$LAST" -mtime +7 2>/dev/null | grep -q .; then
        bad "ultimo respaldo local: $(basename "$LAST") -- hace mas de 7 dias"
    else
        good "ultimo respaldo local: $(basename "$LAST")"
    fi
else
    bad "sin respaldos locales en database/ -- probar: ./dbbackup.sh <base>"
fi

# --------------------------------------------------------------------------------------
echo
if [ "$FIX" -eq 1 ]; then
    echo "Corregido: $FIXED. Pendiente de revision: $ISSUES."
    [ "$FIXED" -gt 0 ] && echo "Los archivos originales quedaron como *.bak-<fecha>. Reinicia Odoo para tomar odoo.config."
else
    if [ "$ISSUES" -eq 0 ]; then
        echo "Todo en orden."
    else
        echo "$ISSUES cosa(s) para revisar. Para aplicar las correcciones: $0 $TARGET --fix"
    fi
fi
exit 0
