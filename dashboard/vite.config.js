// Vite config — production assets served under FastAPI mount /ui (Docker + pilot).
// Dev: open http://127.0.0.1:8787/ui/  (base is /ui/ so paths match the container).
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  base: "/ui/",
  server: {
    port: 8787,
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/ws": {
        target: "http://127.0.0.1:8000",
        ws: true,
      },
      "/health": "http://127.0.0.1:8000",
    },
  },
});
