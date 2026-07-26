import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      // ws: true -- /api/codebase-agent/connect is a WebSocket route; the
      // codebase agent dials into Obrenna's own public address, which means
      // through this same dev-server proxy, not directly at the backend port.
      '/api': { target: 'http://localhost:8000', ws: true, changeOrigin: true },
      '/health': 'http://localhost:8000',
    },
  },
})
