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

OE_USER="$user"
OE_HOME=$pwd
# The default port where this Odoo instance will run under provided you use the command -c in the terminal
# Set to true if you want to install it, false if you don't need it or have it already installed.
read -r -e -p "Install WkmhtmlToPdf [True/False]: " -i "False" INSTALL_WKHTMLTOPDF

# Set the default Odoo port you still have to use -c /etc/odoo-server.conf for example to use this.
read -r -e -p "Odoo port number: " -i "8069" OE_PORT

# Set the default Odoo longpolling port you still have to use -c /etc/odoo-server.conf for example to use this.
read -r -e -p "Odoo longpolling port: " -i "8072" LONGPOLLING_PORT

# Choose the Odoo version which you want to install. For example: 13.0, 12.0, 11.0 or saas-18. When using 'master' the master version will be installed.
# IMPORTANT! This script contains extra libraries that are specifically needed for Odoo 13.0
read -r -e -p "Odoo version: " -i "16.0" OE_VERSION

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
  read -r -e -p "Email for ssl certificate: " -i "odoo@example.com ADMIN_EMAIL"

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
sudo apt-get install postgresql postgres-client postgres-client-common postgresql-server-dev-all libpq-dev -y
sudo -u postgres createuser $USER

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

if [ ! -d /usr/bin/home ]; then
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
  wget https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6.1-2/wkhtmltox_0.12.6.1-2.jammy_amd64.deb
  sudo apt install xfonts-75dpi xfonts-base -y
  sudo dpkg -i wkhtmltox_0.12.6.1-2.jammy_amd64.deb
  sudo cp /usr/local/bin/wkhtmltoimage /usr/bin/wkhtmltoimage
  sudo cp /usr/local/bin/wkhtmltopdf /usr/bin/wkhtmltopdf
fi

#--------------------------------------------------
# Install ODOO
#--------------------------------------------------
echo -e "\n==== Installing numa-public-odoo Server ===="
if [ ! -d "odoo-$OE_VERSION-numa" ]; then
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
fi

if [ "$IS_ENTERPRISE" = "True" ]; then
    # Odoo Enterprise install!

    GITHUB_RESPONSE=$(git clone --depth 1 --branch "$OE_VERSION" https://www.github.com/odoo/enterprise "enterprise-$OE_VERSION" 2>&1)
    while [[ $GITHUB_RESPONSE == *"Authentication"* ]]; do
        echo "------------------------WARNING------------------------------"
        echo "Your authentication with Github has failed! Please try again."
        echo "In order to clone and install the Odoo enterprise version you \nneed to be an offical Odoo partner and you need access to\nhttp://github.com/odoo/enterprise.\n"
        echo "TIP: Press ctrl+c to stop this script."
        echo "-------------------------------------------------------------"
        echo " "
        GITHUB_RESPONSE=$(git clone --depth 1 --branch "$OE_VERSION" https://www.github.com/odoo/enterprise "$OE_HOME/enterprise/addons" 2>&1)
    done

    sudo -H pip3 install num2words ofxparse dbfread ebaysdk firebase_admin pyOpenSSL
    sudo npm install -g less
    sudo npm install -g less-plugin-clean-css
fi

if [ "$PROJECT" != "" ]; then
  if [ -n "$PROJECT" ]; then
    # Create project environment
    echo -e "\n==== Installing project-addons ===="
    if [ ! -d "$PROJECT-$OE_VERSION" ]; then
      mkdir "$PROJECT-$OE_VERSION"
    fi

    cd "$PROJECT-$OE_VERSION" || exit

    if [ ! -d "$PROJECT-addons-$OE_VERSION" ]; then
      if [ "$PROJECT_REPO" = "True" ]; then
        git clone "https://github.com/numaes/$PROJECT-addons" -b "$OE_VERSION" "$PROJECT-addons-$OE_VERSION"
      fi
    fi

    mkdir -p log
    mkdir -p data
    mkdir -p database

    if [ ! -d venv ]; then
      echo -e "\n---- Install virtual env in current directory ----"
      python3 -m venv venv
    fi

    source venv/bin/activate
    sudo ./setup/debinstall.sh

    if [ ! -f 'odoo.config' ]; then
      touch odoo.config
      echo -e "* Creating server config file"

      printf "[options] \n; This is the password that allows database operations:\n" >> odoo.config
      if [ "$GENERATE_RANDOM_PASSWORD" = "True" ]; then
          echo -e "* Generating random admin password"
          OE_SUPERADMIN=$cat /dev/urandom | tr -dc 'a-zA-Z0-9' | fold -w 16 | head -n 1
      fi
      printf "admin_passwd = ${OE_SUPERADMIN}\n" >> odoo.config

      if [ "$OE_VERSION" \> "11.0 " ]; then
          printf "http_port = ${OE_PORT}\n" >> odoo.config
      else
          printf "xmlrpc_port = ${OE_PORT}\n" >> odoo.config
      fi
      if [ "$OE_VERSION" \>= "16.0" ]; then
          printf "gevent_port = ${LONGPOLLING_PORT}\n" >> odoo.config
          printf "longpolling_port = False\n" >> odoo.config
      else
          printf "longpolling_port = ${LONGPOLLING_PORT}\n" >> odoo.config
      fi
      if [ "$INSTALL_NGINX" = "True" ]; then
          printf "proxy_mode = True\n" >> odoo.config
      fi
      printf "data_dir = data\n" >> odoo.config
      printf "limit_memory_hard = 1677721600" >> odoo.config
      printf "limit_memory_soft = 629145600" >> odoo.config
      printf "limit_request = 8192" >> odoo.config
      printf "limit_time_cpu = 3600\n" >> odoo.config
      printf "limit_time_real = 7200\n" >> odoo.config
      printf "db_user = pg-$PROJECT-$OE_VERSION\n" >>odoo.config

      if [ "$PROJECT_REPO" = "True" ]; then
        printf "addons_path=$PROJECT-addons-$OE_VERSION," >> odoo.config
      else
        printf "addons_path=" >> odoo.config
      fi

      printf "../extra-addons-$OE_VERSION," >> odoo.config

      if [ "$INSTALL_PRIVATE" = "Yes" ]; then
        printf "../numa-addons-$OE_VERSION," >>odoo.config
      fi

      printf "../numa-public-addons-$OE_VERSION," >>odoo.config

      if [ "$IS_ENTERPRISE" = "True" ]; then
          printf "../enterprise-$OE_VERSION," >> odoo.config
      fi

      printf "../numa-public-odoo-$OE_VERSION-numa/addons,../odoo-$OE_VERSION-numa/odoo/addons\n" >>odoo.config

    fi

    cat <<EOF > ./start.sh
source venv/bin/activate
../odoo-$OE_VERSION-numa/odoo-bin -c odoo.config \$1 \$2 \$3 \$4 \$5 \$6 \$7 \$8 \$9
EOF
    chmod +x ./start.sh

    CWD=$(pwd)

    if [ ! -f ./onboot.sh ]; then
      cat <<EOF > ./onboot.sh
cd $CWD
source venv/bin/activate
./start.sh --pidfile=running-odoo.pid --logfile=log/odoo-server.log &
EOF
      chmod +x ./onboot.sh
    fi

    if [ ! -f ./stop.sh ]; then
      cat <<EOF > ./stop.sh
if [ -f running-odoo.pid ]; then
    CWO=\$(cat running-odoo.pid)
    kill -9 \$CWO
    rm running-odoo.pid
fi
EOF
      chmod +x ./stop.sh
    fi

    if [ ! -f ./dbbackup.sh ]; then
      cat <<EOF > ./dbbackup.sh
# !/bin/bash
# This script is public domain. Feel free to use or modify as you like.
if [ $# -ne 2 ]; then
    echo "Usage:"
    echo "     $0 <database>  <role>]"
else
	BZIP2="/bin/bzip2"
	GREP="/bin/grep"
	ROLE="$2"
	DUMPALL="pg_dumpall"
	PGDUMP="pg_dump"
	PSQL="psql"
	DATE="$(date +%Y-%m-%d-%H-%M-%S)"
	FILESTOREDIR="./data"

	# directory to save backups in, must be rwx by postgres user
	BACKUPDIR="./database"
	[ -d $BACKUPDIR ] || mkdir -p $BACKUPDIR

	if [ ! -d $FILESTOREDIR ]; then
	   echo "You have no access to Odoo filestore. Run dbbackup with sudo!"
	   exit
	fi

	# get list of databases in system for current user
	# command inspired on SISalp suggestion on odoo mail list
	# https://www.odoo.com/groups/community-59/community-15954813
	DBS=`$PSQL -l -U $ROLE | grep $ROLE | cut -d '|' -f1`
	DBS="$1"

	# now backup the tables
	CWD="$(pwd)"
	# cd /tmp
	for DB in $DBS; do
		# It would have been nice to do the next using pipe
		# but pipe didnt now allow me to redirect pg_dump output to input tar
		# at least I couldn't ;(
		echo "Performing backup of $DB..."
		[ -d $BACKUPDIR/$DB ] || mkdir -p $BACKUPDIR/$DB

		if [ -d "$FILESTOREDIR/filestore/$DB" ]; then
			$PGDUMP $DB -U -O $ROLE > dump.sql && tar cjf $BACKUPDIR/$DB/$DB-$DATE.tar.bz2 --transform "s,^filestore/$DB,filestore," dump.sql -C $FILESTOREDIR filestore/$DB && rm -rf dump.sql
		else
			$PGDUMP $DB -U -O $ROLE > dump.sql && tar cjf $BACKUPDIR/$DB/$DB-$DATE.tar.bz2 dump.sql && rm -rf dump.sql
		fi
	done
	# cd $CWD
fi
EOF
      chmod +x ./dbbackup.sh
    fi

    if [ ! -f ./dbrestore.sh ]; then
      cat <<EOF > ./dbrestore.sh
if [ $# -ne 3 ]; then
    echo "Usage:"
    echo "     $0 <database>  <backup-file>  <role>]"
else
    DB="$1"
    BACKUP_FILE="$2"
    ROLE="$3"
    DATA_PATH="./data"
    UNTARDIR="/tmp/untardir"
    TODAY="$(date '+%Y-%m-%d %H:%M:%S')"
    TODAY_PLUS_ONE_MONTH="$(date -d '+1 month' '+%Y-%m-%d %H:%M:%S')"
    UUID=$(cat /proc/sys/kernel/random/uuid)
    PSQL="psql"

    if [ ! -d $DATA_PATH ]; then
        echo "You have no access to Odoo filestore. Run command with sudo"
    else
        # echo "Droping database $DB if exists"
        # dropdb $DB -U $ROLE

		DBS=`$PSQL -l -U $ROLE | grep $ROLE | cut -d '|' -f1`


		if echo $DBS | grep -w $DB > /dev/null; then
			echo "Existing database, aborting..."
			exit 1
		fi

        echo "Creating empty database"
        createdb -O $ROLE -U $ROLE $DB --encoding=UNICODE -T template0

        echo "Restoring database $DB with file $BACKUP_FILE"
        test -d $UNTARDIR && rm -r $UNTARDIR
        mkdir $UNTARDIR
        tar -xjf $BACKUP_FILE -C $UNTARDIR

        echo "Regenerating database ..."
        psql -d $DB -U $ROLE >/dev/null < $UNTARDIR/dump.sql

        echo "Creating a new id for the new database"
        # psql -d $DB -U $ROLE -c "UPDATE ir_config_parameter set value='$UUID' where key='database.uuid'"
        # psql -d $DB -U $ROLE -c "UPDATE ir_config_parameter set value='$TODAY' where key='database.create_date'"
        # psql -d $DB -U $ROLE -c "UPDATE ir_config_parameter set value='$TODAY_PLUS_ONE_MONTH' where key='database.expiration_date'"

		echo "Cleaning filestore"
        test -d $DATA_PATH/filestore || mkdir -p $DATA_PATH/filestore
        test -d $DATA_PATH/filestore/$DB || mkdir -p $DATA_PATH/filestore/$DB
        # rm -r $DATA_PATH/filestore/$DB/*
        if [ -d $UNTARDIR/filestore ]; then
        	echo "Restoring filestore"
            mv $UNTARDIR/filestore/* -t $DATA_PATH/filestore/$DB
        fi

        # chown -R odoo:odoo $DATA_PATH/filestore/$DB

        rm -r $UNTARDIR
    fi
fi
EOF
      chmod +x ./dbrestore.sh
    fi


    echo -e "\n---- Install python packages/requirements ----"
    pip install --upgrade pip
    pip install wheel
    pip install -r "../odoo-$OE_VERSION-numa/requirements.txt"
    pip install -r "../numa-public-addons-$OE_VERSION/requirements.txt"
    if [ "$INSTALL_PRIVATE" = "Yes" ]; then
      pip install -r "../numa-addons-$OE_VERSION/requirements.txt"
    fi

    "../odoo-$OE_VERSION-numa/odoo-bin" -c odoo.config -s --stop-after-init

    cd ..
  fi
fi

#--------------------------------------------------
# Install Nginx if needed
#--------------------------------------------------
if [ "$INSTALL_NGINX" = "True" ]; then
  echo -e "\n---- Installing and setting up Nginx ----"
  sudo apt install nginx certbot -y

  cat <<EOF > ~/odoo
#odoo server
upstream backend-odoo {
 server localhost:$OE_PORT;
}
upstream backend-odoo-im {
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
   rewrite ^/.*\$ https://\$host\$1 permanent;
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
    proxy_set_header X-Forwarded-Host $http_host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_redirect off;
    proxy_pass http://odoo;

    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains";
    proxy_cookie_flags session_id samesite=lax secure;  # requires nginx 1.19.8

  }

  location /websocket {
    proxy_pass http://backend-odoo-im;
    proxy_set_header Upgrade \$http_upgrade;
    proxy_set_header Connection \$connection_upgrade;
    proxy_set_header X-Forwarded-Host \$host;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
    proxy_set_header X-Real-IP \$remote_addr;

    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains";
    proxy_cookie_flags session_id samesite=lax secure;  # requires nginx 1.19.8
  }

  gzip_types text/css text/scss text/plain text/xml application/xml application/json application/javascript;
  gzip on;

}
EOF

  sudo mv ~/odoo /etc/nginx/sites-available/
  sudo ln -s /etc/nginx/sites-available/odoo /etc/nginx/sites-enabled/odoo
  sudo rm /etc/nginx/sites-enabled/default
  sudo service nginx reload
  sudo su root -c "echo 'proxy_mode = True\n' >> /etc/${OE_CONFIG}.conf"
  echo "Done! The Nginx server is up and running. Configuration can be found at /etc/nginx/sites-available/odoo"
else
  echo "Nginx isn't installed due to choice of the user!"
fi

#--------------------------------------------------
# Enable ssl with certbot
#--------------------------------------------------

if [ "$INSTALL_NGINX" = "True" ] && [ "$ENABLE_SSL" = "True" ] && [ "$ADMIN_EMAIL" != "odoo@example.com" ]  && [ "$WEBSITE_NAME" != "_" ];then
  sudo apt-get install letsencrypt -y
  sudo letsncrypt certbot --nginx -d $WEBSITE_NAME --noninteractive --agree-tos --email $ADMIN_EMAIL --redirect
  sudo service nginx reload
  echo "SSL/HTTPS is enabled!"
else
  echo "SSL/HTTPS isn't enabled due to choice of the user or because of a misconfiguration!"
fi

echo "-----------------------------------------------------------"
echo "Done!. Specifications:"
echo "Port: $OE_PORT"
echo "Project: $PROJECT"
echo "Project directory: $pwd/$PROJECT-$OE_VERSION"
echo "Configuraton file location: $pwd/$PROJECT-$OE_VERSION/odoo.config"
echo "Logfile location: $pwd/$PROJECT-$OE_VERSION/log"
echo "User PostgreSQL: pg-$PROJECT-$OE_VERSION"
echo "Password superadmin database: $OE_SUPERADMIN"
if [ "$INSTALL_NGINX" = "True" ]; then
  echo "Nginx configuration file: /etc/nginx/sites-available/odoo"
fi
echo "-----------------------------------------------------------"
