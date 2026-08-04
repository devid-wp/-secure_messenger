import { execFileSync } from 'node:child_process'
import { mkdirSync, rmSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const frontend = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const crate = resolve(frontend, 'src-wasm')
const target = resolve(crate, 'target', 'wasm32-unknown-unknown', 'release', 'secure_messenger_mls_wasm.wasm')
const output = resolve(frontend, 'src', 'crypto', 'wasm-generated')

rmSync(output, { recursive: true, force: true })
mkdirSync(output, { recursive: true })
execFileSync('cargo', ['build', '--locked', '--release', '--target', 'wasm32-unknown-unknown'], { cwd: crate, stdio: 'inherit' })
execFileSync('wasm-bindgen', [target, '--target', 'web', '--out-dir', output, '--out-name', 'mls'], { cwd: crate, stdio: 'inherit' })
