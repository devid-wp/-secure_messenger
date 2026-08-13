import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const nginx = readFileSync(new URL('../nginx.conf', import.meta.url), 'utf8')
const html = readFileSync(new URL('../index.html', import.meta.url), 'utf8')

describe('browser E2EE delivery hardening', () => {
  it('uses a deny-by-default same-origin CSP with narrowly scoped WASM and Worker support', () => {
    expect(nginx).toContain("default-src 'none'")
    expect(nginx).toContain("script-src 'self' 'wasm-unsafe-eval'")
    expect(nginx).toContain("worker-src 'self'")
    expect(nginx).toContain("connect-src 'self'")
    expect(nginx).toContain("object-src 'none'")
    expect(nginx).toContain("base-uri 'none'")
    expect(nginx).toContain("frame-ancestors 'none'")
    expect(nginx).not.toMatch(/script-src[^;]*'unsafe-eval'/)
    expect(nginx).not.toMatch(/script-src[^;]*'unsafe-inline'/)
  })

  it('ships no inline or remote scripts', () => {
    expect(html).not.toMatch(/<script(?![^>]*\bsrc=)/i)
    expect(html).not.toMatch(/<script[^>]+src=["']https?:/i)
  })

  it('sets transport and browser privacy headers', () => {
    expect(nginx).toContain('Strict-Transport-Security')
    expect(nginx).toContain('Referrer-Policy "no-referrer"')
    expect(nginx).toContain('Permissions-Policy')
    expect(nginx).toContain('X-Content-Type-Options "nosniff"')
  })
})
