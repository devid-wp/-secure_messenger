# Production deployment

## Required topology

Serve one public HTTPS origin. The TLS ingress forwards `/api/` (including the
WebSocket upgrade) and all other paths to the bundled frontend Nginx. Do not
publish backend, object storage, database, Redis, or frontend port 80 directly.
Port 80 at the public ingress exists only to return a permanent HTTPS redirect.

The checked-in Nginx configuration emits the strict document CSP, HSTS,
Referrer Policy, Permissions Policy, nosniff and frame protections. HSTS is
effective only after a response is received over HTTPS, so TLS termination and
HTTP redirect are deployment requirements, not optional application settings.
Use a valid publicly trusted certificate and automate renewal.

## Build and configuration

```shell
cd frontend
npm ci
npm audit --omit=dev
npm run lint
npm run typecheck
npm test
npm run build
```

Build from the committed `package-lock.json` and `src-wasm/Cargo.lock`. Do not
inject remote scripts, analytics, tag managers, fonts, support widgets, or a
service-worker replacement. Keep `VITE_API_URL` empty in production so API,
WebSocket, Worker and WASM traffic remains same-origin.

Set `APP_ENV=production`, a PostgreSQL `DATABASE_URL`, `REDIS_URL`, the exact
public HTTPS origin in `CORS_ORIGINS`, and production object-storage
credentials. Secrets belong in the deployment secret manager. The refresh
cookie is then `Secure`, `HttpOnly`, `SameSite=Lax`, and restricted to
`/api/v1/auth`. Never terminate TLS at the browser-facing Nginx using the
development Compose file as-is; Compose exposes HTTP solely for local testing.

## Release verification

Inspect response headers and confirm the effective CSP contains no inline
script or JavaScript eval allowance. In Chromium and Firefox test two tabs and
two independent profiles, reload after send, offline/reconnect, device removal,
a corrupt IndexedDB vault record, and a maximum-size attachment. Capture the
network trace and search the database, application logs, upload storage and
browser cache for known plaintext canaries. Release only if plaintext appears
nowhere outside the unlocked renderer.
