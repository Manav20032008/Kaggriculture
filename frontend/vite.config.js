import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'
import { env } from 'node:process'

const backendTarget = env.VITE_BACKEND_URL || 'http://127.0.0.1:8000'
const apiProxy = {
  '/api': {
    target: backendTarget,
    changeOrigin: true,
    rewrite: (path) => path.replace(/^\/api/, ''),
  },
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: { proxy: apiProxy },
  preview: { proxy: apiProxy },
})
