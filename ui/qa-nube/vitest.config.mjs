import { defineConfig } from 'vitest/config';
import { fileURLToPath } from 'node:url';
export default defineConfig({
  resolve: { alias: {
    '@/dominio': fileURLToPath(new URL('../src/dominio/index.ts', import.meta.url)),
    '@/componentes': fileURLToPath(new URL('../src/componentes/index.ts', import.meta.url)),
  } },
  test: { environment: 'happy-dom', include: ['qa-nube/*.spec.ts'], fsModuleCache: false },
});
