// import { defineConfig, loadEnv } from 'vite'
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig, loadEnv } from "vite";
import path from "path";
import { tanstackRouter } from '@tanstack/router-plugin/vite';
export default defineConfig(({ mode }) => {
  // Load env file based on `mode` in the current working directory.
  // Set the third parameter to '' to load all env regardless of the `VITE_` prefix.
  const env = loadEnv(mode, process.cwd(), "");

  return {
    base: "./",
    server: {
      // Use the VITE_PORT variable, or fallback to default 5173
      port: parseInt(env.VITE_PORT) || 5173,
      allowedHosts: ["chat.devst.dev", "localhost", "127.0.0.1", "admin.devst.dev"],
      // https: true,
    },
    plugins: [react(), tailwindcss(), tanstackRouter()],
    resolve: {
      alias: {
        "@": path.resolve(__dirname, "./src"),
      },
    },
    esbuild: {
      logOverride: { "this-is-undefined-in-esm": "silent" },
    },
  };
});
