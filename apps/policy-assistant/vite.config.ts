import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('node_modules/@fluentui')) return 'fluent-ui';
          if (id.includes('node_modules/react')) return 'react-runtime';
          return undefined;
        },
      },
    },
  },
  server: {
    port: 4174,
    proxy: {
      '/api': {
        target: process.env.AICA_ASSISTANT_API_ORIGIN ?? 'http://127.0.0.1:8001',
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
    css: true,
    globals: true,
  },
});
