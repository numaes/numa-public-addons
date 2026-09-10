#!/bin/bash
# Verifica lo que odoo_check.sh sabe del AMBIENTE, no de sus scripts: que detecte -- y
# arregle -- un venv que es copia de otro, que sepa decir si el codigo en disco es el que
# esta corriendo, y si algun modulo instalado quedo atras del manifiesto.
#
#     ./tests/test_check_environment.sh
#
# Existe por un caso real: un test-18.0 clonado de prod-18.0 copiando el directorio. El
# venv copiado seguia diciendo ser el de produccion, y como odoo-bin arranca con
# `#!/usr/bin/env python3`, el PATH que ese activate exportaba decidia que site-packages
# se usaban. El ambiente de prueba corria con las bibliotecas de produccion durante meses,
# sin sintoma: los dos python3 son el mismo binario del sistema.
set -uo pipefail

cd "$(dirname "$0")/.."
CHECK="$PWD/odoo_check.sh"
FAILED=0

ok ()   { printf '  %-8s %s\n' "ok" "$1"; }
fail () { printf '  %-8s %s\n' "FALLA" "$1"; FAILED=$((FAILED + 1)); }

WORK="$(mktemp -d -t check-venv-XXXXXX)"
trap 'rm -rf "$WORK"' EXIT

OTHER="/opt/otro-ambiente-18.0/venv"
INST="$WORK/cm-18.0"
mkdir -p "$INST/venv/bin" "$WORK/numa-public-odoo-18.0-numa"

cat > "$INST/odoo.config" <<CFG
[options]
addons_path = ../numa-public-odoo-18.0-numa/addons
admin_passwd = x
db_user = x
CFG

# Un venv como el que deja copiar un directorio: todo adentro sigue nombrando al original.
cat > "$INST/venv/bin/activate" <<ACT
VIRTUAL_ENV=$OTHER
export VIRTUAL_ENV
PATH="\$VIRTUAL_ENV/bin:\$PATH"
ACT
cat > "$INST/venv/pyvenv.cfg" <<CFGV
home = /usr/bin
version = 3.11.13
command = /usr/bin/python3.11 -m venv $OTHER
CFGV
printf '#!%s/bin/python3.11\nprint(1)\n' "$OTHER" > "$INST/venv/bin/pip"
chmod +x "$INST/venv/bin/pip"

echo "Un venv copiado de otro ambiente:"
OUT="$("$CHECK" "$INST" 2>&1)"
grep -qF "el venv dice ser $OTHER" <<< "$OUT" \
    && ok "lo detecta y dice de quien es" \
    || fail "no detecto el venv ajeno"
grep -q "arrancan con un python de otro lado" <<< "$OUT" \
    && ok "detecta los shebangs que apuntan afuera" \
    || fail "no detecto los shebangs ajenos"
grep -qF "$OTHER" "$INST/venv/bin/activate" \
    && ok "sin --fix no toca nada" \
    || fail "modifico el venv sin que se lo pidieran"

echo
echo "Con --fix:"
OUT="$("$CHECK" "$INST" --fix 2>&1)"
grep -q "venv reapuntado" <<< "$OUT" \
    && ok "dice que lo reapunto" \
    || fail "no informo la correccion"
grep -qF "VIRTUAL_ENV=$INST/venv" "$INST/venv/bin/activate" \
    && ok "activate apunta a este ambiente" \
    || fail "activate sigue apuntando afuera"
grep -qF "m venv $INST/venv" "$INST/venv/pyvenv.cfg" \
    && ok "pyvenv.cfg corregido" \
    || fail "pyvenv.cfg sigue apuntando afuera"
head -1 "$INST/venv/bin/pip" | grep -qF "#!$INST/venv/bin/python3.11" \
    && ok "el shebang de pip apunta adentro" \
    || fail "el shebang de pip sigue apuntando afuera"
ls "$INST/venv/bin/activate".bak-* >/dev/null 2>&1 \
    && ok "guardo backup de cada archivo tocado" \
    || fail "no dejo backup"

echo
echo "Ya corregido:"
OUT="$("$CHECK" "$INST" 2>&1)"
grep -q "el venv es de este ambiente" <<< "$OUT" \
    && ok "la segunda pasada lo da por bueno" \
    || fail "sigue reportando el venv"
grep -q "los scripts de bin/ usan el python de este venv" <<< "$OUT" \
    && ok "los shebangs quedaron adentro" \
    || fail "sigue reportando shebangs ajenos"

echo
echo "deployed.txt: el codigo en disco contra el que corre"
REPO="$WORK/un-repo"
mkdir -p "$REPO" && git -C "$REPO" init -q 2>/dev/null
git -C "$REPO" -c user.email=t@t -c user.name=t commit -q --allow-empty -m x 2>/dev/null
SHA="$(git -C "$REPO" rev-parse --short HEAD)"

cat > "$INST/deployed.txt" <<DEP
arrancado:  2026-01-01T00:00:00-03:00
venv:       $INST/venv
--- repositorios ---
0000000    18.0           $REPO
--- paquetes ---
DEP
OUT="$("$CHECK" "$INST" 2>&1)"
grep -q "corriendo 0000000, el checkout ya esta en $SHA" <<< "$OUT" \
    && ok "avisa que alguien hizo pull y no reinicio" \
    || fail "no detecto la diferencia entre disco y proceso"

sed -i "s/^0000000/$SHA   /" "$INST/deployed.txt"
OUT="$("$CHECK" "$INST" 2>&1)"
grep -q "el codigo en disco es el mismo que esta corriendo" <<< "$OUT" \
    && ok "cuando coinciden, lo dice" \
    || fail "no reconocio que coinciden"

cat > "$INST/deployed.txt" <<DEP
arrancado:  2026-01-01T00:00:00-03:00
venv:       $OTHER
--- repositorios ---
--- paquetes ---
DEP
OUT="$("$CHECK" "$INST" 2>&1)"
grep -qF "lo que corre usa el venv $OTHER" <<< "$OUT" \
    && ok "detecta que el proceso vivo usa otro venv" \
    || fail "no detecto el venv ajeno en el proceso vivo"

echo
echo "Modulos instalados contra el manifiesto en disco"
# Sin costura habria que levantar una base para probar una comparacion de cadenas.
mkdir -p "$WORK/addons/mod_viejo" "$WORK/addons/mod_al_dia" "$WORK/addons/mod_con_serie"
printf "{'name': 'v', 'version': '1.2'}\n"       > "$WORK/addons/mod_viejo/__manifest__.py"
printf "{'name': 'a', 'version': '1.2'}\n"       > "$WORK/addons/mod_al_dia/__manifest__.py"
printf "{'name': 's', 'version': '18.0.2.0'}\n"  > "$WORK/addons/mod_con_serie/__manifest__.py"
sed -i "s#^addons_path = .*#addons_path = $WORK/addons#" "$INST/odoo.config"

export ODOO_CHECK_MODULES_CMD="printf 'mod_viejo|18.0.1.1\nmod_al_dia|18.0.1.2\nmod_con_serie|18.0.2.0\nmod_fantasma|18.0.9.9\n'"
OUT="$("$CHECK" "$INST" 2>&1)"
unset ODOO_CHECK_MODULES_CMD

grep -q "mod_viejo: la base corrio 18.0.1.1 y el manifiesto ya dice 18.0.1.2" <<< "$OUT" \
    && ok "detecta el modulo que quedo atras" \
    || fail "no detecto el modulo desactualizado"
grep -q "mod_al_dia" <<< "$OUT" \
    && fail "reporto un modulo al dia (no antepuso la serie al manifiesto)" \
    || ok "un manifiesto '1.2' equivale a 18.0.1.2 en la base"
grep -q "mod_con_serie" <<< "$OUT" \
    && fail "reporto un modulo cuyo manifiesto ya trae la serie" \
    || ok "un manifiesto que ya trae la serie no se le antepone otra"
grep -q "mod_fantasma" <<< "$OUT" \
    && fail "opino sobre un modulo que no esta en este addons_path" \
    || ok "calla sobre los modulos que no estan en disco aca"
grep -q "necesitan -u sobre" <<< "$OUT" \
    && ok "dice como actualizarlos" \
    || fail "no dijo como actualizar"

OUT="$("$CHECK" "$INST" 2>&1)"
grep -q "sin base con que comparar" <<< "$OUT" \
    && ok "sin base, lo dice en vez de callar" \
    || fail "no aviso que le falta la base"

echo
echo "El candado de mantenimiento"
{ date +%s; echo x; } > "$INST/mantenimiento.lock"
OUT="$("$CHECK" "$INST" 2>&1)"
grep -q "mantenimiento en curso" <<< "$OUT" \
    && ok "avisa que hay un mantenimiento en curso" \
    || fail "no menciono el candado"
rm -f "$INST/mantenimiento.lock"

echo
if [ "$FAILED" -eq 0 ]; then
    echo "Todo bien."
    exit 0
fi
echo "$FAILED comprobacion(es) fallaron."
exit 1
