import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 前端 dev server 走 5173，API 反代到后端 8000，避免跨域配置。
export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
  build: { outDir: "dist", sourcemap: false },
});
