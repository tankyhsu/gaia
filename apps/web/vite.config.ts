import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const apiKey = loadEnv(mode, ".", "").GAIA_API_KEY;
  const apiTarget =
    loadEnv(mode, ".", "").VITE_GAIA_API_TARGET || "http://127.0.0.1:8000";
  return {
    plugins: [react()],
    server: {
      port: 4173,
      proxy: {
        "/api": {
          target: apiTarget,
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/api/, ""),
          headers: apiKey ? { "X-Gaia-Api-Key": apiKey } : {},
        },
      },
    },
  };
});
