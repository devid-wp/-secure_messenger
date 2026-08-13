import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'node',
    include: ['test/**/*.test.js'],
    restoreMocks: true,
  },
  server: {
    port: 5173,
    strictPort: true,
  },
})
