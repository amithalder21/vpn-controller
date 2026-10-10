import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

// Dev: app served at "/", /api proxied to the Flask controller on :8088.
// Build: assets under "/static/" and emitted into ../controller/static so the
// existing Flask app serves the SPA with no backend changes.
export default defineConfig(({ mode }) => ({
  base: mode === "production" ? "/static/" : "/",
  plugins: [react()],
  resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8088",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: path.resolve(__dirname, "../controller/static"),
    emptyOutDir: true,
    chunkSizeWarningLimit: 1200,
  },
}));
