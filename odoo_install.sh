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
read -r -e -p "Odoo version: " -i "14.0" OE_VERSION

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
sudo apt-get install postgresql postgresql-server-dev-all -y

echo -e "\n---- Creating the ODOO PostgreSQL User  ----"
sudo su - postgres -c "createuser -s $OE_USER" 2> /dev/null || true
createuser -s "pg-$PROJECT-$OE_VERSION"

#--------------------------------------------------
# Install Dependencies
#--------------------------------------------------
echo -e "\n--- Installing Python 3 + pip3 --"
sudo apt-get install git python3 python3-pip build-essential wget python3-dev python3-venv python3-wheel -y
sudo apt-get install libxslt-dev libzip-dev libldap2-dev libsasl2-dev python3-setuptools -y
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
  wget https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6-1/wkhtmltox_0.12.6-1.focal_amd64.deb
  sudo apt install ./wkhtmltox_0.12.6-1.focal_amd64
fi

#--------------------------------------------------
# Install ODOO
#--------------------------------------------------
echo -e "\n==== Installing numa-public-odoo Server ===="
if [ ! -d "odoo-$OE_VERSION-numa" ]; then
  git clone https://github.com/numaes/numa-public-odoo -b "$OE_VERSION-numa" "odoo-$OE_VERSION-numa"
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
      printf "longpolling_port = ${LONGPOLLING_PORT}\n" >> odoo.config

      printf "data_dir = data\n" >> odoo.config
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

      printf "../odoo-$OE_VERSION-numa/addons,../odoo-$OE_VERSION-numa/odoo/addons\n" >>odoo.config

    fi

    cat <<EOF > ./start.sh
source venv/bin/activate
../odoo-$OE_VERSION-numa/odoo-bin -c odoo.config \$1 \$2 \$3 \$4 \$5 \$6 \$7 \$8 \$9
EOF
    chmod +x start.sh

    CWD=$(pwd)

    if [ ! -f ./onboot.sh ]; then
      cat <<EOF > ./onboot.sh
cd $(CWD)
source venv/bin/activate
./start.sh --pidfile=$CWD/running-odoo.pid --logfile=log/odoo-server.log &
EOF
      chmod +x onboot.sh
    fi

    if [ ! -f ./stop.sh ]; then
      cat <<EOF > ./stop.sh
if [ -f running-odoo.pid ]; then
    CWO=\$(cat running-odoo-pid)
    kill -9 $CWO
    rm running-odoo.pid
fi
EOF
      chmod +x .stop.sh
    fi

    echo -e "\n---- Install python packages/requirements ----"
    pip3 install wheel
    pip3 install -r "../odoo-$OE_VERSION-numa/requirements.txt"
    pip3 install -r "../numa-public-addons-$OE_VERSION/requirements.txt"
    pip3 install -r "../numa-addons-$OE_VERSION/requirements.txt"

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

# http -> https
server {
   listen 80;
   add_header Strict-Transport-Security max-age=2592000;
   rewrite ^/.*\$ https://\$host\$request_uri? permanent;
}

server {
  listen 443 ssl;
  server_name $WEBSITE_NAME;
  proxy_read_timeout 900s;
  proxy_connect_timeout 900s;
  proxy_send_timeout 900s;

  ssl_certificate /etc/letsencrypt/live/$WEBSITE_NAME/fullchain.pem; # managed by Certbot
  ssl_certificate_key /etc/letsencrypt/live/$WEBSITE_NAME/privkey.pem; # managed by Certbot
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
  gzip_types  text/css text/less text/plain text/xml application/xml application/json application/javascript application/pdf image/jpeg image/png;
  gzip_vary   on;
  client_header_buffer_size 4k;
  large_client_header_buffers 4 64k;
  client_max_body_size 0;

  location / {
    proxy_pass    http://localhost:$OE_PORT;
  }

  location /longpolling {
    proxy_pass http://localhost:$LONGPOLLING_PORT;
  }
  location ~* .js|css|png|jpg|jpeg|gif|ico$ {
    expires 2d;
    proxy_pass http://localhost:$OE_PORT;
    add_header Cache-Control "public, no-transform";
  }
  # cache some static data in memory for 60mins.
  location ~ /[a-zA-Z0-9_-]*/static/ {
    proxy_cache_valid 200 302 60m;
    proxy_cache_valid 404      1m;
    proxy_buffering    on;
    expires 864000;
    proxy_pass    http://localhost:$OE_PORT;
  }
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
