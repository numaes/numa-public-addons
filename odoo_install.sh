#!/bin/bash
################################################################################
# Script for installing Odoo on Ubuntu 18.04 an 20.04 could be used for other version too
# Author: Yenthe Van Ginneken
# Modified by NUMA for specific use
#
#-------------------------------------------------------------------------------
# This script will install Odoo on your Ubuntu 16.04 server. It can install multiple Odoo instances
# in one Ubuntu because of the different xmlrpc_ports
#-------------------------------------------------------------------------------
# Make a new file:
# sudo nano odoo-install.sh
# Place this content in it and then make the file executable:
# sudo chmod +x odoo-install.sh
# Execute the script to install Odoo:
# ./odoo-install
################################################################################

OE_USER="$USER"
OE_HOME=$(pwd)
# The default port where this Odoo instance will run under provided you use the command -c in the terminal
# Set to true if you want to install it, false if you don't need it or have it already installed.
read -r -e -p "Install WkmhtmlToPdf [True/False]: " -i "False" INSTALL_WKHTMLTOPDF

# Set the default Odoo port you still have to use -c /etc/odoo-server.conf for example to use this.
read -r -e -p "Odoo port number: " -i "8069" OE_PORT

# Set the default Odoo longpolling port you still have to use -c /etc/odoo-server.conf for example to use this.
read -r -e -p "Odoo longpolling port: " -i "8072" LONGPOLLING_PORT

# Choose the Odoo version which you want to install. For example: 13.0, 12.0, 11.0 or saas-18. When using 'master' the master version will be installed.
# IMPORTANT! This script contains extra libraries that are specifically needed for Odoo 13.0
read -r -e -p "Odoo version: " -i "18.0" OE_VERSION

# Set this to True if you want to install the Odoo enterprise version!
read -r -e -p "Is enterprise? [True/False]: " -i "False" IS_ENTERPRISE

# Set this to True if you want to install the Odoo enterprise version!
read -r -e -p "Install NUMA's private repository? [True/False]: " -i "False" INSTALL_PRIVATE

# Set this to True if you want to install Nginx!
read -r -e -p "Install Nginx? [True/False]: " -i "False" INSTALL_NGINX

WEBSITE_NAME='site@domain'
ENABLE_SSL='False'
ADMIN_EMAIL='odoo@example.com'

if [ "$INSTALL_NGINX" = "True" ]; then
  # Set the website name
  read -r -e -p "Website name: " -i "www.odoo_website.com" WEBSITE_NAME

  # Set to "True" to install certbot and have ssl enabled, "False" to use http
  read -r -e -p "Enable SSL? [True/False]: " -i "False" ENABLE_SSL

  # Provide Email to register ssl certificate
  read -r -e -p "Email for ssl certificate: " -i "odoo@example.com" ADMIN_EMAIL

fi

# Set the superadmin password - if GENERATE_RANDOM_PASSWORD is set to "True" we will automatically generate a random password, otherwise we use this one
read -r -e -p "Superadmin name: " -i "admin" OE_SUPERADMIN

# Set to "True" to generate a random password, "False" to use the variable in OE_SUPERADMIN
read -r -e -p "Generate random password for admin? [True/False]: " -i "False" GENERATE_RANDOM_PASSWORD

# Project name
read -r -e -p "Project name (blank if no project): " PROJECT

PROJECT_REPO='False'
if [ "$PROJECT" != "" ]; then
  # Project repo
  read -r -e -p "Use a project repository? [True/False]: " -i "True" PROJECT_REPO
fi

#--------------------------------------------------
# Update Server
#--------------------------------------------------
echo -e "\n---- Update Server ----"
sudo apt-get update
sudo apt-get upgrade -y

#--------------------------------------------------
# Install PostgreSQL Server
#--------------------------------------------------
echo -e "\n---- Install PostgreSQL Server ----"
sudo apt-get install postgresql postgresql-contrib postgresql-client postgresql-client-common postgresql-server-dev-all libpq-dev -y
sudo -u postgres createuser -s "$USER"

echo -e "\n---- Creating the ODOO PostgreSQL User  ----"
createuser -s "pg-$PROJECT-$OE_VERSION"

#--------------------------------------------------
# Install Dependencies
#--------------------------------------------------
echo -e "\n--- Installing Python 3 + pip3 --"
sudo apt-get install git swig -y
sudo apt install libssl-dev libffi-dev libmysqlclient-dev libblas-dev libatlas-base-dev -y
sudo apt-get install python3 python3-pip build-essential wget python3-dev python3-venv python3-wheel liblcms2-dev -y
sudo apt-get install libxslt1-dev zlib1g-dev libzip-dev libldap2-dev libsasl2-dev python3-setuptools -y
sudo apt-get install node-less libjpeg-dev -y
sudo apt-get install libxml2-dev libxmlsec1-dev -y

echo -e "\n---- Install virtual env in current directory ----"

echo -e "\n---- Installing nodeJS NPM and rtlcss for LTR support ----"
sudo apt-get install nodejs npm -y
sudo npm install -g rtlcss

if [ ! -e /usr/bin/node ] && [ -e /usr/bin/nodejs ]; then
  echo -e "\n--- Create symlink for node"
  sudo ln -s /usr/bin/nodejs /usr/bin/node
fi

#--------------------------------------------------
# Install Wkhtmltopdf if needed
#--------------------------------------------------
##
###  WKHTMLTOPDF download links

if [ "$INSTALL_WKHTMLTOPDF" = "True" ]; then
  echo -e "\n---- Install wkhtml and place shortcuts on correct place for ODOO $OE_VERSION ----"
  wget https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6.1-3/wkhtmltox_0.12.6.1-3.jammy_amd64.deb
  sudo apt install xfonts-75dpi xfonts-base fontconfig libjpeg62-turbo
  sudo dpkg -i wkhtmltox_0.12.6.1-3.jammy_amd64.deb
  sudo ln -s /usr/local/bin/wkhtmltopdf /usr/bin/wkhtmltopdf
  sudo ln -s /usr/local/bin/wkhtmltoimage /usr/bin/wkhtmltoimage
fi

#--------------------------------------------------
# Install ODOO
#--------------------------------------------------
echo -e "\n==== Installing numa-public-odoo Server ===="
if [ ! -d "numa-public-odoo-$OE_VERSION-numa" ]; then
  git clone https://github.com/numaes/numa-public-odoo -b "$OE_VERSION-numa" "numa-public-odoo-$OE_VERSION-numa"
fi

echo -e "\n==== Installing numa-public-addons ===="
if [ ! -d "numa-public-addons-$OE_VERSION" ]; then
  git clone https://github.com/numaes/numa-public-addons -b "$OE_VERSION" "numa-public-addons-$OE_VERSION"
fi

echo -e "\n==== Installing extra-addons ===="
if [ ! -d "extra-addons-$OE_VERSION" ]; then
  git clone https://github.com/numaes/extra-addons -b "$OE_VERSION" "extra-addons-$OE_VERSION"
fi

#--------------------------------------------------
# Install NUMA private addons
#--------------------------------------------------

if [ "$INSTALL_PRIVATE" = "True" ]; then
  echo -e "\n==== Installing numa-addons Server ===="
  if [ ! -d "numa-addons-$OE_VERSION" ]; then
    GITHUB_RESPONSE="Authentication"
    while [[ $GITHUB_RESPONSE == *"Authentication"* ]]; do
        echo "------------------------WARNING------------------------------"
        echo "Your authentication with NUMA numa-addons has failed! Please try again."
        echo "TIP: Press ctrl+c to stop this script."
        echo "-------------------------------------------------------------"
        echo " "
        GITHUB_RESPONSE=$(git clone https://github.com/numaes/numa-addons -b "$OE_VERSION" "numa-addons-$OE_VERSION" 2>&1)
    done
  fi

  echo -e "\n==== Installing numa_l10n_ar Server ===="
  if [ ! -d "numa_l10n_ar-$OE_VERSION" ]; then
    GITHUB_RESPONSE="Authentication"
    while [[ $GITHUB_RESPONSE == *"Authentication"* ]]; do
        echo "------------------------WARNING------------------------------"
        echo "Your authentication with NUMA numa_l10n_ar has failed! Please try again."
        echo "TIP: Press ctrl+c to stop this script."
        echo "-------------------------------------------------------------"
        echo " "
        GITHUB_RESPONSE=$(git clone https://github.com/numaes/numa_l10n_ar -b "$OE_VERSION" "numa_l10n_ar-$OE_VERSION" 2>&1)
    done
  fi
fi

if [ "$IS_ENTERPRISE" = "True" ]; then
    # Odoo Enterprise install!

    GITHUB_RESPONSE=$(git clone --depth 1 --branch "$OE_VERSION" https://www.github.com/odoo/enterprise "enterprise-$OE_VERSION" 2>&1)
    while [[ $GITHUB_RESPONSE == *"Authentication"* ]]; do
        echo "------------------------WARNING------------------------------"
        echo "Your authentication with Github has failed! Please try again."
        echo "In order to clone and install the Odoo enterprise version you"
        echo "need to be an offical Odoo partner and you need access to"
        echo "nhttp://github.com/odoo/enterprise."
        echo "TIP: Press ctrl+c to stop this script."
        echo "-------------------------------------------------------------"
        echo " "
        GITHUB_RESPONSE=$(git clone --depth 1 --branch "$OE_VERSION" https://www.github.com/odoo/enterprise "$OE_HOME/enterprise/addons" 2>&1)
    done

    sudo -H pip3 install num2words ofxparse dbfread ebaysdk firebase_admin pyOpenSSL
    sudo npm install -g less
    sudo npm install -g less-plugin-clean-css
fi

# Mejora: Definir variables para las rutas al principio
ODOO_ROOT="$OE_HOME/$PROJECT-$OE_VERSION"
LOG_DIR="$ODOO_ROOT/log"
DATA_DIR="$ODOO_ROOT/data"
DATABASE_DIR="$ODOO_ROOT/database"

if [ "$PROJECT" != "" ]; then
  if [ -n "$PROJECT" ]; then
    # Create project environment
    
    echo -e "\n==== Installing project-addons ===="
    # Mejora: Usar las variables de directorio definidas al principio
    mkdir -p "$ODOO_ROOT"
    cd "$ODOO_ROOT" || exit

    if [ ! -d "$PROJECT-addons-$OE_VERSION" ] && [ "$PROJECT_REPO" = "True" ]; then
      git clone "https://github.com/numaes/$PROJECT-addons" -b "$OE_VERSION" "$PROJECT-addons-$OE_VERSION"
    fi

    # Mejora: Usar variables para crear directorios
    mkdir -p "$LOG_DIR"
    mkdir -p "$DATA_DIR"
    mkdir -p "$DATABASE_DIR"

    if [ ! -d venv ]; then
      echo -e "\n---- Install virtual env in current directory ----"
      python3 -m venv venv
    fi

    source venv/bin/activate
    # setup/ es del arbol de Odoo, no del directorio del proyecto: aca el cwd es
    # $ODOO_ROOT, que solo tiene venv, log, data, database y los addons del proyecto.
    # `sudo ./setup/debinstall.sh` fallaba con "No such file or directory" en cada
    # instalacion, y las dependencias de sistema terminaban poniendose a mano.
    sudo "../numa-public-odoo-$OE_VERSION-numa/setup/debinstall.sh"

    # --- dimensionamiento -------------------------------------------------------------
    # Todas nuestras instalaciones son de 16 GB. Los workers salen de la regla de Odoo
    # (2 x nucleos + 1), con tope 9 para dejar aire a PostgreSQL en la misma maquina.
    #
    # db_maxconn se deriva de los workers porque es POR PROCESO, no global: con el valor
    # suelto de 64 y 7 workers se piden hasta 448 conexiones contra el max_connections=100
    # que trae PostgreSQL por defecto. Los +2 son los hilos de cron.
    OE_CORES=$(nproc 2>/dev/null || echo 2)
    OE_WORKERS=$(( OE_CORES * 2 + 1 ))
    [ "$OE_WORKERS" -gt 9 ] && OE_WORKERS=9
    OE_DB_MAXCONN=$(( 90 / (OE_WORKERS + 2) ))
    OE_MAJOR="${OE_VERSION%%.*}"

    if [ ! -f 'odoo.config' ]; then
          cat > odoo.config <<EOF
[options]
admin_passwd = $(if [ "$GENERATE_RANDOM_PASSWORD" = "True" ]; then head /dev/urandom | tr -dc A-Za-z0-9 | head -c 16; echo; else echo "$OE_SUPERADMIN"; fi)
http_port = $OE_PORT
$(if [ "$OE_MAJOR" -ge 16 ]; then echo "gevent_port = $LONGPOLLING_PORT"; else echo "longpolling_port = $LONGPOLLING_PORT"; fi)
proxy_mode = $INSTALL_NGINX
data_dir = $DATA_DIR

# Sin workers Odoo corre en un solo proceso con hilos: no hay pool, y una impresion que
# bloquea su worker bloquea todo. Con wkhtmltopdf ademas hace falta que sobren workers,
# porque pide los assets por HTTP contra este mismo Odoo mientras retiene el suyo.
workers = $OE_WORKERS
max_cron_threads = 2
db_maxconn = $OE_DB_MAXCONN

# El blando tiene que ser MENOR que el duro: al pasarlo, el worker termina la peticion en
# curso y sale ordenado. Aca estaban al reves (blando 8,29 GB, duro 1,6 GB), asi que el
# reciclado ordenado nunca ocurria -- siempre llegaba primero el duro. Y el duro lo hereda
# wkhtmltopdf como RLIMIT_AS: con 1,6 GB compartidos con un worker ya cargado, Qt se queda
# sin espacio de direcciones.
limit_memory_soft = 2147483648
limit_memory_hard = 4294967296
limit_request = 8192

# 7200 son dos horas: una peticion trabada retiene su worker todo ese tiempo. El cpu debe
# quedar por debajo del real. Los crons siguen exentos.
limit_time_cpu = 600
limit_time_real = 900
limit_time_real_cron = -1

db_user = pg-$PROJECT-$OE_VERSION
addons_path=../numa-public-odoo-$OE_VERSION-numa/addons,../numa-public-odoo-$OE_VERSION-numa/odoo/addons,../extra-addons-$OE_VERSION$(if [ "$IS_ENTERPRISE" = "True" ]; then echo ",../enterprise-$OE_VERSION"; fi),../numa-public-addons-$OE_VERSION$(if [ "$INSTALL_PRIVATE" = "True" ]; then echo ",../numa-addons-$OE_VERSION,../numa_l10n_ar-$OE_VERSION"; fi)$(if [ "$PROJECT_REPO" = "True" ]; then echo ",$PROJECT-addons-$OE_VERSION"; fi)
EOF

      fi

    cat > ./start.sh <<START_EOF
#!/bin/bash
# El shebang no es decorativo: sin el, ./start.sh lo toma dash, que no conoce
# \`source\`, no activa el venv y odoo-bin muere con ModuleNotFoundError: babel.
cd "\$(dirname "\$0")"
# La ruta absoluta al config es lo que hace identificable el ambiente en \`ps\`: varios
# ambientes (produccion, prueba) conviven como directorios hermanos y todos lanzan el mismo
# odoo-bin. Es tambien lo que usa stop.sh para no apagar el ambiente equivocado.
# Se calcula en EJECUCION (de ahi los \$ escapados): resolverlo al generar dejaria clavada
# la ruta de la maquina donde se corrio el instalador.
CURRENT_DIR="\$(pwd)"
source venv/bin/activate

# Arrancar es el fin del mantenimiento.
rm -f mantenimiento.lock

# Que hay corriendo aca. El addons_path es una lista de directorios y nada en Odoo
# registra en que commit esta cada uno, asi que "que version esta desplegada" termina
# siendo arqueologia. Se escribe en cada arranque, que es el unico momento en que la
# respuesta es exacta. Tambien deja anotado el venv: si el ambiente se clono copiando el
# directorio, el venv copiado sigue apuntando al original y aca se ve.
{
    echo "arrancado:  \$(date -Is)"
    echo "venv:       \$(python3 -c 'import sys; print(sys.prefix)' 2>/dev/null)"
    echo "--- repositorios ---"
    SEEN=""
    for d in "\$CURRENT_DIR" "\$CURRENT_DIR"/*/ "\$CURRENT_DIR"/../*/; do
        [ -d "\$d/.git" ] || continue
        p="\$(cd "\$d" && pwd)"
        case " \$SEEN " in *" \$p "*) continue ;; esac
        SEEN="\$SEEN \$p"
        REV="\$(git -C "\$p" rev-parse --short HEAD 2>/dev/null)"
        BR="\$(git -C "\$p" rev-parse --abbrev-ref HEAD 2>/dev/null)"
        printf '%-10s %-14s %s\n' "\$REV" "\$BR" "\$p"
    done
    echo "--- paquetes ---"
    python3 -m pip freeze 2>/dev/null
} > deployed.txt

exec ../numa-public-odoo-$OE_VERSION-numa/odoo-bin -c "\$CURRENT_DIR/odoo.config" "\$@"
START_EOF
    chmod +x ./start.sh

    CWD=$(pwd)

    if [ ! -f ./onboot.sh ]; then
      cat > ./onboot.sh <<ONBOOT_EOF
#!/bin/bash
# Arranque, rotacion del log y supervision de ESTE ambiente.
#
#   ./onboot.sh                  arranca (es lo que llama el @reboot del crontab)
#   ./onboot.sh --si-no-corre    arranca solo si no esta corriendo; para una linea de cron
#   ./onboot.sh --solo-rotar     rota el log y sale, sin arrancar nada
#
# Sin shebang, el \`@reboot /bin/bash -c .../onboot.sh\` del crontab termina ejecutando
# esto con /bin/sh (dash), que no conoce \`source\`: el venv no se activa y odoo-bin muere
# con ModuleNotFoundError. \$CWD se interpola aca a proposito: cron arranca en otro
# directorio y necesita la ruta absoluta.
cd "$CWD" || exit 1

MODO="\${1:-}"
LOG=log/odoo-server.log
LOG_MAX=\$((50 * 1024 * 1024))
LOG_KEEP=7

# Un proceso es de este ambiente si su linea de comandos nombra NUESTRO config: varios
# ambientes conviven como directorios hermanos y todos lanzan el mismo odoo-bin.
es_de_este_ambiente () {
    [ -r "/proc/\$1/cmdline" ] || return 1
    tr '\0' ' ' < "/proc/\$1/cmdline" | grep -qF "\$(pwd)/odoo.config"
}

# --si-no-corre: para una linea de cron cada pocos minutos. El @reboot solo cubre el
# reinicio de la maquina; si el master muere por cualquier otra razon, sin esto no lo
# levanta nadie. Silencioso mientras todo va bien, para no llenar el mail del cron.
if [ "\$MODO" = "--si-no-corre" ]; then
    # Un apagado deliberado deja un candado. No arrancar encima de un mantenimiento en
    # curso; y que el candado caduque, para que uno abandonado no deje el ambiente caido
    # indefinidamente. Silencioso mientras el mantenimiento es reciente.
    MANTENIMIENTO_MAX=1800
    if [ -f mantenimiento.lock ]; then
        DESDE=\$(head -1 mantenimiento.lock 2>/dev/null)
        case "\$DESDE" in ''|*[!0-9]*) DESDE=0 ;; esac
        AHORA=\$(date +%s)
        if [ "\$DESDE" -gt 0 ] && [ \$((AHORA - DESDE)) -lt "\$MANTENIMIENTO_MAX" ]; then
            exit 0
        fi
        echo "\$(date '+%F %T') candado de mantenimiento vencido; arranco igual"
        rm -f mantenimiento.lock
    fi
    if [ -f running-odoo.pid ]; then
        PID=\$(cat running-odoo.pid)
        if kill -0 "\$PID" 2>/dev/null && es_de_este_ambiente "\$PID"; then
            exit 0
        fi
    fi
    # Que el pidfile no sirva no prueba que no este corriendo: puede haberse perdido o
    # quedado viejo, y de hecho uno apuntaba a un worker en vez de al master. Arrancar un
    # segundo Odoo sobre la misma base es mucho peor que no arrancar ninguno, asi que se
    # busca por linea de comandos antes de decidir.
    for _p in \$(pgrep -f "odoo-bin" 2>/dev/null); do
        if es_de_este_ambiente "\$_p"; then
            echo "\$(date '+%F %T') corriendo como pid \$_p pero sin pidfile valido; no arranco otro"
            exit 0
        fi
    done
    echo "\$(date '+%F %T') no estaba corriendo; arrancando"
fi

# Rotar antes de arrancar. Aca y no en start.sh porque este es el unico lugar que conoce
# la ruta del log: start.sh la recibe como argumento y tendria que parsearsela. Rotar
# ANTES de que odoo abra el archivo evita copytruncate y evita mandarle señales: el
# proceso nuevo crea el suyo limpio. Odoo 18 ya no trae rotacion propia.
if [ -f "\$LOG" ] && [ "\$(stat -c%s "\$LOG" 2>/dev/null || echo 0)" -gt "\$LOG_MAX" ]; then
    rm -f "\$LOG.\$LOG_KEEP.gz"
    i=\$((LOG_KEEP - 1))
    while [ "\$i" -ge 1 ]; do
        [ -f "\$LOG.\$i.gz" ] && mv -f "\$LOG.\$i.gz" "\$LOG.\$((i + 1)).gz"
        i=\$((i - 1))
    done
    mv -f "\$LOG" "\$LOG.1" && gzip -f "\$LOG.1"
    echo "onboot: log rotado (superaba \$((LOG_MAX / 1024 / 1024)) MB), se conservan \$LOG_KEEP"
fi

[ "\$MODO" = "--solo-rotar" ] && exit 0

source venv/bin/activate
exec ./start.sh --pidfile=running-odoo.pid --logfile="\$LOG" &
ONBOOT_EOF
#!/bin/bash
# Sin shebang, el \`@reboot /bin/bash -c .../onboot.sh\` del crontab termina ejecutando
# esto con /bin/sh (dash), que no conoce \`source\`: el venv no se activa y odoo-bin muere
# con ModuleNotFoundError. \$CWD se interpola aca a proposito: cron arranca en otro
# directorio y necesita la ruta absoluta.
cd "$CWD" || exit 1
source venv/bin/activate
exec ./start.sh --pidfile=running-odoo.pid --logfile=log/odoo-server.log &
ONBOOT_EOF
      chmod +x ./onboot.sh
    fi

    if [ ! -f ./stop.sh ]; then
      cat > ./stop.sh <<'STOP_EOF'
#!/bin/bash
# Apagado ordenado de ESTE ambiente, y solo de este.
#
# Varios ambientes conviven como directorios hermanos -- produccion y prueba, cada uno con
# su venv, su odoo.config y su puerto -- y todos lanzan el mismo odoo-bin. Cualquier
# apagado que busque procesos por patron de nombre (`pkill -f odoo-bin`) alcanza a los
# vecinos. Aca no se busca por nombre en ningun momento:
#
#   1. el pid sale de running-odoo.pid, y se verifica contra la ruta absoluta del config
#      que start.sh le pasa a odoo-bin -- un pidfile viejo puede nombrar un pid reciclado
#      por un proceso ajeno, y matar eso seria matar algo de otro;
#   2. los workers se capturan como hijos de ESE pid, y se capturan ANTES de tocar al
#      padre: apenas el master muere, los hijos quedan huerfanos reparentados a init y ya
#      no hay forma de saber de quien eran;
#   3. antes de matar a cada superviviente se vuelve a verificar que siga siendo de este
#      ambiente, por si el pid se reciclo entre la captura y el remate.
#
# Un `kill -9` al master, sin nada de esto, dejaba workers huerfanos hasta minuto y medio
# y podia matar un wkhtmltopdf en curso -- que es como aparece un
# "Wkhtmltopdf failed (error code: -9)" en el log sin que haya OOM por ningun lado.
cd "$(dirname "$0")"
ENV_DIR="$(pwd)"

es_de_este_ambiente () {  # es_de_este_ambiente <pid>
    [ -r "/proc/$1/cmdline" ] || return 1
    tr '\0' ' ' < "/proc/$1/cmdline" | grep -qF "$ENV_DIR/odoo.config"
}

[ -f running-odoo.pid ] || { echo "no hay running-odoo.pid"; exit 0; }
PID=$(cat running-odoo.pid)

if ! kill -0 "$PID" 2>/dev/null; then
    echo "el pid $PID ya no corre"; rm -f running-odoo.pid; exit 0
fi

if ! es_de_este_ambiente "$PID"; then
    echo "el pid $PID no corresponde a $ENV_DIR -- no lo toco." >&2
    echo "running-odoo.pid quedo desactualizado; borralo a mano si estas seguro." >&2
    exit 1
fi

# Capturar los workers ahora, mientras el padre todavia esta y la relacion es visible.
HIJOS=$(pgrep -P "$PID" 2>/dev/null)

echo "apagando odoo de $ENV_DIR (pid $PID) con SIGTERM..."
kill -TERM "$PID" 2>/dev/null
for i in $(seq 1 30); do
    kill -0 "$PID" 2>/dev/null || { echo "apagado limpio en ${i}s"; break; }
    sleep 1
done
if kill -0 "$PID" 2>/dev/null; then
    echo "no respondio en 30s, SIGKILL como ultimo recurso"
    kill -9 "$PID" 2>/dev/null
fi

# Workers que hayan sobrevivido al padre. Solo los capturados, y solo si siguen siendo
# nuestros: nunca por patron.
for h in $HIJOS; do
    kill -0 "$h" 2>/dev/null && es_de_este_ambiente "$h" && kill -TERM "$h" 2>/dev/null
done
sleep 2
for h in $HIJOS; do
    if kill -0 "$h" 2>/dev/null && es_de_este_ambiente "$h"; then
        echo "  worker $h no cerro solo, SIGKILL"
        kill -9 "$h" 2>/dev/null
    fi
done

rm -f running-odoo.pid

# Un apagado deliberado es, por definicion, mantenimiento. Sin esto la supervision del
# cron lo pelea: mientras corre un `-u` no hay pidfile, la linea de --si-no-corre lo lee
# como "se cayo" y arranca un segundo Odoo sobre la misma base, que es bastante peor que
# tenerlo apagado. El candado caduca solo -- un mantenimiento abandonado no puede dejar
# el ambiente caido para siempre -- y lo borra el proximo arranque.
{ date +%s; echo "detenido por stop.sh el $(date '+%F %T')"; } > mantenimiento.lock
STOP_EOF
      chmod +x ./stop.sh
    fi

    # Los dos heredocs de abajo usan delimitador ENTRECOMILLADO ('NUMA_..._EOF').
    # Sin las comillas el shell expande cada $VAR y $(...) al GENERAR el script, y lo que
    # queda en disco son los valores congelados del momento de la instalacion:
    #     if [ $# -ne 2 ]        ->  if [ 0 -ne 2 ]      (siempre verdadero)
    #     DATE="$(date ...)"     ->  DATE="2025-08-26-00-18-19"
    #     for DB in $DBS         ->  for DB in           (ni siquiera es sintaxis valida)
    # Asi quedaron los dbbackup.sh/dbrestore.sh de produccion desde 2025-08-26: inertes,
    # y sin que nada lo avisara. Nada de aca adentro debe interpolarse al generar.
    if [ ! -f ./dbbackup.sh ]; then
      cat > ./dbbackup.sh <<'NUMA_DBBACKUP_EOF'
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
NUMA_DBBACKUP_EOF
      chmod +x ./dbbackup.sh
    fi

    if [ ! -f ./dbrestore.sh ]; then
      cat > ./dbrestore.sh <<'NUMA_DBRESTORE_EOF'
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
NUMA_DBRESTORE_EOF
      chmod +x ./dbrestore.sh
    fi

    echo -e "\n---- Install python packages/requirements ----"
    pip install --upgrade pip
    pip install wheel
    pip install -r "../numa-public-odoo-$OE_VERSION-numa/requirements.txt"
    pip install -r "../numa-public-addons-$OE_VERSION/requirements.txt"
    if [ "$INSTALL_PRIVATE" = "True" ]; then
      pip install -r "../numa-addons-$OE_VERSION/requirements.txt"
      pip install -r "../numa_l10n_ar-$OE_VERSION/requirements.txt"
    fi
    source venv/bin/activate
    "../numa-public-odoo-$OE_VERSION-numa/odoo-bin" -c odoo.config -s --stop-after-init

    cd ..
  fi
fi

#--------------------------------------------------
# Install Nginx if needed
#--------------------------------------------------
if [ "$INSTALL_NGINX" = "True" ]; then
    # Mejora: Instalar letsencrypt-nginx si aún no lo está
    sudo apt install python3-pip python3-venv python3-wheel python3-dev libxslt1-dev libzip-dev libldap2-dev libsasl2-dev libssl-dev libffi-dev libxml2-dev libxmlsec1-dev build-essential wget git nodejs npm rtlcss libjpeg-dev zlib1g-dev -y;
    sudo apt install nginx -y
    sudo apt install letsencrypt -y
    sudo apt install certbot python3-certbot-nginx -y
    if [ "$ENABLE_SSL" = "True" ]; then
      sudo certbot certonly --nginx -d "$WEBSITE_NAME" --noninteractive --agree-tos --email "$ADMIN_EMAIL"
      sudo service nginx reload
      echo "SSL/HTTPS is enabled!"
    else
      echo "SSL not requested; the site will be served over HTTP only."
    fi

  cat <<EOF > ~/$WEBSITE_NAME
#odoo server
upstream backend-$WEBSITE_NAME {
 server localhost:$OE_PORT;
}
upstream backend-$WEBSITE_NAME-im {
 server localhost:$LONGPOLLING_PORT;
}
map \$http_upgrade \$connection_upgrade {
  default upgrade;
  ''      close;
}

# http -> https
server {
   listen 80;
   server_name $WEBSITE_NAME;
   rewrite ^ https://\$host\$request_uri? permanent;
}

server {
  listen 443 ssl;
  server_name $WEBSITE_NAME;
  proxy_read_timeout 900s;
  proxy_connect_timeout 900s;
  proxy_send_timeout 900s;

  ssl_certificate /etc/letsencrypt/live/$WEBSITE_NAME/fullchain.pem; # managed by Certbot
  ssl_certificate_key /etc/letsencrypt/live/$WEBSITE_NAME/privkey.pem; # managed by Certbot
  ssl_session_timeout 30m;
  ssl_protocols TLSv1.2;
  ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:DHE-RSA-AES128-GCM-SHA256:DHE-RSA-AES256-GCM-SHA384;
  ssl_prefer_server_ciphers off;
  keepalive_timeout 60;


  # Add Headers for odoo proxy mode
  proxy_set_header X-Forwarded-Host \$host;
  proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
  proxy_set_header X-Forwarded-Proto \$scheme;
  proxy_set_header X-Real-IP \$remote_addr;
  add_header X-Frame-Options "SAMEORIGIN";
  add_header X-XSS-Protection "1; mode=block";
  proxy_set_header X-Client-IP \$remote_addr;
  proxy_set_header HTTP_X_FORWARDED_HOST \$remote_addr;

  #   odoo    log files
  access_log  /var/log/nginx/$OE_USER-access.log;
  error_log   /var/log/nginx/$OE_USER-error.log;

  #   increase    proxy   buffer  size
  proxy_buffers   16  64k;
  proxy_buffer_size   128k;

  #   force   timeouts    if  the backend dies
  proxy_next_upstream error   timeout invalid_header  http_500    http_502
  http_503;

  types {
    text/less less;
    text/scss scss;
  }

  #   enable  data    compression
  gzip    on;
  gzip_min_length 1100;
  gzip_buffers    4   32k;
  gzip_types  text/css text/scss text/plain text/xml application/xml application/json application/javascript;
  gzip_vary   on;
  client_header_buffer_size 4k;
  large_client_header_buffers 4 64k;
  client_max_body_size 0;

  location / {
    proxy_set_header X-Forwarded-Host \$host;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_redirect off;
    proxy_pass http://backend-$WEBSITE_NAME;

    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains";

  }

  location /websocket {
    proxy_pass http://backend-$WEBSITE_NAME-im;
    proxy_set_header Upgrade \$http_upgrade;
    proxy_set_header Connection \$connection_upgrade;
    proxy_set_header X-Forwarded-Host \$host;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
    proxy_set_header X-Real-IP \$remote_addr;

    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains";
  }
}
EOF

  sudo mv ~/$WEBSITE_NAME /etc/nginx/sites-available/
  sudo ln -s /etc/nginx/sites-available/$WEBSITE_NAME /etc/nginx/sites-enabled/$WEBSITE_NAME
  sudo rm /etc/nginx/sites-enabled/default
  sudo service nginx reload
  # proxy_mode ya se escribe en odoo.config al generarlo (arriba), a partir de
  # $INSTALL_NGINX. No hay ningun /etc/<OE_CONFIG>.conf en esta instalacion.
  echo "Done! The Nginx server is up and running. Configuration can be found at /etc/nginx/sites-available/odoo"
else
  echo "Nginx isn't installed due to choice of the user!"
fi

#--------------------------------------------------
# Enable ssl with certbot
#--------------------------------------------------


echo "-----------------------------------------------------------"
echo "Done!. Specifications:"
echo "Port: $OE_PORT"
echo "Project: $PROJECT"
echo "Project directory: $(pwd)/$PROJECT-$OE_VERSION"
echo "Configuraton file location: $(pwd)/$PROJECT-$OE_VERSION/odoo.config"
echo "Logfile location: $(pwd)/$PROJECT-$OE_VERSION/log"
echo "User PostgreSQL: pg-$PROJECT-$OE_VERSION"
echo "Password superadmin database: $OE_SUPERADMIN"
if [ "$INSTALL_NGINX" = "True" ]; then
  echo "Nginx configuration file: /etc/nginx/sites-available/odoo"
fi
echo "-----------------------------------------------------------"
