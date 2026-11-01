import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
// Static fixture only: no API proxy and no Discord connection.
export default defineConfig({
  plugins: [react()],
  build: { rollupOptions: { input: "declaration-ping-preview.html" } },
});
