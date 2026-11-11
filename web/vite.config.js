import { defineConfig } from 'vite';
export default defineConfig({
  build: { outDir: '../ares/static', emptyOutDir: true },
  server: { proxy: { '/projects': 'http://127.0.0.1:8000', '/session': 'http://127.0.0.1:8000', '/capabilities': 'http://127.0.0.1:8000' } }
});
