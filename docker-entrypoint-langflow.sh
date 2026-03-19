#!/bin/sh
set -e

# Fix ownership of the Langflow data directory so the container user (uid=1000) can write to it.
# When the directory is bind-mounted from a host with a different UID (e.g. CI runners at uid=1001),
# the container user cannot create files. Running chown here as root — before dropping privileges —
# mirrors the pattern used by official database images (OpenSearch, PostgreSQL, Redis).
chown -R 1000:1000 /app/langflow-data

# Restore HOME for uid=1000 — USER root in the Dockerfile sets HOME=/root,
# but the langflow user (uid=1000) has HOME=/app/data. Without this, uv and
# other tools try to write caches to /root/ which uid=1000 cannot access.
export HOME=/app/data

# Drop from root to uid=1000 and exec the main process.
# Python is used for privilege drop — it is guaranteed to be present in the Langflow image
# and requires no additional packages (unlike gosu or su-exec).
exec python3 -c 'import os, sys; os.setgid(1000); os.setuid(1000); os.execvp(sys.argv[1], sys.argv[1:])' "$@"
