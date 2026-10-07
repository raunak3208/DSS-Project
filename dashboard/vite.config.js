import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server proxies /api to the controller (docker compose publishes it on :8080).
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/api": process.env.API_URL || "http://localhost:8080" } },
});
