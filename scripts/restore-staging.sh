#!/usr/bin/env bash
set -euo pipefail
umask 077

# This script is deliberately staging-only. It restores opaque records and
# verifies a downgrade/upgrade cycle without displaying database or media data.
if [[ "${1:-}" != "--confirm-staging-restore" ]]; then
  printf '%s\n' 'Refusing to restore. Pass --confirm-staging-restore for a disposable staging environment.' >&2
  exit 64
fi
: "${STAGING_ENV_FILE:?set STAGING_ENV_FILE to the protected staging env file}"
: "${BACKUP_PATH:?set BACKUP_PATH to one backup directory}"
: "${ROLLBACK_REVISION:?set ROLLBACK_REVISION to the tested Alembic revision}"

case "${BACKUP_PATH}" in
  /*) ;;
  *) printf '%s\n' 'BACKUP_PATH must be absolute.' >&2; exit 64 ;;
esac

for required_file in "$BACKUP_PATH/postgres.dump" "$BACKUP_PATH/SHA256SUMS"; do
  [[ -f "$required_file" ]] || { printf 'Missing backup file: %s\n' "$required_file" >&2; exit 66; }
done

(
  cd "$BACKUP_PATH"
  sha256sum --check SHA256SUMS
)

compose=(docker compose --env-file "$STAGING_ENV_FILE" -f compose.yaml)
"${compose[@]}" exec -T db sh -ec \
  'pg_restore --clean --if-exists --no-owner --no-privileges --username "$POSTGRES_USER" --dbname "$POSTGRES_DB"' \
  < "$BACKUP_PATH/postgres.dump"

"${compose[@]}" cp "$BACKUP_PATH/storage/." minio:/tmp/secure-messenger-restore/
"${compose[@]}" exec -T minio sh -ec \
  'mc alias set restore http://localhost:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null && mc mirror --quiet --overwrite /tmp/secure-messenger-restore "restore/$S3_BUCKET" && rm -rf /tmp/secure-messenger-restore' \
  >/dev/null

"${compose[@]}" run --rm migrate python -m alembic downgrade "$ROLLBACK_REVISION"
"${compose[@]}" run --rm migrate python -m alembic upgrade head
"${compose[@]}" exec -T db sh -ec \
  'pg_isready --username "$POSTGRES_USER" --dbname "$POSTGRES_DB"' >/dev/null

printf '%s\n' 'Staging restore and migration rollback/upgrade verification completed.'
