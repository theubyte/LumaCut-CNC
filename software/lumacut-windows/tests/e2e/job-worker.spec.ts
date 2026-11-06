import { expect, test } from '@playwright/test';

// Der Auftrag läuft wirklich im Web Worker: Oberfläche bleibt frei, ein neuer Lauf bricht den alten ab, Fehler kommen an.
test('Auftrag im Worker', async ({ page }) => {
  await page.goto('/');
  const r = await page.evaluate(async () => {
    const client = await import('/src/core/jobClient.ts' as string);
    const model = await import('/src/core/model.ts' as string);
    const rasterMod = await import('/src/core/raster.ts' as string);
    const w = 1000, g = new Uint8Array(w * w).map((_, i) => (i * 37) & 255);
    const d = model.newDoc('Foto');
    d.elements.push(model.newElement(d.layers[0].id, 'Bild', { transform: { x: 40, y: 40, scaleX: 1, scaleY: 1, rotation: 0 }, raster: rasterMod.rasterOf(w, w, g), imageWidthMm: 200, imageHeightMm: 200, imageMode: 'DITHER' }));
    let ticks = 0, maxGap = 0, last = performance.now();
    const timer = setInterval(() => { const n = performance.now(); maxGap = Math.max(maxGap, n - last); last = n; ticks++; }, 10);
    const first = client.buildJob(d).then(() => 'fertig', (e: Error) => e.name);
    const t0 = performance.now();
    const job = await client.buildJob(d);
    const ms = performance.now() - t0;
    clearInterval(timer);
    const empty = await client.buildJob(model.newDoc('Leer')).catch((e: Error) => `${e.name}: ${e.message}`);
    return { first: await first, ms, ticks, maxGap, lines: job.toolpath.lineCount, xy: job.toolpath.xy.constructor.name, count: job.toolpath.count, seconds: job.stats.seconds, head: job.gcode.slice(0, 30), empty };
  });
  console.log(JSON.stringify(r));
  expect(r.first).toBe('JobAborted');
  expect(r.xy).toBe('Float32Array');
  expect(r.count).toBeGreaterThan(1000);
  expect(r.head).toContain('LumaCut App');
  expect(r.empty).toContain('JobBuildError: Nichts zu lasern');
  expect(r.ticks).toBeGreaterThan(5);
  expect(r.maxGap).toBeLessThan(500);
});
