import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const api = 'http://127.0.0.1:8765'
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': api,
      '/ingest': api,
      '/ws': { target: api.replace('http', 'ws'), ws: true },
    },
  },
})
