import { defineConfig } from "vitest/config";
import vue from "@vitejs/plugin-vue";

export default defineConfig({
  plugins: [vue()],
  server: {
    host: "0.0.0.0",
    port: 4173,
    allowedHosts: ["frontend"],
    proxy: {
      "/api": "http://api:8000",
      "/health": "http://api:8000",
    },
  },
  test: {
    environment: "jsdom",
    clearMocks: true,
  },
});
