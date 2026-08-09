# Dependency audit policy

Every release runs `pip-audit`, `npm audit` and `cargo audit`. Machine-readable
reports are retained as the `dependency-audit-results` CI artifact for 30 days.
Any high or critical npm advisory and any Python/Rust advisory blocks release.

An exception is allowed only when the vulnerable code is demonstrably
unreachable in the shipped build and no safe upgrade exists. It must be added
before the release and approved during security review.

| Advisory | Package/version | Reachability evidence | Compensating control | Owner | Expires | Review link |
|---|---|---|---|---|---|---|
| RUSTSEC-2026-0124 | `libcrux-chacha20poly1305 0.0.7` | Absent from `cargo tree --locked --target wasm32-unknown-unknown`; optional HPKE libcrux backend is not compiled | Shipped suite uses `openmls_rust_crypto`/RustCrypto AES-128-GCM | Security | 2026-09-30 | Pending upstream OpenMLS/HPKE refresh |
| RUSTSEC-2026-0207 | `libcrux-sha3 0.0.8` | Crate is linked through HPKE, but the affected incremental SHAKE multi-squeeze API is not used by the fixed MLS suite | Fixed suite is X25519/AES-128-GCM/SHA-256/Ed25519 | Security | 2026-09-30 | Pending upstream OpenMLS/HPKE refresh |
| RUSTSEC-2026-0208 | `libcrux-sha3 0.0.8` | Crate is linked, but the affected AVX2 SHAKE-256 path cannot execute in browser WASM | Fixed suite uses SHA-256 and browser WASM target | Security | 2026-09-30 | Pending upstream OpenMLS/HPKE refresh |
| RUSTSEC-2026-0209 | `libcrux-aesgcm 0.0.7` | Absent from `cargo tree --locked --target wasm32-unknown-unknown` | Shipped provider is RustCrypto AES-GCM; application payloads are size-limited | Security | 2026-09-30 | Pending upstream OpenMLS/HPKE refresh |
| RUSTSEC-2026-0211 | `libcrux-aesgcm 0.0.7` | Absent from the shipped wasm target tree | Shipped provider is RustCrypto AES-GCM | Security | 2026-09-30 | Pending upstream OpenMLS/HPKE refresh |
| RUSTSEC-2026-0212 | `libcrux-secrets 0.0.5` | Crate is linked through HPKE, but the affected AArch64 native-code swap/select implementation cannot execute in browser WASM | Browser WASM target is not AArch64 native code | Security | 2026-09-30 | Pending upstream OpenMLS/HPKE refresh |

These are proposed exceptions, not approved exceptions. The release workflow
does not ignore them and remains red until the independent security review adds
an approval link or an upstream dependency update removes them.

The AES-GCM and ChaCha proposals cover packages retained in `Cargo.lock`
through the optional HPKE libcrux backend. `cargo tree --locked --target
wasm32-unknown-unknown` and `cargo tree --locked --target all` produce no
reverse path to `hpke-rs-libcrux`; the shipped provider path is
`hpke-rs-rust-crypto`. SHA3/secrets support is linked by `hpke-rs`, but the
affected algorithms/platform paths are outside the fixed MLS suite and browser
WASM target. These exceptions do not authorize a new ciphersuite or enabling
the libcrux backend. Remove each ignore as soon as an OpenMLS-compatible HPKE
release refreshes the graph.

## Last verified result

Audit date: 2026-08-09.

- `pip-audit`: no known vulnerabilities in `requirements.lock`.
- `npm audit`: no known vulnerabilities after upgrading to Vite 8.2.1.
- `cargo audit`: six advisories matched the proposed exceptions above and still
  block release pending independent approval; three unmaintained-crate warnings
  remain informational and require review on the next OpenMLS upgrade.

Expired exceptions block release. Removing or weakening an audit command also
requires security review.
