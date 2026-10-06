import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Let the dev server read designs/, incidents/, scenarios/ and engine/ from the project root.
    fs: { allow: ['..'] },
  },
  // The engine worker loads Pyodide with a dynamic import, which needs an ES module worker.
  worker: { format: 'es' },
})
