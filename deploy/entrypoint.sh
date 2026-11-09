#!/bin/sh
# Railway mounts volumes owned by root, so take ownership of /data before dropping privileges.
set -e

if [ "$(id -u)" = "0" ]; then
    mkdir -p "$(dirname "$DB_PATH")" "$UPLOAD_DIR"
    chown -R app:app "$(dirname "$DB_PATH")" "$UPLOAD_DIR"
    exec setpriv --reuid=app --regid=app --init-groups "$@"
fi

exec "$@"
