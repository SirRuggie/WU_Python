import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig({
  plugins: [react()],
  publicDir: false,
  build: { rollupOptions: { input: "return-reminders-simple-preview.html" } },
});
