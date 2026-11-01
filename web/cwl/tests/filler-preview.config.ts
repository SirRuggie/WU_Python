import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: path.resolve("../../.local/filler-preview"),
    emptyOutDir: true,
    rollupOptions: { input: path.resolve("roster-filler-preview.html") },
  },
});
