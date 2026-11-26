import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  plugins: [vue()],
  base: '/assets/dist/',
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: { '/api': { target: 'http://127.0.0.1:8766', changeOrigin: false } },
  },
  build: {
    outDir: '../src/quant_research/assets/dist',
    emptyOutDir: true,
    sourcemap: false,
  },
})
