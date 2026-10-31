import path from 'node:path'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'

// 127.0.0.1 (not "localhost"): on Windows localhost can resolve to IPv6 while uvicorn listens on IPv4
const api = process.env.VITE_PROXY_TARGET ?? 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { '@': path.resolve(__dirname, 'src') } },
  server: {
    port: 5173,
    proxy: { '/api': { target: api, changeOrigin: true, ws: true } },
  },
})
