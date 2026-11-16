import { defineConfig } from 'vitest/config';
import { fileURLToPath } from 'node:url';
export default defineConfig({
  resolve: { alias: {
    '@/dominio': fileURLToPath(new URL('../src/dominio/index.ts', import.meta.url)),
    '@/componentes': fileURLToPath(new URL('../src/componentes/index.ts', import.meta.url)),
    '@/app': fileURLToPath(new URL('../src/app/index.ts', import.meta.url)),
    '@/bloques': fileURLToPath(new URL('../src/bloques/index.ts', import.meta.url)),
    '@/datos': fileURLToPath(new URL('../src/datos/index.ts', import.meta.url)),
    '@/plataforma': fileURLToPath(new URL('../src/plataforma/index.ts', import.meta.url)),
  } },
  test: { environment: 'happy-dom', include: ['qa-nube/*.spec.ts'], fsModuleCache: false },
});
