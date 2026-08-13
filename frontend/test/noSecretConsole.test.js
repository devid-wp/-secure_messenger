import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { test } from 'vitest'

test('frontend does not log render errors, payloads, keys, or tokens to the console', async () => {
  const source = await readFile(new URL('../src/components/ErrorBoundary.jsx', import.meta.url), 'utf8')
  assert.doesNotMatch(source, /console\.(?:log|debug|info|warn|error)\s*\(/)
  assert.doesNotMatch(source, /componentStack|error-boundary-stack/)
})
