#!/bin/bash
# El shebang no es decorativo: sin el, ./start.sh lo toma dash, que no conoce
# `source`, no activa el venv y odoo-bin muere con ModuleNotFoundError: babel.
cd "$(dirname "$0")"
source venv/bin/activate
exec ../numa-public-odoo-18.0-numa/odoo-bin -c odoo.config "$@"
