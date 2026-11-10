#!/bin/sh
set -e
# First start (or SEED_RESET=true): load the bundled snapshot into the data volume.
if [ ! -f /data/tgtg_halal.sqlite3 ] || [ "$SEED_RESET" = "true" ]; then
  cp /seed/tgtg_halal.sqlite3 /data/tgtg_halal.sqlite3
  echo "Loaded bundled data snapshot."
fi
exec "$@"
