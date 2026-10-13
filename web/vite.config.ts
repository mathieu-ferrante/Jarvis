import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Interface servie par Jarvis lui-même (FastAPI) ; en développement, l'API est relayée vers le port 8730.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8730",
      "/ws": { target: "ws://127.0.0.1:8730", ws: true },
    },
  },
  build: { outDir: "dist", sourcemap: false },
});
