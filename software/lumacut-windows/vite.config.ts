import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import { fileURLToPath } from 'node:url';

// In the browser (tests, screenshots) /api goes through this proxy. The default is ALWAYS the
// local simulator (tools/sim_pi.py), never the real Pi: nothing in development may move the machine.
const target = process.env.LUMACUT_DEV_PI ?? 'http://127.0.0.1:8090';

export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  server: {
    port: 5183,
    strictPort: true,
    proxy: {
      // Strip Origin: the Pi rejects POST/PUT/DELETE whose Origin does not match its Host.
      '/api': { target, changeOrigin: true, configure: (p) => p.on('proxyReq', (r) => r.removeHeader('origin')) },
    },
  },
  build: { target: 'es2022', chunkSizeWarningLimit: 3000 },
  test: { environment: 'node', include: ['src/**/*.test.ts'] },
});
