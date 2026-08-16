import { defineConfig, devices } from '@playwright/test'
import process from 'node:process'

const deployedBaseUrl = process.env.PLAYWRIGHT_BASE_URL

export default defineConfig({
  testDir: './e2e',
  timeout: 120_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['list'], ['github']] : 'list',
  use: {
    baseURL: deployedBaseUrl || 'http://127.0.0.1:5173',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  ],
  webServer: deployedBaseUrl ? undefined : [
    {
      command: 'python scripts/run_e2e_server.py',
      cwd: '..',
      url: 'http://127.0.0.1:8000/docs',
      timeout: 120_000,
      reuseExistingServer: false,
    },
    {
      command: 'npm run dev -- --host 127.0.0.1',
      cwd: '.',
      env: { VITE_API_URL: 'http://127.0.0.1:8000' },
      url: 'http://127.0.0.1:5173',
      timeout: 120_000,
      reuseExistingServer: false,
    },
  ],
})
