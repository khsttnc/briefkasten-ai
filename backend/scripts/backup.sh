#!/usr/bin/env bash
set -euo pipefail

# Briefkasten AI - daily backup.
#
# What this does:
#   1. Takes a WAL-safe *online* backup of the live SQLite DB - no downtime,
#      no need to stop the app (see ../app/database.py's
#      PRAGMA journal_mode=WAL and https://www.sqlite.org/backup.html).
#   2. Folds the backup copy's inherited WAL flag back to a single
#      self-contained file (see comment below).
#   3. Copies it alongside the uploads/ directory into a staging folder.
#   4. Sends both to a LOCAL Restic repository (client-side encrypted,
#      deduplicated) on this same server, and prunes old snapshots there.
#   5. If a REMOTE repository is also configured (see DEPLOY.md), sends
#      the same staged backup there too. If it isn't configured, this step
#      is skipped - no error, just a log line - so this script works
#      correctly with local-only backup today and gains off-server backup
#      later by adding one file, with no other change.
#
# IMPORTANT: the local repository (step 4) protects against accidental
# deletion/application-level corruption ONLY. It lives on the same disk
# as the data it backs up, so it does NOT protect against disk failure or
# loss of the server itself - see DEPLOY.md's "Yedekleme" section for why
# an off-server (remote) repository is still required before real user
# data exists.
#
# Run as root via cron on the Hetzner host (see DEPLOY.md) - not inside a
# container, since it needs the docker CLI to locate the named volume's
# host mountpoint. Requires: sqlite3, restic, docker, and /root/.restic-env
# (sets RESTIC_LOCAL_REPOSITORY / RESTIC_LOCAL_PASSWORD_FILE - never
# committed to this repo, created once during deploy per DEPLOY.md).

COMPOSE_PROJECT_NAME="briefkasten-ai"
STAGING_DIR="/root/briefkasten-backup-staging"
KEEP_DAILY=14

# shellcheck disable=SC1091
source /root/.restic-env

_restic_ensure_initialized() {
    if ! restic cat config >/dev/null 2>&1; then
        echo "Repository not yet initialized at ${RESTIC_REPOSITORY} - initializing now."
        restic init
    fi
}

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

# --- Local repository (mandatory) ---
export RESTIC_REPOSITORY="$RESTIC_LOCAL_REPOSITORY"
export RESTIC_PASSWORD_FILE="$RESTIC_LOCAL_PASSWORD_FILE"
mkdir -p "$RESTIC_REPOSITORY"
_restic_ensure_initialized
restic backup "${STAGING_DIR}/briefkasten.db" "${STAGING_DIR}/uploads" --tag briefkasten-daily
restic forget --keep-daily "$KEEP_DAILY" --prune
echo "Local backup completed at $(date -u +%FT%TZ) -> ${RESTIC_REPOSITORY}"

# --- Remote repository (optional) ---
# /root/.restic-env-remote does not exist until a remote target (e.g. a
# Hetzner Storage Box) has actually been set up - see DEPLOY.md. Its
# absence is a normal, expected state (not an error) for as long as this
# app has no real user data yet.
if [ -f /root/.restic-env-remote ]; then
    # shellcheck disable=SC1091
    source /root/.restic-env-remote
    export RESTIC_REPOSITORY="$RESTIC_REMOTE_REPOSITORY"
    export RESTIC_PASSWORD_FILE="$RESTIC_REMOTE_PASSWORD_FILE"
    _restic_ensure_initialized
    restic backup "${STAGING_DIR}/briefkasten.db" "${STAGING_DIR}/uploads" --tag briefkasten-daily
    restic forget --keep-daily "$KEEP_DAILY" --prune
    echo "Remote backup completed at $(date -u +%FT%TZ) -> ${RESTIC_REPOSITORY}"
else
    echo "WARNING: no remote backup target configured (/root/.restic-env-remote not found)." >&2
    echo "WARNING: backups exist ONLY on this server and do NOT survive disk/server loss." >&2
    echo "WARNING: set up an off-server target before real user data exists - see DEPLOY.md 'Yedekleme'." >&2
fi

rm -rf "$STAGING_DIR"
