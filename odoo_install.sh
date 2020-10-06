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

# Choose the Odoo version which you want to install. For example: 13.0, 12.0, 11.0 or saas-18. When using 'master' the master version will be installed.
# IMPORTANT! This script contains extra libraries that are specifically needed for Odoo 13.0
read -r -e -p "Odoo version: " -i "14.0" OE_VERSION

# Set this to True if you want to install the Odoo enterprise version!
read -r -e -p "Is enterprise? [True/False]: " -i "False" IS_ENTERPRISE

# Set this to True if you want to install Nginx!
read -r -e -p "Install Nginx? [True/False]: " -i "False" INSTALL_NGINX

# Set the superadmin password - if GENERATE_RANDOM_PASSWORD is set to "True" we will automatically generate a random password, otherwise we use this one
read -r -e -p "Superadmin name: " -i "admin" OE_SUPERADMIN

# Set to "True" to generate a random password, "False" to use the variable in OE_SUPERADMIN
read -r -e -p "Generate random password for admin? [True/False]: " -i "False" GENERATE_RANDOM_PASSWORD

# Set the website name
read -r -e -p "Website name: " -i "_" WEBSITE_NAME

# Set the default Odoo longpolling port you still have to use -c /etc/odoo-server.conf for example to use this.
read -r -e -p "Odoo longpolling port: " -i "8072" LONGPOLLING_PORT

# Set to "True" to install certbot and have ssl enabled, "False" to use http
read -r -e -p "Enable SSL? [True/False]: " -i "False" ENABLE_SSL

# Provide Email to register ssl certificate
read -r -e -p "Email for ssl certificate: " -i "odoo@example.com ADMIN_EMAIL"

# Project name
read -r -e -p "Project name: " PROJECT

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
sudo apt-get install git python3 python3-pip build-essential wget python3-dev python3-venv python3-wheel libxslt-dev libzip-dev libldap2-dev libsasl2-dev python3-setuptools node-less libpng12-0 libjpeg-dev gdebi -y
sudo apt-get install libxml2-dev libxnlsec1-dev

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
## === Ubuntu Trusty x64 & x32 === for other distributions please replace these two links,
## in order to have correct version of wkhtmltopdf installed, for a danger note refer to
## https://github.com/odoo/odoo/wiki/Wkhtmltopdf :
## https://www.odoo.com/documentation/13.0/setup/install.html#debian-ubuntu

WKHTMLTOX_X64=https://github.com/wkhtmltopdf/wkhtmltopdf/releases/download/0.12.5/wkhtmltox_0.12.5-1.trusty_amd64.deb
WKHTMLTOX_X32=https://github.com/wkhtmltopdf/wkhtmltopdf/releases/download/0.12.5/wkhtmltox_0.12.5-1.trusty_i386.deb

if [ "$INSTALL_WKHTMLTOPDF" = "True" ]; then
  echo -e "\n---- Install wkhtml and place shortcuts on correct place for ODOO $OE_VERSION ----"
  #pick up correct one from x64 & x32 versions:
  if [ "`getconf LONG_BIT`" == "64" ];then
      _url=$WKHTMLTOX_X64
  else
      _url=$WKHTMLTOX_X32
  fi
  sudo wget $_url
  sudo gdebi --n `basename $_url`
  sudo ln -s /usr/local/bin/wkhtmltopdf /usr/bin
  sudo ln -s /usr/local/bin/wkhtmltoimage /usr/bin
else
  echo "Wkhtmltopdf isn't installed due to the choice of the user!"
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

if [ -n "$PROJECT" ]; then
  # Create project environment
  echo -e "\n==== Installing project-addons ===="
  if [ ! -d "$PROJECT-$OE_VERSION" ]; then
    mkdir "$PROJECT-$OE_VERSION"
  fi

  cd "$PROJECT-$OE_VERSION" || exit

  if [ ! -d "$PROJECT-addons-$OE_VERSION" ]; then
    git clone "https://github.com/numaes/$PROJECT-addons" -b "$OE_VERSION" "$PROJECT-addons-$OE_VERSION"
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
    printf "data_dir = data\n" >> odoo.config
    printf "limit_time_cpu = 3600\n" >> odoo.config
    printf "limit_time_real = 7200\n" >> odoo.config
    printf "db_user = pg-$PROJECT-$OE_VERSION\n" >>odoo.config

    if [ "$IS_ENTERPRISE" = "True" ]; then
        printf "addons_path=$PROJECT-addons-$OE_VERSION,../enterprise-$OE_VERSION" >> odoo.config
    else
        printf "addons_path=$PROJECT-addons-$OE_VERSION" >> odoo.config
    fi
    printf ",../extra-addons-$OE_VERSION,../numa-addons-$OE_VERSION,../numa-public-addons-$OE_VERSION,../odoo-$OE_VERSION-numa/addons,../odoo-$OE_VERSION-numa/odoo/addons\n" >>odoo.config

  fi

  cat <<EOF > ./start.sh
  chmod +x start.sh
../odoo-$OE_VERSION-numa/odoo-bin -c odoo.config $1 $2 $3 $4 $5 $6 $7 $8 $9
EOF
  if [ ! -f ./onboot.sh ]; then
    cat <<EOF > ./onboot.sh
cd $pwd
source venv/bin/activate
./start.sh --logfile=log/odoo-server.log &
EOF
    chmod +x onboot.sh
  fi

  echo -e "\n---- Install python packages/requirements ----"
  pip install wheel
  pip install -r "../odoo-$OE_VERSION-numa/requirements.txt"
  pip install -r "../numa-public-addons-$OE_VERSION/requirements.txt"
  pip install -r "../numa-addons-$OE_VERSION/requirements.txt"

  "../odoo-$OE_VERSION-numa/odoo-bin" -c odoo.config -s --stop-after-init

  cd ..
fi

#--------------------------------------------------
# Install Nginx if needed
#--------------------------------------------------
if [ $INSTALL_NGINX = "True" ]; then
  echo -e "\n---- Installing and setting up Nginx ----"
  sudo apt install nginx -y
  cat <<EOF > ~/odoo
server {
listen 80;

# set proper server name after domain set
server_name $WEBSITE_NAME;

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
error_log       /var/log/nginx/$OE_USER-error.log;

#   increase    proxy   buffer  size
proxy_buffers   16  64k;
proxy_buffer_size   128k;

proxy_read_timeout 900s;
proxy_connect_timeout 900s;
proxy_send_timeout 900s;

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
proxy_pass    http://127.0.0.1:$OE_PORT;
# by default, do not forward anything
proxy_redirect off;
}

location /longpolling {
proxy_pass http://127.0.0.1:$LONGPOLLING_PORT;
}
location ~* .js|css|png|jpg|jpeg|gif|ico$ {
expires 2d;
proxy_pass http://127.0.0.1:$OE_PORT;
add_header Cache-Control "public, no-transform";
}
# cache some static data in memory for 60mins.
location ~ /[a-zA-Z0-9_-]*/static/ {
proxy_cache_valid 200 302 60m;
proxy_cache_valid 404      1m;
proxy_buffering    on;
expires 864000;
proxy_pass    http://127.0.0.1:$OE_PORT;
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
  sudo add-apt-repository ppa:certbot/certbot -y && sudo apt-get update -y
  sudo apt-get install python-certbot-nginx -y
  sudo certbot --nginx -d $WEBSITE_NAME --noninteractive --agree-tos --email $ADMIN_EMAIL --redirect
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
