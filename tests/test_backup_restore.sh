#!/bin/bash
# Runs the dbbackup.sh and dbrestore.sh that odoo_install.sh emits against a real, local PostgreSQL.
#
#     ./tests/test_backup_restore.sh
#
# test_install_scripts.sh proves the scripts are emitted byte for byte; this proves what they do
# with the filestore, which is where a wrong guess costs data:
#   - a backup includes the filestore unless --sin-filestore is given, and says which in its manifest;
#   - a restore replaces the target filestore only when the backup carries one. A backup without it
#     must never wipe the filestore already on disk (restoring over production with --production);
#   - backups from before the option (no manifest key, always a filestore/ directory) still restore
#     their filestore;
#   - KEEP counts each kind apart, so manual database-only backups never purge nightly full ones.
#
# Needs psql, pg_dump, pg_restore, createdb and dropdb for a role that may create databases. Without
# them it says so and exits 0. It creates and drops its own databases, named pn_bkptest_<pid>_*.
set -uo pipefail

cd "$(dirname "$0")/.."
INSTALLER="$PWD/odoo_install.sh"
FAILED=0
ok ()   { printf '  %-8s %s\n' "ok" "$1"; }
fail () { printf '  %-8s %s\n' "FALLA" "$1"; FAILED=$((FAILED + 1)); }
expect () { if eval "$1"; then ok "$2"; else fail "$2"; fi; }

if ! psql -d postgres -X -q -t -A -c 'SELECT 1' >/dev/null 2>&1; then
    echo "skip: no local PostgreSQL available for $(whoami)"
    exit 0
fi

PREFIX="pn_bkptest_$$"
SRC="${PREFIX}_src"
WORK="$(mktemp -d -t backup-restore-XXXXXX)"
cleanup () {
    for db in $(psql -d postgres -X -t -A -c "SELECT datname FROM pg_database WHERE datname LIKE '${PREFIX}%'"); do
        dropdb --if-exists "$db" >/dev/null 2>&1
    done
    rm -rf "$WORK"
}
trap cleanup EXIT

# --- the scripts, straight from the installer ------------------------------------------------------
INST="$WORK/cm-18.0"
mkdir -p "$INST/data/filestore"
extract () {  # extract <script name> <heredoc delimiter>
    awk -v start="cat > ./$1 <<'$2'" -v end="$2" '
        index($0, start) { f = 1; next }
        f && $0 == end { exit }
        f { print }' "$INSTALLER" > "$INST/$1"
    chmod +x "$INST/$1"
}
extract dbbackup.sh NUMA_DBBACKUP_EOF
extract dbrestore.sh NUMA_DBRESTORE_EOF
if [ ! -s "$INST/dbbackup.sh" ] || [ ! -s "$INST/dbrestore.sh" ]; then
    echo "FALLA  could not extract dbbackup.sh and dbrestore.sh from $INSTALLER" >&2
    exit 1
fi

# --- a source database the neutralisation step can work on, and its filestore ----------------------
createdb "$SRC"
psql -d "$SRC" -X -q -c "CREATE TABLE ir_config_parameter (key varchar PRIMARY KEY, value text);
                          INSERT INTO ir_config_parameter VALUES ('database.uuid', 'source-uuid');"
mkdir -p "$INST/data/filestore/$SRC/ab"
echo "attachment" > "$INST/data/filestore/$SRC/ab/abcdef"

manifest () { tar xzOf "$1" manifest | sed -n "s/^$2=//p"; }
has_filestore () { tar tzf "$1" | grep -q '^filestore/ab/abcdef$'; }

echo "dbbackup.sh:"
OUT="$(cd "$INST" && ./dbbackup.sh "$SRC" 2>&1)"
FULL="$(ls -1 "$INST/database/$SRC"-????????-??????.tar.gz 2>/dev/null | tail -1)"
expect '[ -n "$FULL" ]' "by default it writes <base>-<date>.tar.gz"
expect '[ -n "$FULL" ] && has_filestore "$FULL"' "by default the backup carries the filestore"
expect '[ -n "$FULL" ] && [ "$(manifest "$FULL" filestore)" = included ]' "the manifest says filestore=included"
expect '[ -n "$FULL" ] && [ "$(manifest "$FULL" filestore_files)" = 1 ]' "the manifest counts the filestore files"

sleep 1  # backup names carry the time to the second
OUT="$(cd "$INST" && ./dbbackup.sh "$SRC" --sin-filestore 2>&1)"
NOFS="$(ls -1 "$INST/database/$SRC"-????????-??????-sin-filestore.tar.gz 2>/dev/null | tail -1)"
expect '[ -n "$NOFS" ]' "--sin-filestore writes <base>-<date>-sin-filestore.tar.gz"
expect '[ -n "$NOFS" ] && ! tar tzf "$NOFS" | grep -q "^filestore"' "--sin-filestore leaves the filestore out"
expect '[ -n "$NOFS" ] && [ "$(manifest "$NOFS" filestore)" = excluded ]' "the manifest says filestore=excluded"
expect 'grep -qF "filestore omitted" <<< "$OUT"' "--sin-filestore says it skipped the filestore"

sleep 1
OUT="$(cd "$INST" && ./dbbackup.sh --sin-filestore "$SRC" "$(whoami)" 2>&1)"
expect '[ "$(ls -1 "$INST/database/$SRC"-*-sin-filestore.tar.gz | wc -l)" -eq 2 ]' "the option works before the base name and with a role"

OUT="$(cd "$INST" && ./dbbackup.sh "$SRC" --bogus 2>&1)"; RC=$?
expect '[ "$RC" -ne 0 ] && grep -q -- "--sin-filestore" <<< "$OUT"' "an unknown option fails and shows the usage"

echo
echo "retention by kind:"
for i in 1 2 3; do
    touch -d "2020-01-0$i 00:00" "$INST/database/$SRC-2020010${i}-000000.tar.gz" \
                                 "$INST/database/$SRC-2020010${i}-000000-sin-filestore.tar.gz"
done
FULL_BEFORE=$(ls -1 "$INST/database/$SRC"-????????-??????.tar.gz | wc -l)
sleep 1
OUT="$(cd "$INST" && KEEP=2 ./dbbackup.sh "$SRC" --sin-filestore 2>&1)"
expect '[ "$(ls -1 "$INST/database/$SRC"-*-sin-filestore.tar.gz | wc -l)" -eq 2 ]' "KEEP=2 keeps two database-only backups"
expect '[ "$(ls -1 "$INST/database/$SRC"-????????-??????.tar.gz | wc -l)" -eq "$FULL_BEFORE" ]' \
       "a database-only backup never purges full backups ($FULL_BEFORE kept)"
rm -f "$INST/database/$SRC"-2020*
# Retention purged the first database-only backup: restore from the newest one left.
NOFS="$(ls -1t "$INST/database/$SRC"-????????-??????-sin-filestore.tar.gz 2>/dev/null | head -1)"

echo
echo "dbrestore.sh:"
DB="${PREFIX}_full"
OUT="$(cd "$INST" && ./dbrestore.sh "$DB" "$FULL" 2>&1)"; RC=$?
expect '[ "$RC" -eq 0 ] && [ -f "$INST/data/filestore/$DB/ab/abcdef" ]' "a full backup restores its filestore"

DB="${PREFIX}_nofs"
OUT="$(cd "$INST" && ./dbrestore.sh "$DB" "$NOFS" 2>&1)"; RC=$?
expect '[ "$RC" -eq 0 ] && psql -d postgres -X -t -A -c "SELECT 1 FROM pg_database WHERE datname = '"'"'$DB'"'"'" | grep -q 1' \
       "a database-only backup restores the database"
expect '[ -d "$INST/data/filestore/$DB" ] && [ -z "$(ls -A "$INST/data/filestore/$DB")" ]' \
       "with no filestore on disk it leaves an empty one"
expect 'grep -qF "cp -a" <<< "$OUT" && grep -qF "$SRC" <<< "$OUT"' \
       "it warns that attachments are missing and how to copy them from $SRC"

DB="${PREFIX}_keep"
mkdir -p "$INST/data/filestore/$DB/zz"
echo "production attachment" > "$INST/data/filestore/$DB/zz/keep"
OUT="$(cd "$INST" && ./dbrestore.sh "$DB" "$NOFS" --production 2>&1)"; RC=$?
expect '[ "$RC" -eq 0 ] && [ -f "$INST/data/filestore/$DB/zz/keep" ]' "a database-only backup never touches an existing filestore"

DB="${PREFIX}_old"
OLD="$WORK/old-format.tar.gz"
mkdir -p "$WORK/old" && tar xzf "$FULL" -C "$WORK/old"
sed -i '/^filestore/d' "$WORK/old/manifest"
tar czf "$OLD" -C "$WORK/old" manifest dump.pgc filestore
OUT="$(cd "$INST" && ./dbrestore.sh "$DB" "$OLD" 2>&1)"
expect '[ -f "$INST/data/filestore/$DB/ab/abcdef" ]' "a backup from before the option restores its filestore"

echo
if [ "$FAILED" -eq 0 ]; then
    echo "Todo bien."
else
    echo "$FAILED check(s) failed."
fi
exit "$FAILED"
