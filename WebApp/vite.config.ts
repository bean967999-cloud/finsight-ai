import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: { outDir: "Build" },
  server: {
    host: "127.0.0.1",
    port: 59318,
    strictPort: true,
    proxy: {
      "/api": { target: "http://127.0.0.1:9300", changeOrigin: false },
      "/health": { target: "http://127.0.0.1:9300", changeOrigin: false },
    },
  },
});
