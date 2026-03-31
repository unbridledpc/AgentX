import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  // Use relative paths so the built site can be hosted from a subfolder (e.g. http://example.com/solweb/)
  // without needing a rebuild.
  base: "./",
  server: {
    port: 5173
  }
});
