import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { access } from 'node:fs/promises';
const client = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const ui = path.resolve(client, '../ui');
const output = path.resolve(client, 'build/web');
await access(path.join(output, 'index.html'));
const { build } = await import(pathToFileURL(path.join(ui, 'node_modules/vite/dist/node/index.js')).href);
await build({ root: ui, configFile: false, publicDir: false,
  resolve: { alias: { firebase: path.join(ui, 'node_modules/firebase') } },
  build: { target: 'es2022', outDir: output, emptyOutDir: false, sourcemap: false,
    lib: { entry: path.join(client, 'web/corte_auth.js'), name: 'CorteWebBridge', formats: ['iife'], fileName: () => 'corte_auth.bundle.js' } },
});
