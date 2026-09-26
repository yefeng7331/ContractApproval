import { cp, mkdir } from 'node:fs/promises';

// Keep PDF fonts and decoders local; the installed lockfile pins their version.
const root = new URL('../', import.meta.url);
for (const name of ['cmaps', 'standard_fonts', 'wasm', 'iccs']) {
  const destination = new URL(`public/pdfjs/${name}/`, root);
  await mkdir(destination, { recursive: true });
  await cp(new URL(`node_modules/pdfjs-dist/${name}/`, root), destination, { recursive: true });
}
