import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Relative base + HashRouter means the site works on any GitHub Pages path
// (user site or project site) with no extra configuration.
export default defineConfig({
  base: "./",
  plugins: [react()],
});
