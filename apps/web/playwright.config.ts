import { defineConfig } from "@playwright/test";

const port = Number(process.env.GAIA_WEB_TEST_PORT || 4174);

export default defineConfig({
  testDir: "./tests",
  use: { baseURL: `http://127.0.0.1:${port}` },
  webServer: {
    command: `npm run dev -- --host 127.0.0.1 --port ${port}`,
    port,
    reuseExistingServer: !process.env.CI,
  },
});
