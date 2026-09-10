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

exec ../numa-public-odoo-18.0-numa/odoo-bin -c "$CURRENT_DIR/odoo.config" "$@"
