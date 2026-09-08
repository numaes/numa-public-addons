#!/bin/bash
# Sin shebang, el `@reboot /bin/bash -c .../onboot.sh` del crontab termina ejecutando
# esto con /bin/sh (dash), que no conoce `source`: el venv no se activa y odoo-bin muere
# con ModuleNotFoundError. $CWD se interpola aca a proposito: cron arranca en otro
# directorio y necesita la ruta absoluta.
cd "/opt/cm-18.0" || exit 1
source venv/bin/activate
exec ./start.sh --pidfile=running-odoo.pid --logfile=log/odoo-server.log
