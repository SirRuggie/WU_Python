import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig({
  plugins: [react()],
  publicDir: "tests/fixtures/base-bank-public",
  build: { rollupOptions: { input: "base-bank-preview.html" } },
});
