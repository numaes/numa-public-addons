#!/bin/bash
# Verifica que odoo_install.sh emita exactamente los scripts que corren en produccion.
#
#     ./tests/test_install_scripts.sh
#
# Existe por una falla concreta: los heredocs de este instalador se escribieron sin
# comillas en el delimitador, asi que el shell expandia cada $VAR y $(...) al GENERAR, y
# lo que quedaba en disco eran los valores congelados del momento de la instalacion:
#
#     if [ $# -ne 2 ]     ->  if [ 0 -ne 2 ]            (siempre verdadero)
#     DATE="$(date ...)"  ->  DATE="2025-08-26-00-18-19"
#     for DB in $DBS      ->  for DB in ;               (ni siquiera es sintaxis valida)
#
# El dbbackup.sh de produccion quedo asi durante mas de un año: imprimia su mensaje de uso
# y salia. No habia respaldos, y nada lo avisaba. Un error que no se nota es el que
# necesita una prueba; este tarda dos segundos y no necesita base de datos ni red.
#
# La otra mitad de lo que cuida es la deriva: el instalador y produccion tienden a
# separarse porque cuando algo falla en una instalacion se parchea la salida, con el
# cliente esperando, y el generador queda como estaba. Si eso vuelve a pasar, el diff de
# abajo lo dice en el commit siguiente.
#
# Para aceptar un cambio deliberado en los scripts generados:
#     ./tests/test_install_scripts.sh --update    (y revisar el diff antes de commitear)
set -uo pipefail

cd "$(dirname "$0")/.."
INSTALLER="odoo_install.sh"
EXPECTED="tests/expected"
UPDATE=0
[ "${1:-}" = "--update" ] && UPDATE=1

[ -f "$INSTALLER" ] || { echo "No encuentro $INSTALLER" >&2; exit 1; }

WORK="$(mktemp -d -t install-scripts-XXXXXX)"
trap 'rm -rf "$WORK"' EXIT

# Valores fijos de instalacion, para que la salida sea reproducible. Los scripts que SI
# deben interpolar (start.sh, onboot.sh) usan estos; los que no, no deben usar ninguno.
export OE_VERSION="18.0" PROJECT="cm" CWD="/opt/cm-18.0"

# --- 1. extraer los bloques `cat ... > ./<nombre> <<DELIM` -----------------------------
# Se descubren solos: renombrar un delimitador o agregar un script nuevo no rompe nada.
awk '
    !inblock {
        if ($0 ~ /^[[:space:]]*cat[[:space:]].*>[[:space:]]*\.\/[A-Za-z0-9._-]+[[:space:]]*$/ ||
            $0 ~ /^[[:space:]]*cat[[:space:]].*>[[:space:]]*\.\/[A-Za-z0-9._-]+[[:space:]]/ ||
            $0 ~ /^[[:space:]]*cat[[:space:]]*>[[:space:]]*\.\/[A-Za-z0-9._-]+[[:space:]]*<</) {
            line = $0
            if (match(line, /<<[[:space:]]*'"'"'?[A-Za-z0-9_]+'"'"'?/)) {
                d = substr(line, RSTART + 2, RLENGTH - 2)
                gsub(/[[:space:]]|'"'"'/, "", d)
                delim = d
                inblock = 1
                print line
                next
            }
        }
        next
    }
    { print }
    $0 == delim { inblock = 0 }
' "$INSTALLER" > "$WORK/generate.sh"

# Cuerpos crudos de los bloques cuyo delimitador esta entrecomillado: son los que, por
# definicion, deben salir sin ninguna interpolacion.
mkdir -p "$WORK/raw"
awk -v out="$WORK/raw" '
    !inblock {
        if ($0 ~ /^[[:space:]]*cat[[:space:]].*>[[:space:]]*\.\// &&
            match($0, /<<[[:space:]]*'"'"'[A-Za-z0-9_]+'"'"'/)) {
            d = substr($0, RSTART + 2, RLENGTH - 2)
            gsub(/[[:space:]]|'"'"'/, "", d)
            delim = d
            match($0, /\.\/[A-Za-z0-9._-]+/)
            name = substr($0, RSTART + 2, RLENGTH - 2)
            inblock = 1
            next
        }
        next
    }
    $0 == delim { inblock = 0; close(out "/" name); next }
    { print > (out "/" name) }
' "$INSTALLER"

BLOCKS=$(grep -c '^[[:space:]]*cat' "$WORK/generate.sh" || true)
if [ "$BLOCKS" -lt 4 ]; then
    echo "FALLA: esperaba al menos 4 bloques generadores en $INSTALLER, encontre $BLOCKS." >&2
    echo "       ¿Cambio la forma de los heredocs? Revisa la extraccion en este test." >&2
    exit 1
fi

# --- 2. ejecutarlos -------------------------------------------------------------------
( cd "$WORK" && bash generate.sh ) || { echo "FALLA: los bloques generadores no corren." >&2; exit 1; }

GENERATED=$(cd "$WORK" && ls -1 *.sh 2>/dev/null | grep -v '^generate\.sh$' || true)
[ -n "$GENERATED" ] || { echo "FALLA: no se genero ningun script." >&2; exit 1; }

FAILED=0
report () { echo "  $1"; }

echo "Scripts generados por $INSTALLER ($BLOCKS bloques):"
for f in $GENERATED; do

    # --- 3. tiene que ser bash valido ---
    if ! bash -n "$WORK/$f" 2>"$WORK/$f.err"; then
        report "FALLA  $f: no es sintaxis valida"
        sed 's/^/         /' "$WORK/$f.err"
        FAILED=1
        continue
    fi

    # --- 4. si el delimitador esta entrecomillado, no puede haber habido expansion ---
    # Invariante directa en vez de buscar huellas conocidas: un heredoc con delimitador
    # entrecomillado tiene que salir byte a byte igual al cuerpo que esta en el fuente.
    # Un primer intento de este test buscaba las firmas del bug de 2025-08-26
    # (`if [ 0 -ne 2 ]`, `DATE="2025-..."`), y no disparo: estaban calcadas de la forma
    # vieja del script. Un chequeo que no se dispara es peor que no tenerlo.
    if [ -f "$WORK/raw/$f" ]; then
        if ! diff -q "$WORK/raw/$f" "$WORK/$f" >/dev/null; then
            report "FALLA  $f: el delimitador esta entrecomillado pero la salida no es literal"
            diff -u "$WORK/raw/$f" "$WORK/$f" | head -20 | sed 's/^/         /'
            FAILED=1
            continue
        fi
    fi

    # --- 5. tiene que empezar con shebang (sin el, dash lo toma y `source` no existe) ---
    if [ "$(head -1 "$WORK/$f")" != "#!/bin/bash" ]; then
        report "FALLA  $f: sin shebang #!/bin/bash en la primera linea"
        FAILED=1
        continue
    fi

    # --- 6. byte a byte contra la copia buena ---
    if [ "$UPDATE" -eq 1 ]; then
        mkdir -p "$EXPECTED"
        cp "$WORK/$f" "$EXPECTED/$f"
        report "actualizado  $EXPECTED/$f"
    elif [ ! -f "$EXPECTED/$f" ]; then
        report "FALLA  $f: no hay copia buena en $EXPECTED/. Si es nuevo y correcto: --update"
        FAILED=1
    elif ! diff -q "$EXPECTED/$f" "$WORK/$f" >/dev/null; then
        report "FALLA  $f: difiere de $EXPECTED/$f"
        diff -u "$EXPECTED/$f" "$WORK/$f" | sed 's/^/         /'
        FAILED=1
    else
        report "ok     $f"
    fi
done

# --- 7. odoo.config: propiedades, no comparacion byte a byte ---------------------------
# Sus valores dependen de la maquina ($(nproc)) y del proyecto, asi que una copia buena no
# serviria. Lo que si tiene que valer siempre son estas relaciones -- y todas estuvieron
# rotas: el blando era mayor que el duro (8,29 GB contra 1,6 GB), no se emitia `workers`
# en absoluto, y db_maxconn quedaba en el valor suelto de 64 aunque es por proceso.
echo
echo "odoo.config generado:"
CFG_SRC=$(awk '/^ *cat > odoo\.config <<EOF$/{f=1;next} f&&/^EOF$/{exit} f' "$INSTALLER")
if [ -z "$CFG_SRC" ]; then
    report "FALLA  no pude extraer el bloque de odoo.config"
    FAILED=1
else
    render_config () {  # render_config <INSTALL_NGINX> <output file>
        ( export OE_PORT=8069 LONGPOLLING_PORT=8072 OE_ADMIN_PASSWD=generated-secret \
                 OE_SUPERADMIN=admin INSTALL_NGINX="$1" DATA_DIR=./data \
                 IS_ENTERPRISE=False INSTALL_PRIVATE=True PROJECT_REPO=True
          OE_CORES=$(nproc 2>/dev/null || echo 2)
          OE_WORKERS=$(( OE_CORES * 2 + 1 )); [ "$OE_WORKERS" -gt 9 ] && OE_WORKERS=9
          OE_DB_MAXCONN=$(( 90 / (OE_WORKERS + 2) ))
          OE_MAJOR="${OE_VERSION%%.*}"
          eval "cat <<EOF
$CFG_SRC
EOF" ) > "$2" 2>/dev/null
    }
    render_config True "$WORK/odoo.config"
    render_config False "$WORK/odoo-no-nginx.config"

    val () { sed -n "s/^$1 *= *//p" "$WORK/odoo.config" | head -1; }
    W=$(val workers); SOFT=$(val limit_memory_soft); HARD=$(val limit_memory_hard)
    TCPU=$(val limit_time_cpu); TREAL=$(val limit_time_real); MAXC=$(val db_maxconn)

    check () {  # check <condicion-ok> <mensaje>
        if [ "$1" = "ok" ]; then report "ok     $2"; else report "FALLA  $2"; FAILED=1; fi
    }
    [ -n "$W" ] && [ "$W" -ge 1 ] 2>/dev/null && R=ok || R=no
    check "$R" "workers = ${W:-<ausente>} (sin esto Odoo corre en un solo proceso)"

    [ -n "$SOFT" ] && [ -n "$HARD" ] && [ "$SOFT" -lt "$HARD" ] 2>/dev/null && R=ok || R=no
    check "$R" "limit_memory_soft ($SOFT) < limit_memory_hard ($HARD)"

    [ -n "$HARD" ] && [ "$HARD" -ge 2147483648 ] 2>/dev/null && R=ok || R=no
    check "$R" "limit_memory_hard >= 2 GB (wkhtmltopdf lo hereda como RLIMIT_AS)"

    [ -n "$TCPU" ] && [ -n "$TREAL" ] && [ "$TCPU" -lt "$TREAL" ] 2>/dev/null && R=ok || R=no
    check "$R" "limit_time_cpu ($TCPU) < limit_time_real ($TREAL)"

    [ -n "$TREAL" ] && [ "$TREAL" -le 1800 ] 2>/dev/null && R=ok || R=no
    check "$R" "limit_time_real ($TREAL) <= 1800 (2 horas retenia el worker demasiado)"

    if [ -n "$MAXC" ] && [ -n "$W" ]; then
        TOTAL=$(( MAXC * (W + 2) ))
        [ "$TOTAL" -le 90 ] && R=ok || R=no
        check "$R" "db_maxconn ($MAXC) x ($W workers + 2 crons) = $TOTAL <= 90 conexiones"
    else
        check no "db_maxconn ausente"
    fi

    grep -q '^longpolling_port' "$WORK/odoo.config" && R=no || R=ok
    check "$R" "sin longpolling_port (en Odoo >= 16 la opcion es gevent_port)"

    # Incident 2026-09-12: a database manager reachable from the internet, guarded by a guessable
    # master password, let an attacker drop the production database of another installation.
    [ "$(val list_db)" = "False" ] && R=ok || R=no
    check "$R" "list_db = False (the database manager is disabled)"

    [ "$(val admin_passwd)" = "generated-secret" ] && R=ok || R=no
    check "$R" "admin_passwd comes from OE_ADMIN_PASSWD"

    grep -qE 'read .*-i "True" GENERATE_RANDOM_PASSWORD' "$INSTALLER" && R=ok || R=no
    check "$R" "the master password is random unless the operator chooses otherwise"

    [ "$(val http_interface)" = "127.0.0.1" ] && R=ok || R=no
    check "$R" "http_interface = 127.0.0.1 behind nginx (nothing bypasses the proxy)"

    grep -q '^http_interface' "$WORK/odoo-no-nginx.config" && R=no || R=ok
    check "$R" "no http_interface without nginx (Odoo stays reachable on its port)"
fi

# --- 8. nginx site: properties of each variant, then nginx -t when docker is available ---------
# Every fix here was found on a production host on 2026-09-13:
# - `server localhost:PORT` resolved to 127.0.0.1 and 127.0.1.1, and Odoo listens only on the first,
#   so nginx failed and retried half of its upstream connections (164 errors in one day).
# - Nothing blocked /web/database, the entry point of the 2026-09-12 incident.
# - A second domain needs to be in server_name and in the certificate.
# - With the stock default site removed, a host no site names fell into the first Odoo site loaded,
#   answering with another site's certificate and a 502.
echo
echo "nginx generated:"
extract_function () {  # extract_function <name>: body up to its "} # end <name>" marker
    awk -v name="$1" '$0 ~ "^" name "\\(\\) \\{$" {f=1} f {print} f && $0 == "} # end " name {exit}' "$INSTALLER"
}
NGINX_FUNCTIONS="$(extract_function write_nginx_site)
$(extract_function write_nginx_catch_all)
$(extract_function version_at_least)"
if ! printf '%s\n' "$NGINX_FUNCTIONS" | grep -q '^} # end write_nginx_site$' ||
   ! printf '%s\n' "$NGINX_FUNCTIONS" | grep -q '^} # end write_nginx_catch_all$' ||
   ! printf '%s\n' "$NGINX_FUNCTIONS" | grep -q '^} # end version_at_least$'; then
    report "FALLA  could not extract write_nginx_site, write_nginx_catch_all and version_at_least"
    FAILED=1
else
    eval "$NGINX_FUNCTIONS"
    OE_PORT=8069 LONGPOLLING_PORT=8072
    write_nginx_site "$WORK/site-ssl.conf" True cm.example.com pn.example.com
    write_nginx_site "$WORK/site-http.conf" False cm.example.com
    write_nginx_catch_all "$WORK/catch-all-reject.conf" True
    write_nginx_catch_all "$WORK/catch-all-snakeoil.conf" False

    has ()   { grep -qF -- "$2" "$WORK/$1" && R=ok || R=no; check "$R" "$1 has: $2"; }
    lacks () { grep -qF -- "$2" "$WORK/$1" && R=no || R=ok; check "$R" "$1 lacks: $2"; }

    for f in site-ssl.conf site-http.conf; do
        lacks "$f" "localhost"
        has   "$f" " server 127.0.0.1:8069;"
        has   "$f" " server 127.0.0.1:8072;"
        has   "$f" "location ~* ^/+web/database {"
        has   "$f" "proxy_set_header X-Forwarded-Host \$host;"
        lacks "$f" "HTTP_X_FORWARDED_HOST"
        has   "$f" "access_log /var/log/nginx/cm.example.com-access.log;"
    done
    [ "$(grep -c 'server_name cm.example.com pn.example.com;' "$WORK/site-ssl.conf")" -eq 2 ] && R=ok || R=no
    check "$R" "site-ssl.conf names both domains in the http and https servers"
    has   site-ssl.conf  "return 301 https://\$host\$request_uri;"
    has   site-ssl.conf  "ssl_certificate /etc/letsencrypt/live/cm.example.com/fullchain.pem;"
    has   site-ssl.conf  'add_header Strict-Transport-Security'
    lacks site-http.conf "ssl"
    lacks site-http.conf "Strict-Transport-Security"
    lacks site-http.conf "return 301"
    has   catch-all-reject.conf   "listen 443 ssl default_server;"
    has   catch-all-reject.conf   "ssl_reject_handshake on;"
    has   catch-all-reject.conf   "return 444;"
    has   catch-all-snakeoil.conf "ssl_certificate /etc/ssl/certs/ssl-cert-snakeoil.pem;"
    lacks catch-all-snakeoil.conf "ssl_reject_handshake"

    # ssl_reject_handshake exists since nginx 1.19.4; Ubuntu 22.04 still ships 1.18.
    version_at_least 1.18.0 1.19.4 && R=no || R=ok;  check "$R" "1.18.0 is older than 1.19.4"
    version_at_least 1.19.4 1.19.4 && R=ok || R=no;  check "$R" "1.19.4 is at least 1.19.4"
    version_at_least 1.24.0 1.19.4 && R=ok || R=no;  check "$R" "1.24.0 is at least 1.19.4"

    # nginx -t on the real parser, both pairs of files, when docker and the image are at hand.
    NGINX_IMAGE="nginx:1.27-alpine"
    if command -v docker >/dev/null 2>&1 && docker image inspect "$NGINX_IMAGE" >/dev/null 2>&1; then
        mkdir -p "$WORK/le" "$WORK/snakeoil" "$WORK/conf-ssl" "$WORK/conf-http"
        openssl req -x509 -nodes -newkey rsa:2048 -days 1 -subj "/CN=cm.example.com" \
            -keyout "$WORK/le/privkey.pem" -out "$WORK/le/fullchain.pem" >/dev/null 2>&1
        cp "$WORK/le/fullchain.pem" "$WORK/snakeoil/cert.pem"; cp "$WORK/le/privkey.pem" "$WORK/snakeoil/key.pem"
        cp "$WORK/site-ssl.conf" "$WORK/catch-all-reject.conf" "$WORK/conf-ssl/"
        cp "$WORK/site-http.conf" "$WORK/catch-all-snakeoil.conf" "$WORK/conf-http/"
        chmod -R a+rX "$WORK/le" "$WORK/snakeoil" "$WORK/conf-ssl" "$WORK/conf-http"
        for pair in conf-ssl conf-http; do
            if docker run --rm --network none -v "$WORK/$pair:/etc/nginx/conf.d:ro" \
                   -v "$WORK/le:/etc/letsencrypt/live/cm.example.com:ro" \
                   -v "$WORK/snakeoil/cert.pem:/etc/ssl/certs/ssl-cert-snakeoil.pem:ro" \
                   -v "$WORK/snakeoil/key.pem:/etc/ssl/private/ssl-cert-snakeoil.key:ro" \
                   "$NGINX_IMAGE" nginx -t >"$WORK/$pair.nginx-t" 2>&1; then
                report "ok     nginx -t accepts $pair"
            else
                report "FALLA  nginx -t rejects $pair"
                sed 's/^/         /' "$WORK/$pair.nginx-t"
                FAILED=1
            fi
        done
    else
        report "skip   nginx -t (needs docker and the $NGINX_IMAGE image)"
    fi
fi

echo
if [ "$UPDATE" -eq 1 ]; then
    echo "Copias buenas actualizadas. Revisa el diff antes de commitear."
    exit 0
fi
if [ "$FAILED" -eq 0 ]; then
    echo "Todo bien: el instalador emite exactamente lo que hay en $EXPECTED/."
else
    echo "Hay diferencias. Si el cambio es deliberado, corre con --update y revisa el diff."
fi
exit "$FAILED"
