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
exec ../numa-public-odoo-18.0-numa/odoo-bin -c "$CURRENT_DIR/odoo.config" "$@"
