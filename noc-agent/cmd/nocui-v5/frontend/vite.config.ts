import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'node:path'

export default defineConfig({
  plugins: [react()],
  base: './',
  resolve: {
    alias: { '@': path.resolve(__dirname, './src') },
  },
  build: {
    target: 'es2022',
    outDir: 'dist',
    emptyOutDir: true,
    chunkSizeWarningLimit: 2048,
  },
  server: {
    port: 34115,
    strictPort: true,
  },
})
