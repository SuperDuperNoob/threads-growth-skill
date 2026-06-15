#!/usr/bin/env bash
# Migrate ~/.orbit to the shared NAS so the Hermes agent (on the Beelink) and
# Keith's Mac use ONE config + DB. Idempotent and safe: backs up, verifies,
# and only swaps in the symlink after the copy is confirmed byte-complete.
#
# Run ON THE MAC, once, after the NAS is mounted. Then set ORBIT_HOME on both
# machines (printed at the end).
#
# Usage:
#   scripts/migrate-orbit-to-nas.sh /Volumes/<nas-share>/orbit
set -euo pipefail

DEST="${1:?Usage: migrate-orbit-to-nas.sh /Volumes/<nas-share>/orbit}"
SRC="$HOME/.orbit"
STAMP="$(date +%Y%m%d-%H%M%S)"

echo "==> Source:      $SRC"
echo "==> Destination: $DEST"

# --- guards ---------------------------------------------------------------
if [ -L "$SRC" ]; then
  echo "✓ $SRC is already a symlink → $(readlink "$SRC"). Nothing to do."
  exit 0
fi
[ -d "$SRC" ]            || { echo "✗ $SRC missing"; exit 1; }
DEST_PARENT="$(dirname "$DEST")"
[ -d "$DEST_PARENT" ]    || { echo "✗ NAS path $DEST_PARENT not mounted"; exit 1; }
# write-test the NAS so we fail before touching the source
touch "$DEST_PARENT/.orbit-write-test" && rm -f "$DEST_PARENT/.orbit-write-test" \
  || { echo "✗ NAS not writable"; exit 1; }

# --- backup ---------------------------------------------------------------
BACKUP="$SRC.bak-$STAMP"
echo "==> Backing up $SRC → $BACKUP (local, untouched safety copy)"
cp -a "$SRC" "$BACKUP"

# --- copy to NAS ----------------------------------------------------------
echo "==> Copying to NAS (rsync, preserves perms incl. 0600 config.json)..."
mkdir -p "$DEST"
rsync -a --delete "$SRC"/ "$DEST"/

# --- verify ---------------------------------------------------------------
echo "==> Verifying copy..."
for f in config.json orbit.db; do
  [ -e "$DEST/$f" ] || { echo "✗ $f missing on NAS — ABORTING, source untouched"; exit 1; }
done
SRC_DB_SIZE=$(stat -f%z "$SRC/orbit.db" 2>/dev/null || stat -c%s "$SRC/orbit.db")
DST_DB_SIZE=$(stat -f%z "$DEST/orbit.db" 2>/dev/null || stat -c%s "$DEST/orbit.db")
[ "$SRC_DB_SIZE" = "$DST_DB_SIZE" ] \
  || { echo "✗ orbit.db size mismatch ($SRC_DB_SIZE vs $DST_DB_SIZE) — ABORTING"; exit 1; }
echo "✓ config.json + orbit.db present, db sizes match ($DST_DB_SIZE bytes)"

# --- swap in symlink ------------------------------------------------------
echo "==> Replacing $SRC with a symlink → $DEST"
mv "$SRC" "$SRC.old-$STAMP"
ln -s "$DEST" "$SRC"

cat <<EOF

✓ Migration complete.
  - NAS copy:        $DEST
  - Mac symlink:     $SRC → $DEST
  - Local backup:    $BACKUP   (delete once you've confirmed things work)
  - Old dir:         $SRC.old-$STAMP

NEXT — set ORBIT_HOME on BOTH machines:

  Mac (~/.zshrc):
      export ORBIT_HOME="$DEST"
  Hermes container (wherever it mounts this NAS share):
      export ORBIT_HOME="<container-mount-path>/orbit"

VERIFY on the Mac (should work unchanged):
      ORBIT_HOME="$DEST" orbit status

ROLLBACK if anything is wrong:
      rm "$SRC" && mv "$SRC.old-$STAMP" "$SRC"
EOF
