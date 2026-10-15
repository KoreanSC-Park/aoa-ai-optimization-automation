import { Agent } from 'node:http'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        // Reuse loopback sockets to avoid truncated close responses on Windows.
        agent: new Agent({ keepAlive: true }),
      },
    },
  },
})
