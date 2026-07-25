import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const apiKey = loadEnv(mode, ".", "").GAIA_API_KEY;
  return {
    plugins: [react()],
    server: {
      port: 4173,
      proxy: {
        "/api": {
          target: "http://localhost:8000",
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/api/, ""),
          headers: apiKey ? { "X-Gaia-Api-Key": apiKey } : {},
        },
      },
    },
  };
});
