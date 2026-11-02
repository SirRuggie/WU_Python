import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "../../.local/p92-preview",
    emptyOutDir: true,
    rollupOptions: { input: "pool-roles-preview.html" },
  },
});
