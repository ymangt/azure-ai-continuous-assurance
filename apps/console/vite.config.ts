import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const sampleArtifactsModule = 'virtual:aica-sample-artifacts';
const resolvedSampleArtifactsModule = `\0${sampleArtifactsModule}`;
const repositoryRoot = fileURLToPath(new URL('../../', import.meta.url));

const sampleArtifactPaths = {
  baselinePackage: 'data/sample-runs/baseline/package.json',
  baselineManifest: 'data/sample-runs/baseline/run-manifest.json',
  remediatedPackage: 'data/sample-runs/remediated/package.json',
  remediatedManifest: 'data/sample-runs/remediated/run-manifest.json',
  sampleDiff: 'data/sample-runs/remediated/diff.json',
} as const;

function sampleArtifactsPlugin() {
  return {
    name: 'aica-sample-artifacts',
    resolveId(id: string) {
      return id === sampleArtifactsModule ? resolvedSampleArtifactsModule : undefined;
    },
    load(id: string) {
      if (id !== resolvedSampleArtifactsModule) return undefined;

      // The private API image is built from apps/console as an isolated Docker context.
      // It never loads fixture mode, so keep its unused fixture chunk dependency-free.
      if (process.env.VITE_DATA_SOURCE === 'api') {
        return Object.keys(sampleArtifactPaths)
          .map((name) => `export const ${name} = {};`)
          .join('\n');
      }

      return Object.entries(sampleArtifactPaths)
        .map(([name, relativePath]) => (
          `export const ${name} = ${readFileSync(`${repositoryRoot}${relativePath}`, 'utf8')};`
        ))
        .join('\n');
    },
  };
}

export default defineConfig({
  plugins: [react(), sampleArtifactsPlugin()],
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
    port: 4173,
    proxy: {
      '/api': {
        target: process.env.AICA_API_ORIGIN ?? 'http://127.0.0.1:8000',
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
