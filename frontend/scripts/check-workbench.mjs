import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { getDocument } from 'pdfjs-dist/legacy/build/pdf.mjs';
import { locations } from '../src/workbench.ts';

// Consumes real backend responses exported by the isolated Python smoke test.
const fixture = JSON.parse(await readFile(process.argv[2], 'utf8'));
const root = fileURLToPath(new URL('../public/pdfjs/', import.meta.url)).replaceAll('\\', '/');
assert.equal(fixture.snapshot.risks.length, 2);
const loading = getDocument({
  data: new Uint8Array(await readFile(process.argv[3])),
  cMapUrl: `${root}cmaps/`, cMapPacked: true,
  standardFontDataUrl: `${root}standard_fonts/`, wasmUrl: `${root}wasm/`, iccUrl: `${root}iccs/`,
});
try {
  const pdf = await loading.promise;
  const highlights = fixture.snapshot.risks.flatMap(risk => {
    const rects = risk.anchors.flatMap(anchor => locations(anchor, fixture.document, fixture.mapping));
    assert.ok(rects.length, `Risk ${risk.rule_id} has no reliable locations`);
    assert.ok(rects.every(rect => rect.page <= pdf.numPages));
    return rects;
  });
  let text = '';
  for (let number = 1; number <= pdf.numPages; number++) {
    const page = await pdf.getPage(number);
    text += (await page.getTextContent()).items.map(item => item.str ?? '').join('');
    const viewport = page.getViewport({ scale: 1 });
    const target = pdf.canvasFactory.create(Math.ceil(viewport.width), Math.ceil(viewport.height));
    await page.render({ canvas: target.canvas, viewport }).promise;
    const pixels = target.context.getImageData(0, 0, target.canvas.width, target.canvas.height).data;
    assert.ok(pixels.some((value, index) => index % 4 !== 3 && value < 200), 'PDF rendered blank');
    pdf.canvasFactory.destroy(target);
  }
  assert.match(text, /软件/);
  console.log(`PASS ${fixture.name}: ${pdf.numPages} page(s), ${highlights.length} regions, Chinese text and Node canvas`);
} finally {
  await loading.destroy();
}
