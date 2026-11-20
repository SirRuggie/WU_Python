import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig({
  plugins: [react()],
  publicDir: false,
  build: {
    rollupOptions: {
      input: new URL(
        "./tests/fixtures/signup-reminders-preview.html",
        import.meta.url,
      ).pathname,
    },
  },
});
