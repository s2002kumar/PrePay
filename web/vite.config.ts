/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vite";

// The live server sends these as headers; a static host cannot, so the static build carries them.
const STATIC_CSP =
  "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; " +
  "font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'";

function staticHeaders(): Plugin {
  return {
    name: "prepay-static-headers",
    transformIndexHtml: () => [
      { tag: "meta", attrs: { "http-equiv": "Content-Security-Policy", content: STATIC_CSP }, injectTo: "head-prepend" },
      { tag: "meta", attrs: { name: "referrer", content: "no-referrer" }, injectTo: "head-prepend" },
    ],
  };
}

// `vite build --mode static` builds the static site, which reads precomputed API responses from
// <base>/data/ (src/static.ts); PREPAY_BASE sets its path prefix, e.g. /PrePay/ on GitHub Pages.
export default defineConfig(({ mode }) => ({
  base: process.env.PREPAY_BASE ?? "/",
  define: { "import.meta.env.VITE_PREPAY_STATIC": JSON.stringify(mode === "static" ? "1" : "0") },
  plugins: [react(), ...(mode === "static" ? [staticHeaders()] : [])],
  server: { proxy: { "/api": "http://127.0.0.1:8000" } },
  build: { outDir: "dist", sourcemap: false, assetsDir: "assets" },
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{ts,tsx}"],
    setupFiles: ["src/test-setup.ts"],
  },
}));
