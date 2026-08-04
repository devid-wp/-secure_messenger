# Secure Messenger Frontend

A React and Vite client for Secure Messenger.

## Development

From the `frontend` directory:

```powershell
npm install
npm run dev
```

The application is available at `http://localhost:5173`. During local development,
the backend is expected at `http://localhost:8000`. Set `VITE_API_URL` to use a
different backend origin.

## Production build

```powershell
npm run build
```

The generated static files are written to `dist`.

## Docker

The repository-level `compose.yaml` builds this frontend and serves it through
Nginx at `http://localhost:8080`. Nginx also proxies API and WebSocket traffic to
the backend container.

## Requirements

- Node.js 20 or newer
- npm
- Rust with the `wasm32-unknown-unknown` target
- `wasm-bindgen-cli` 0.2.126
