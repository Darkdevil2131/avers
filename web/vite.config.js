import { defineConfig } from 'vite';
const revision = process.env.ARES_BUILD_REVISION || '';
export default defineConfig({
  define: { __ARES_BUILD_REVISION__: JSON.stringify(/^[a-f0-9]{40}$/i.test(revision) ? revision.toLowerCase() : 'unknown') },
  build: { outDir: '../ares/static', emptyOutDir: true },
  server: { proxy: { '/projects': 'http://127.0.0.1:8000', '/session': 'http://127.0.0.1:8000', '/capabilities': 'http://127.0.0.1:8000' } }
});
