import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Component tests (R12): real components in a simulated browser (jsdom), the
// server faked per test (tests/support.jsx). Run with the rest of the suite
// by tests/run.sh, or on their own: npm test.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    include: ['tests/**/*.test.{js,jsx}'],
    setupFiles: ['tests/setup.js'],
    restoreMocks: true,
  },
})
