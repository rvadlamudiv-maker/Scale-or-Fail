import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Let the dev server read designs/ and incidents/ from the project root (one level up).
    fs: { allow: ['..'] },
  },
})
