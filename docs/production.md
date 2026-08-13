# Installation and production deployment

## Development

Use the pinned toolchain: Python 3.12.11, Node 20.19.0/npm 10.8.2, and Rust
1.88.0 with `wasm32-unknown-unknown`.

```sh
cd frontend
npm ci
npm run lint && npm run typecheck && npm run build && npm test
cd ..
python -m pytest
```

Do not replace the committed Python, npm, or Cargo lockfiles with ad-hoc
dependency installation.

## Production

1. Copy `.env.production.example` outside the repository and fill every
   placeholder from a secret manager. Generate independent strong PostgreSQL,
   Redis, and S3 credentials.
2. Set `PUBLIC_ORIGIN` to the one canonical `https://` browser origin and set
   `ALERT_WEBHOOK_URL` to the incident-management receiver.
3. Put an HTTPS ingress in front of `127.0.0.1:8080`. It must redirect HTTP to
   HTTPS and preserve `X-Forwarded-Proto`. Do not publish PostgreSQL, Redis,
   MinIO, Prometheus, or the backend directly.
4. Start the stack with the protected env file:

```sh
docker compose --env-file /secure/path/secure-messenger.env up -d --build
```

The Compose stack runs PostgreSQL, Redis, MinIO, a one-shot migration service,
the backend, frontend, Prometheus, blackbox exporter, and Alertmanager.
Backend startup is gated on successful migrations and its internal services are
on a private Docker network. Containers run read-only where possible and have
resource limits.

Production startup rejects SQLite, missing Redis/S3, non-HTTPS CORS origins,
placeholder credentials, and an absent or over-broad trusted proxy CIDR.

## Monitoring

Prometheus receives only aggregate operational metrics: API and WebSocket
availability, status classes, latency, active WebSocket count, MinIO capacity,
and certificate expiry. It does not receive messages, ciphertext, attachment
names, keys, access tokens, or user identifiers. Configure an authenticated
external `ALERT_WEBHOOK_URL`; do not expose Prometheus or Alertmanager publicly.
