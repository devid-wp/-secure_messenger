#!/usr/bin/env bash
set -euo pipefail
umask 077

# Creates an opaque database + object-storage backup. The deployment env file
# is never copied into the backup directory and secrets are never printed.
: "${DEPLOY_ENV_FILE:?set DEPLOY_ENV_FILE to the protected production env file}"
: "${BACKUP_DIR:?set BACKUP_DIR to a protected backup destination}"

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_root="${BACKUP_DIR%/}/secure-messenger-${timestamp}"
mkdir -p "$backup_root/storage"

compose=(docker compose --env-file "$DEPLOY_ENV_FILE" -f compose.yaml)

"${compose[@]}" exec -T db sh -ec \
  'pg_dump --format=custom --no-owner --no-privileges --username "$POSTGRES_USER" --dbname "$POSTGRES_DB"' \
  > "$backup_root/postgres.dump"

"${compose[@]}" exec -T minio sh -ec \
  'mc alias set backup http://localhost:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null && mc mirror --quiet "backup/$S3_BUCKET" /tmp/secure-messenger-backup' \
  >/dev/null
"${compose[@]}" cp minio:/tmp/secure-messenger-backup/. "$backup_root/storage/"
"${compose[@]}" exec -T minio rm -rf /tmp/secure-messenger-backup >/dev/null

(
  cd "$backup_root"
  sha256sum postgres.dump
  find storage -type f -print0 | sort -z | xargs -0 -r sha256sum
) > "$backup_root/SHA256SUMS"
printf '%s\n' "$timestamp" > "$backup_root/created-at.txt"

printf 'Backup created: %s\n' "$backup_root"
