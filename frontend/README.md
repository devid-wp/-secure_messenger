# Secure Messenger Frontend

A React and Vite client for Secure Messenger.

## Development

From the `frontend` directory:

```shell
npm ci
npm run dev
```

The application is available at `http://localhost:5173`. During local development,
the backend is expected at `http://localhost:8000`. Set `VITE_API_URL` to use a
different backend origin.

## Production build

```shell
npm ci
npm run lint
npm run typecheck
npm run build
npm test
```

The generated static files are written to `dist`.

## Docker

The repository-level `compose.yaml` builds this frontend and serves it through
Nginx at `http://localhost:8080` for local testing only. Nginx also proxies API
and WebSocket traffic to the backend container. Production must place it behind
an HTTPS ingress; browser E2EE must never be delivered over public HTTP.

## Requirements

- Node.js 20.19.0 and npm 10.8.2
- Rust 1.88.0 with the `wasm32-unknown-unknown` target
- `wasm-bindgen-cli` 0.2.126
