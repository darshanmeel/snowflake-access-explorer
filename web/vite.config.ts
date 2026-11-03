/// <reference types="vitest/config" />
import { resolve } from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// npm run build    -> dist/     local SPA, served by server.py
// npm run build:st -> dist-st/  Streamlit component (st_react.py): relative paths, no CDN, no worker, no data: URLs,
//                               one JS + one CSS file, index.html at its root (Streamlit in Snowflake CSP).
export default defineConfig(({ mode }) => {
  const st = mode === "st";
  return {
    // st: no crossorigin on the stylesheet, so it loads even if Snowflake serves the component from another origin
    plugins: [react(), ...(st ? [{ name: "no-crossorigin", transformIndexHtml: (h: string) => h.replace(/ crossorigin/g, "") }] : [])],
    base: "./",
    root: st ? resolve(import.meta.dirname, "st") : import.meta.dirname,
    build: {
      outDir: resolve(import.meta.dirname, st ? "dist-st" : "dist"),
      emptyOutDir: true,
      chunkSizeWarningLimit: 2500,
      assetsInlineLimit: st ? 0 : 4096,
      cssCodeSplit: false,
      rollupOptions: st ? { output: { inlineDynamicImports: true } } : undefined,
    },
    // npm run dev: the page from Vite, /api from server.py (ACCESS_API_PORT, default 8000)
    server: { proxy: { "/api": `http://127.0.0.1:${process.env.ACCESS_API_PORT || 8000}` } },
    // threads: the default forks pool times out starting its workers on Windows
    test: { environment: "jsdom", pool: "threads", root: import.meta.dirname },
  };
});
