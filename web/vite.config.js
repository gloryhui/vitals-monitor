import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

export default defineConfig({
  base: "/tools/vitals/",
  plugins: [vue()],
  build: {
    outDir: "..",
    emptyOutDir: false,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes("node_modules/echarts") || id.includes("node_modules/zrender")) {
            return "echarts";
          }
        },
      },
    },
  },
  server: {
    port: 5180,
    proxy: {
      "/api": "http://127.0.0.1:8790",
    },
  },
});
