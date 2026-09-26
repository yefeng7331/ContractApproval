import { defineConfig } from 'vite';

export default defineConfig({
  server: {
    proxy: { '/api': process.env.CONTRACT_API_PROXY_TARGET || 'http://127.0.0.1:8010' },
  },
});
