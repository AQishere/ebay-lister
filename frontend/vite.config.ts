import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

// In dev, /api is proxied to the FastAPI app (uvicorn on :8000 by default).
// Point it at the live API instead with VITE_API_TARGET=https://<app>.vercel.app
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  return {
    plugins: [react()],
    server: {
      proxy: {
        '/api': { target: env.VITE_API_TARGET || 'http://localhost:8000', changeOrigin: true },
      },
    },
  }
})
