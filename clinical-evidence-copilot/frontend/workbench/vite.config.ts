import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import {defineConfig} from 'vite';

export default defineConfig({
  base: '/workbench/',
  plugins: [react(), tailwindcss()],
  build: {
    outDir: '../../src/clinical_intelligence/copilot/static/gemini',
    emptyOutDir: true,
    sourcemap: false,
  },
  // The shipped build is served by Python; Node is only a development tool.
  server: {
    host: '127.0.0.1',
    proxy: {
      '/api': 'http://127.0.0.1:8857',
      '/ui': 'http://127.0.0.1:8857',
    },
  },
});
