/// <reference types="vitest" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: { port: 3000 },
  define: { global: 'globalThis' },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
    // The Cognito pool is constructed at import time; give tests placeholder IDs.
    env: {
      VITE_COGNITO_USER_POOL_ID: 'us-east-1_testpool',
      VITE_COGNITO_CLIENT_ID: 'test-client-id',
    },
  },
})
