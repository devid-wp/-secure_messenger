# Backup, restore, and release candidate

## Backups

Run backups from a host with Docker access and a protected deployment env file:

```sh
export DEPLOY_ENV_FILE=/secure/path/production.env
export BACKUP_DIR=/secure/backups
scripts/backup-production.sh
```

The script produces a PostgreSQL custom-format dump, a mirror of the S3 bucket,
and `SHA256SUMS`. Treat backups as sensitive even though message/file payloads
are encrypted. Store them encrypted at rest with separate access controls and
retention rules.

## Restore and migration rollback on staging

Use a disposable staging stack only. The restore command is intentionally
refused unless explicitly confirmed:

```sh
export STAGING_ENV_FILE=/secure/path/staging.env
export BACKUP_PATH=/secure/backups/secure-messenger-YYYYMMDDTHHMMSSZ
export ROLLBACK_REVISION=<tested-alembic-revision>
scripts/restore-staging.sh --confirm-staging-restore
```

It verifies checksums, restores PostgreSQL and object storage, then runs
`alembic downgrade` to the supplied revision and upgrades back to `head`.
Record the revision, backup identifier, operator, and result in the release
ticket. A failed restore or rollback blocks release.

## Release candidate gate

Before creating a version/tag, use a clean staging environment and require:

1. GitHub `Release security gate` is green, including pip-audit, npm audit,
   cargo audit, Trivy image scans, migrations, unit tests, and Chromium E2E.
2. The primary flow works: register, unlock vault, create/open a chat, send and
   receive encrypted text and file, reload, unlock again, and revoke a device.
3. A backup was restored and the migration rollback/upgrade check succeeded.
4. A network trace, database dump, object store sample, logs, and metrics show
   no test plaintext or key material.
5. Container images are built from the immutable commit, signed by the release
   pipeline, and their digests are recorded beside the version tag.

When all five gates are green, run **Publish signed release** from `main` with
the chosen semantic version. The workflow refuses to run without a successful
`Release security gate` for the same commit, publishes backend/frontend images
to GHCR, signs their immutable digests with Cosign keyless GitHub OIDC,
publishes provenance attestations, and creates the annotated `v<version>` tag
and GitHub release with `release-digests.txt`.

Do not tag or publish a release if any item is missing. This repository does
not yet attest that a clean staging RC has been executed; that requires the
deployment credentials and an operator-controlled staging environment.
