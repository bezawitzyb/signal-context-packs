import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Development: `npm run dev` on :5173, with /api and /mcp sent to the backend on :7860 (start.sh).
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      "/api": "http://127.0.0.1:7860",
      "/mcp": "http://127.0.0.1:7860",
    },
  },
  build: { outDir: "dist", sourcemap: false },
});
