import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Let the dev server read designs/, incidents/, scenarios/ and engine/ from the project root.
    fs: { allow: ['..'] },
    // The leaderboard API runs on Cloudflare; during development, use the live one.
    proxy: { '/api': { target: 'https://scale-or-fail.pages.dev', changeOrigin: true } },
  },
  // The engine worker loads Pyodide with a dynamic import, which needs an ES module worker.
  worker: { format: 'es' },
  // One screen that needs React Flow and the YAML parser up front, so one bundle is fine.
  // (Pyodide itself loads separately, in the background, from its CDN.)
  build: { chunkSizeWarningLimit: 800 },
})
