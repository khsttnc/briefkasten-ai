#!/usr/bin/env bash
set -euo pipefail

# Briefkasten AI - daily off-server backup.
#
# What this does:
#   1. Takes a WAL-safe *online* backup of the live SQLite DB - no downtime,
#      no need to stop the app (see ../app/database.py's
#      PRAGMA journal_mode=WAL and https://www.sqlite.org/backup.html).
#   2. Folds the backup copy's inherited WAL flag back to a single
#      self-contained file (see comment below).
#   3. Copies it alongside the uploads/ directory into a staging folder.
#   4. Sends both to an off-server Restic repository (client-side encrypted,
#      deduplicated) - see DEPLOY.md "Yedekleme" for one-time setup and the
#      restore procedure.
#   5. Prunes old snapshots per the retention policy below.
#
# Run as root via cron on the Hetzner host (see DEPLOY.md) - not inside a
# container, since it needs the docker CLI to locate the named volume's
# host mountpoint. Requires: sqlite3, restic, docker, and /root/.restic-env
# (sets RESTIC_REPOSITORY / RESTIC_PASSWORD_FILE - never committed to this
# repo, created once during deploy per DEPLOY.md).

COMPOSE_PROJECT_NAME="briefkasten-ai"
STAGING_DIR="/root/briefkasten-backup-staging"
KEEP_DAILY=14

# shellcheck disable=SC1091
source /root/.restic-env

VOLUME_NAME="$(docker volume ls -q \
    --filter "label=com.docker.compose.project=${COMPOSE_PROJECT_NAME}" \
    --filter "label=com.docker.compose.volume=db_data")"

if [ -z "$VOLUME_NAME" ]; then
    echo "ERROR: could not find the db_data volume for compose project '${COMPOSE_PROJECT_NAME}' - aborting, no backup taken." >&2
    exit 1
fi

VOLUME_MOUNTPOINT="$(docker volume inspect -f '{{ .Mountpoint }}' "$VOLUME_NAME")"

rm -rf "$STAGING_DIR"
mkdir -p "$STAGING_DIR"

# Online backup via SQLite's Backup API - safe to run against a live,
# concurrently-written WAL-mode database without stopping the app. Verified
# locally against a WAL-mode DB under concurrent writes: the resulting
# snapshot is always valid and fully queryable, never corrupt or partial.
sqlite3 "${VOLUME_MOUNTPOINT}/briefkasten.db" ".backup '${STAGING_DIR}/briefkasten.db'"

# The backup copy inherits the WAL flag from the source DB's file header,
# so simply opening it later can spawn -wal/-shm sidecar files alongside
# it. Folding the WAL back into the main file here means the staged (and
# later restored) backup is always one single, self-contained .db file -
# no sidecar files to remember to also copy during a restore.
sqlite3 "${STAGING_DIR}/briefkasten.db" "PRAGMA journal_mode=DELETE;"

cp -a "${VOLUME_MOUNTPOINT}/uploads" "${STAGING_DIR}/uploads"

restic backup "${STAGING_DIR}/briefkasten.db" "${STAGING_DIR}/uploads" \
    --tag briefkasten-daily

restic forget --keep-daily "$KEEP_DAILY" --prune

rm -rf "$STAGING_DIR"

echo "Backup completed at $(date -u +%FT%TZ)."
