#!/usr/bin/env bash
set -euo pipefail

DB_PATH="${TRENDRADAR_DB_PATH:-/home/liu/trendradar-data/trendradar.db}"
BACKUP_DIR="${BACKUP_DIR:-/home/liu/trendradar-backups}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"

mkdir -p "$BACKUP_DIR"

if [ ! -f "$DB_PATH" ]; then
  echo "Database file not found: $DB_PATH" >&2
  exit 1
fi

STAMP="$(date +%F)"
OUT_FILE="${BACKUP_DIR}/trendradar-${STAMP}.db"

sqlite3 "$DB_PATH" ".backup '${OUT_FILE}'"
find "$BACKUP_DIR" -maxdepth 1 -name 'trendradar-*.db' -type f -mtime +"$RETENTION_DAYS" -delete
echo "SQLite hot backup completed: $OUT_FILE"
