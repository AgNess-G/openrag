import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";
import { viteSingleFile } from "vite-plugin-singlefile";

export default defineConfig({
  plugins: [react(), viteSingleFile()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "../frontend"),
    },
  },
  build: {
    outDir: "dist",
    rollupOptions: {
      input: [process.env.INPUT || "settings-app.html"],
    },
    emptyOutDir: false,
  },
  css: {
    postcss: "./postcss.config.mjs",
  },
});
