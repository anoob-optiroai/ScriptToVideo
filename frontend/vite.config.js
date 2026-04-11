import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:8000',
      '/downloads': 'http://localhost:8000',
      '/videos': 'http://localhost:8000',
    }
  }
})
