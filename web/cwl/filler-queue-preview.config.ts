import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig({
  plugins: [react()],
  publicDir: false,
  build: {
    emptyOutDir: false,
    rollupOptions: { input: "filler-queue-preview.html" },
  },
});
