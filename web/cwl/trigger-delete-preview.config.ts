import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Separate static fixture build. No dev proxy or dashboard API is involved.
export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: { input: 'trigger-delete-preview.html' },
  },
})
