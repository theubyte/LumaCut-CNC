import { test, expect, type Page } from '@playwright/test';

/**
 * The design editor with real mouse and keyboard. Geometry is read back from the document through
 * the dev hook `window.__lc`, screen positions are derived from the current view.
 */
interface Pt { x: number; y: number }
const shot = (name: string) => `tests/e2e/screenshots/motiv-${name}.png`;

async function open(page: Page, theme: 'light' | 'dark' = 'light') {
  await page.addInitScript((t) => { localStorage.setItem('lc.theme', JSON.stringify(t)); localStorage.setItem('lc.dest', JSON.stringify('motiv')); }, theme);
  await page.goto('/');
  await expect(page.getByTestId('canvas')).toBeVisible();
  await page.waitForFunction(() => !!(window as any).__lc);
  await page.waitForTimeout(150);
}
const els = (page: Page) => page.evaluate(() => (window as any).__lc.useDoc.getState().doc.elements.map((e: any) => ({ id: e.id, kind: e.kind, layerId: e.layerId, plate: e.plate, t: e.transform, text: e.text, n: e.paths.length, pts: e.paths.flat().length, curves: e.curves })));
const selection = (page: Page) => page.evaluate(() => (window as any).__lc.useDoc.getState().selection as string[]);
const pastLen = (page: Page) => page.evaluate(() => (window as any).__lc.useDoc.getState().past.length as number);
/** Bounds in mm of one element, in world coordinates. */
const bounds = (page: Page, i = -1) => page.evaluate((i) => {
  const d = (window as any).__lc.useDoc.getState().doc, e = d.elements.at(i), t = e.transform, r = t.rotation * Math.PI / 180, c = Math.cos(r), s = Math.sin(r);
  const pts = e.paths.flat().map((p: Pt) => ({ x: p.x * t.scaleX * c - p.y * t.scaleY * s + t.x, y: p.x * t.scaleX * s + p.y * t.scaleY * c + t.y }));
  const xs = pts.map((p: Pt) => p.x), ys = pts.map((p: Pt) => p.y);
  return { minX: Math.min(...xs), maxX: Math.max(...xs), minY: Math.min(...ys), maxY: Math.max(...ys) };
}, i);
/** Screen position of a work-area point. */
async function at(page: Page, mm: Pt): Promise<Pt> {
  const box = (await page.getByTestId('canvas').boundingBox())!;
  const v = await page.evaluate(() => { const s = (window as any).__lc.useEditor.getState(); return { z: s.zoom, x: s.panX, y: s.panY }; });
  return { x: box.x + mm.x * v.z + v.x, y: box.y + mm.y * v.z + v.y };
}
async function drag(page: Page, a: Pt, b: Pt, steps = 8) {
  const p = await at(page, a), q = await at(page, b);
  await page.mouse.move(p.x, p.y); await page.mouse.down(); await page.mouse.move(q.x, q.y, { steps }); await page.mouse.up();
}
async function drawRect(page: Page, a: Pt, b: Pt) { await page.keyboard.press('r'); await drag(page, a, b); }
const clickMm = async (page: Page, mm: Pt) => { const p = await at(page, mm); await page.mouse.click(p.x, p.y); };

test('leerer Zustand lädt ein und führt zur Form', async ({ page }) => {
  await open(page);
  await expect(page.getByTestId('empty-state')).toBeVisible();
  await page.getByRole('button', { name: 'Form zeichnen' }).click();
  await expect(page.getByTestId('tool-rect')).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByTestId('tool-hint')).toContainText('Rechteck');
  await drag(page, { x: 50, y: 60 }, { x: 110, y: 100 });
  await expect(page.getByTestId('empty-state')).toBeHidden();
});

test('Rechteck zeichnen, verschieben, skalieren, drehen, ein Undo je Schritt', async ({ page }) => {
  await open(page);
  await drawRect(page, { x: 50, y: 60 }, { x: 110, y: 100 });
  let [r] = await els(page);
  expect(r.kind).toBe('Rechteck');
  let b = await bounds(page);
  expect(b.minX).toBeCloseTo(50, 0); expect(b.maxX).toBeCloseTo(110, 0); expect(b.maxY).toBeCloseTo(100, 0);
  expect(await pastLen(page)).toBe(1);
  await expect(page.getByTestId('tool-select')).toHaveAttribute('aria-pressed', 'true');

  // Move by dragging the outline: exactly one more undo step for the many mouse moves.
  await drag(page, { x: 65, y: 60 }, { x: 105, y: 90 });
  b = await bounds(page);
  expect(b.minX).toBeCloseTo(90, 0); expect(b.minY).toBeCloseTo(90, 0);
  expect(await pastLen(page)).toBe(2);

  // Scale at the east handle: only the width changes.
  await drag(page, { x: 150, y: 110 }, { x: 190, y: 110 });
  b = await bounds(page);
  expect(b.maxX).toBeCloseTo(190, 0); expect(b.maxY - b.minY).toBeCloseTo(40, 0);
  expect(await pastLen(page)).toBe(3);

  // Corner handle keeps the proportion (lock is on by default).
  const w0 = b.maxX - b.minX, h0 = b.maxY - b.minY;
  await drag(page, { x: b.maxX, y: b.maxY }, { x: b.maxX + 20, y: b.maxY + 2 });
  b = await bounds(page);
  expect((b.maxX - b.minX) / (b.maxY - b.minY)).toBeCloseTo(w0 / h0, 1);
  expect(await pastLen(page)).toBe(4);

  // Rotate at the handle above the frame, Shift snaps to 15 degrees.
  const cx = (b.minX + b.maxX) / 2, cy = (b.minY + b.maxY) / 2;
  const top = await at(page, { x: cx, y: b.minY });
  const c = await at(page, { x: cx, y: cy });
  await page.mouse.move(top.x, top.y - 24); await page.mouse.down();
  await page.keyboard.down('Shift');
  const rad = Math.hypot(top.x - c.x, top.y - 24 - c.y);
  await page.mouse.move(c.x + rad * Math.sin(Math.PI / 6), c.y - rad * Math.cos(Math.PI / 6), { steps: 8 });
  await page.keyboard.up('Shift'); await page.mouse.up();
  [r] = await els(page);
  expect(r.t.rotation).toBeCloseTo(30, 3);
  expect(await pastLen(page)).toBe(5);

  // Undo walks back one user action at a time.
  await page.keyboard.press('Control+z');
  [r] = await els(page);
  expect(r.t.rotation).toBeCloseTo(0, 3);
  await page.keyboard.press('Control+z');
  b = await bounds(page);
  expect(b.maxX - b.minX).toBeCloseTo(w0, 0);
  await page.keyboard.press('Control+y');
  await page.keyboard.press('Control+z');
  await page.keyboard.press('Control+z'); await page.keyboard.press('Control+z'); await page.keyboard.press('Control+z');
  expect(await els(page)).toHaveLength(0);
});

test('Tastatur: Pfeile, Duplizieren, Kopieren, Löschen, Alles', async ({ page }) => {
  await open(page);
  await drawRect(page, { x: 50, y: 60 }, { x: 80, y: 90 });
  const x0 = (await els(page))[0].t.x;
  await page.keyboard.press('ArrowRight'); expect((await els(page))[0].t.x).toBeCloseTo(x0 + 0.1, 3);
  await page.keyboard.press('Shift+ArrowRight'); expect((await els(page))[0].t.x).toBeCloseTo(x0 + 1.1, 3);
  await page.keyboard.press('Control+ArrowRight'); expect((await els(page))[0].t.x).toBeCloseTo(x0 + 11.1, 3);
  await page.keyboard.press('Control+d');
  expect(await els(page)).toHaveLength(2);
  await page.keyboard.press('Control+c'); await page.keyboard.press('Control+v');
  expect(await els(page)).toHaveLength(3);
  await page.keyboard.press('Control+a');
  expect(await selection(page)).toHaveLength(3);
  await page.keyboard.press('Control+g');
  expect((await page.evaluate(() => (window as any).__lc.useDoc.getState().doc.elements.map((e: any) => e.groupId))).every(Boolean)).toBe(true);
  await page.keyboard.press('Escape');
  await clickMm(page, { x: 61.1 + 15, y: 60 });
  expect(await selection(page)).toHaveLength(3);
  await page.keyboard.press('Delete');
  expect(await els(page)).toHaveLength(0);
});

test('Rahmen aufziehen, Umschalt für Mehrfachauswahl, Ausrichten', async ({ page }) => {
  await open(page);
  await drawRect(page, { x: 50, y: 60 }, { x: 80, y: 80 });
  await drawRect(page, { x: 100, y: 90 }, { x: 150, y: 130 });
  await page.keyboard.press('Escape');
  await drag(page, { x: 40, y: 50 }, { x: 160, y: 140 });
  expect(await selection(page)).toHaveLength(2);
  await page.keyboard.press('Escape');
  await clickMm(page, { x: 65, y: 60 });
  const p = await at(page, { x: 125, y: 90 });
  await page.keyboard.down('Shift'); await page.mouse.click(p.x, p.y); await page.keyboard.up('Shift');
  expect(await selection(page)).toHaveLength(2);
  await page.getByTestId('align-left').click();
  const [a, b] = [await bounds(page, 0), await bounds(page, 1)];
  expect(a.minX).toBeCloseTo(b.minX, 3);
});

test('Text setzen und ändern, Pfade folgen', async ({ page }) => {
  await open(page);
  await page.keyboard.press('t');
  await clickMm(page, { x: 60, y: 120 });
  await expect(page.getByTestId('text-input')).toBeFocused();
  await page.waitForFunction(() => (window as any).__lc.useDoc.getState().doc.elements.length === 1);
  const before = await bounds(page);
  await page.getByTestId('text-input').fill('LumaCut Studio');
  await page.waitForFunction(() => (window as any).__lc.useDoc.getState().doc.elements[0].text === 'LumaCut Studio');
  const after = await bounds(page);
  expect(after.maxX - after.minX).toBeGreaterThan((before.maxX - before.minX) * 2);
  expect((await els(page))[0].n).toBeGreaterThan(10);
  // Stays text: font size rebuilds the outlines, the words remain.
  const size = page.getByRole('textbox', { name: 'Schriftgröße' });
  await size.fill('20'); await size.press('Enter');
  await page.waitForFunction(() => (window as any).__lc.useDoc.getState().doc.elements[0].fontSizeMm === 20);
  await page.waitForTimeout(100);
  const big = await bounds(page);
  expect(big.maxX - big.minX).toBeCloseTo((after.maxX - after.minX) * 2, 0);
  expect((await els(page))[0].text).toBe('LumaCut Studio');
});

test('zwei Formen vereinigen', async ({ page }) => {
  await open(page);
  await drawRect(page, { x: 60, y: 60 }, { x: 120, y: 120 });
  await drawRect(page, { x: 90, y: 90 }, { x: 150, y: 150 });
  await page.keyboard.press('Control+a');
  await page.getByTestId('bool-union').click();
  const all = await els(page);
  expect(all).toHaveLength(1);
  const b = await bounds(page);
  expect(b.minX).toBeCloseTo(60, 0); expect(b.maxX).toBeCloseTo(150, 0);
  expect(all[0].kind).toBe('Verschweißen');
  await page.keyboard.press('Control+z');
  expect(await els(page)).toHaveLength(2);
});

test('Ebene wechseln, Werte, Reihenfolge per Ziehen', async ({ page }) => {
  await open(page);
  await drawRect(page, { x: 60, y: 60 }, { x: 120, y: 120 });
  const layerOf = async () => page.evaluate(() => { const d = (window as any).__lc.useDoc.getState().doc; return d.layers.find((l: any) => l.id === d.elements[0].layerId).name; });
  expect(await layerOf()).toBe('Gravieren');
  await page.getByRole('radio', { name: 'Schneiden' }).first().click();
  expect(await layerOf()).toBe('Schneiden');
  await expect(page.getByTestId('layer-Schneiden')).toBeVisible();
  await expect(page.getByTestId('layer-Gravieren')).toHaveCount(0);

  const power = page.getByRole('textbox', { name: 'Leistung Schneiden' });
  await power.fill('5'); await power.press('Enter');
  await expect(page.getByTestId('layer-Schneiden')).toContainText('zündet');
  await power.fill('85'); await power.press('Enter');

  await page.getByTestId('layer-more-Schneiden').click();
  await expect(page.getByTestId('layer-Schneiden')).toContainText('Durchgänge');

  // A second layer in use, then swap by dragging its grip.
  await page.keyboard.press('Escape');
  await page.getByRole('radio', { name: 'Markieren' }).first().click();
  await drawRect(page, { x: 150, y: 150 }, { x: 180, y: 180 });
  const order = () => page.evaluate(() => { const d = (window as any).__lc.useDoc.getState().doc; return d.layers.map((l: any) => l.name); });
  const before = await order();
  expect(before.indexOf('Linie')).toBeLessThan(before.indexOf('Schneiden'));
  const grip = (await page.getByTestId('layer-grip-Linie').boundingBox())!;
  const row = (await page.getByTestId('layer-Schneiden').boundingBox())!;
  await page.mouse.move(grip.x + 6, grip.y + 8); await page.mouse.down();
  await page.mouse.move(grip.x + 6, row.y + row.height + 6, { steps: 6 }); await page.mouse.up();
  const after = await order();
  expect(after.indexOf('Linie')).toBeGreaterThan(after.indexOf('Schneiden'));
});

test('Platten: hinzufügen, wechseln, Auswahl verschieben', async ({ page }) => {
  await open(page);
  await drawRect(page, { x: 60, y: 60 }, { x: 120, y: 120 });
  await page.getByTestId('plate-add').click();
  await expect(page.getByTestId('plate-1')).toHaveAttribute('aria-selected', 'true');
  await expect(page.getByTestId('empty-state')).toContainText('Platte 2');
  await drawRect(page, { x: 30, y: 60 }, { x: 60, y: 90 });
  await page.getByTestId('plate-0').click();
  await expect(page.getByTestId('plate-0')).toHaveAttribute('aria-selected', 'true');
  await clickMm(page, { x: 90, y: 60 });
  await page.getByTestId('plate-move').click();
  await page.getByRole('menuitem', { name: 'Platte 2' }).click();
  const all = await els(page);
  expect(all.every((e: { plate: number }) => e.plate === 1)).toBe(true);
  await expect(page.getByTestId('plate-1')).toHaveAttribute('aria-selected', 'true');
});

test('Knoten verschieben, einfügen, löschen; Griffe einer Ellipse', async ({ page }) => {
  await open(page);
  await drawRect(page, { x: 60, y: 60 }, { x: 120, y: 120 });
  await page.keyboard.press('a');
  await expect(page.getByTestId('tool-node')).toHaveAttribute('aria-pressed', 'true');
  const past0 = await pastLen(page);
  await drag(page, { x: 120, y: 120 }, { x: 140, y: 150 });
  let b = await bounds(page);
  expect(b.maxX).toBeCloseTo(140, 0); expect(b.maxY).toBeCloseTo(150, 0);
  expect(await pastLen(page)).toBe(past0 + 1);
  // Double click on the left side adds a node; Delete takes it away again.
  const onEdge = await at(page, { x: 60, y: 90 });
  await page.mouse.dblclick(onEdge.x, onEdge.y);
  const nodes = () => page.evaluate(() => (window as any).__lc.useDoc.getState().doc.elements[0].curves[0].nodes.length);
  expect(await nodes()).toBe(5);
  await page.keyboard.press('Delete');
  expect(await nodes()).toBe(4);
  await page.keyboard.press('Control+z'); await page.keyboard.press('Control+z'); await page.keyboard.press('Control+z');
  b = await bounds(page);
  expect(b.maxX).toBeCloseTo(120, 0);

  await page.keyboard.press('v'); await page.keyboard.press('Escape');
  await page.keyboard.press('e');
  await drag(page, { x: 200, y: 200 }, { x: 260, y: 260 });
  await page.keyboard.press('a');
  await clickMm(page, { x: 230, y: 200 });
  const h0 = await page.evaluate(() => { const e = (window as any).__lc.useDoc.getState().doc.elements.at(-1); return e.curves[0].nodes[0]; });
  const e0 = await bounds(page);
  await drag(page, { x: e0.minX + h0.hx2, y: e0.minY + h0.hy2 }, { x: e0.minX + h0.hx2 + 20, y: e0.minY + h0.hy2 - 15 });
  const h1 = await page.evaluate(() => (window as any).__lc.useDoc.getState().doc.elements.at(-1).curves[0].nodes[0]);
  expect(h1.hx2).not.toBeCloseTo(h0.hx2, 1);
});

test('Stift: Ecke und runde Stelle, schließen', async ({ page }) => {
  await open(page);
  await page.keyboard.press('p');
  await clickMm(page, { x: 100, y: 100 });
  await drag(page, { x: 160, y: 100 }, { x: 180, y: 120 });
  await clickMm(page, { x: 130, y: 170 });
  await clickMm(page, { x: 100, y: 100 });
  const [e] = await els(page);
  expect(e.kind).toBe('Kurve');
  expect(e.curves[0].closed).toBe(true); expect(e.curves[0].nodes).toHaveLength(3);
  expect(e.pts).toBeGreaterThan(6);
});

test('Warnung am Objekt: Arbeitsfläche und Park-Ecke', async ({ page }) => {
  await open(page);
  const bedW = await page.evaluate(() => (window as any).__lc.useEditor.getState().canvasW);
  expect(bedW).toBeGreaterThan(0);
  await drawRect(page, { x: 320, y: 5 }, { x: 350, y: 25 });
  await expect(page.getByTestId('props-warning')).toContainText('Park-Ecke');
  await page.getByRole('button', { name: 'Aus der Park-Ecke schieben' }).click();
  await expect(page.getByTestId('props-warning')).toBeHidden();
  const x = page.getByRole('textbox', { name: 'Position X' });
  await x.fill('380'); await x.press('Enter');
  await expect(page.getByTestId('props-warning')).toContainText('Ragt über');
});

test('Zoom zum Mauszeiger, Verschieben, Einpassen', async ({ page }) => {
  await open(page);
  const p = await at(page, { x: 100, y: 100 });
  await page.mouse.move(p.x, p.y);
  await page.mouse.wheel(0, -400);
  await page.waitForTimeout(50);
  const q = await at(page, { x: 100, y: 100 });
  expect(Math.abs(q.x - p.x)).toBeLessThan(1); expect(Math.abs(q.y - p.y)).toBeLessThan(1);
  const z1 = await page.evaluate(() => (window as any).__lc.useEditor.getState().zoom);
  await page.keyboard.down('Space'); await page.mouse.down(); await page.mouse.move(p.x + 60, p.y + 30, { steps: 3 }); await page.mouse.up(); await page.keyboard.up('Space');
  const q2 = await at(page, { x: 100, y: 100 });
  expect(q2.x - q.x).toBeCloseTo(60, 0);
  await page.keyboard.press('f');
  const z2 = await page.evaluate(() => (window as any).__lc.useEditor.getState().zoom);
  expect(z2).toBeLessThan(z1);
});

test('tausende Pfade bleiben flüssig', async ({ page }) => {
  await open(page);
  await page.evaluate(() => {
    const { useDoc } = (window as any).__lc, s = useDoc.getState(), layer = s.doc.layers[1].id, el: any[] = [];
    for (let i = 0; i < 5000; i++) {
      const x = 5 + (i % 100) * 3.2, y = 40 + Math.floor(i / 100) * 6;
      el.push({ id: 'p' + i, layerId: layer, kind: 'Test', transform: { x, y, scaleX: 1, scaleY: 1, rotation: 0 }, paths: [Array.from({ length: 13 }, (_, k) => ({ x: 1.4 + Math.cos(k / 12 * 6.283) * 1.4, y: 1.4 + Math.sin(k / 12 * 6.283) * 1.4 }))], text: null, fontSizeMm: 10, bold: false, fontFamily: 'sans-serif', raster: null, imageWidthMm: 0, imageHeightMm: 0, imageMode: 'GRAYSCALE', adjust: {}, groupId: null, plate: 0 });
    }
    s.addElements(el);
  });
  await page.waitForTimeout(300);
  const ms = await page.evaluate(async () => {
    const lc = (window as any).__lc, st = lc.stage, times: number[] = [];
    for (let i = 0; i < 12; i++) { lc.useEditor.getState().zoomAt(500, 400, i % 2 ? 1.1 : 0.91); await new Promise(requestAnimationFrame); await new Promise(requestAnimationFrame); times.push(st.lastSceneMs); }
    return times.sort((a, b) => a - b)[6];
  });
  console.log(`5000 Pfade, Bild neu zeichnen: ${ms.toFixed(1)} ms`);
  expect(ms).toBeLessThan(40);
  await page.keyboard.press('Control+a');
  const t0 = Date.now();
  await drag(page, { x: 100, y: 200 }, { x: 110, y: 205 }, 10);
  console.log(`5000 Pfade ziehen, 10 Schritte: ${Date.now() - t0} ms`);
  expect(await pastLen(page)).toBe(2);
});

/* ---- Screenshots ---- */
async function richMotif(page: Page) {
  await page.evaluate(async () => {
    const { useDoc } = (window as any).__lc, s = useDoc.getState();
    const text = await import('/src/core/text.ts' as string), curves = await import('/src/core/curves.ts' as string), model = await import('/src/core/model.ts' as string);
    const L = (n: string) => useDoc.getState().layerByName(n).id;
    const add = (e: any) => useDoc.getState().commit((d: any) => ({ ...d, elements: [...d.elements, model.newElement(e.layerId, e.kind, { ...e, transform: { ...model.IDENTITY, ...e.transform } })] }));
    const cv = (c: any, kind: string, layer: string, x: number, y: number, rotation = 0) => add({ kind, layerId: L(layer), curves: [c], paths: curves.flattenCurves([c]), transform: { x, y, rotation } });
    cv(curves.rectCurve(240, 170), 'Rechteck', 'Schneiden', 30, 60);
    cv(curves.ellipseCurve(120, 120), 'Ellipse', 'Linie', 58, 85);
    cv(curves.ellipseCurve(104, 104), 'Ellipse', 'Linie', 66, 93);
    for (const [t, size, x, y, bold] of [['LumaCut', 15, 78, 128, true], ['WERKSTATT', 6, 92, 150, false]] as const) {
      const paths = await text.textPaths(t, size, bold, 'sans-serif');
      add({ kind: 'Text', layerId: L('Gravieren'), text: t, fontSizeMm: size, bold, paths, transform: { x, y } });
    }
    const star = Array.from({ length: 11 }, (_, k) => { const r = k % 2 ? 11 : 26, a = -Math.PI / 2 + k * Math.PI / 5; return { x: 26 + r * Math.cos(a), y: 26 + r * Math.sin(a) }; });
    add({ kind: 'Stern', layerId: L('Gravieren'), paths: [star], transform: { x: 195, y: 90, rotation: 12 } });
    for (let i = 0; i < 9; i++) cv(curves.ellipseCurve(9, 9), 'Loch', 'Schneiden', 192 + i * 7.2 % 60, 165 + Math.floor(i / 3) * 14 + (i % 3) * 2);
    // A soft photo-like gradient as a raster, 400 x 280 px.
    const w = 400, h = 280, gray = new Uint8Array(w * h);
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) { const dx = x - w / 2, dy = y - h / 2; gray[y * w + x] = Math.max(0, Math.min(255, 245 - 215 * Math.exp(-(dx * dx + dy * dy) / 9000) * (0.75 + 0.25 * Math.sin(x / 9) * Math.cos(y / 11)))); }
    let bin = ''; for (let i = 0; i < gray.length; i += 8192) bin += String.fromCharCode(...gray.subarray(i, i + 8192));
    add({ kind: 'Bild', layerId: L('Gravieren'), raster: { width: w, height: h, grayBase64: btoa(bin) }, imageWidthMm: 80, imageHeightMm: 56, imageMode: 'DITHER', transform: { x: 30, y: 250 } });
    useDoc.getState().commit((d: any) => ({ ...d, title: 'Schild Werkstatt' }));
    s.select([]);
  });
  await page.waitForTimeout(500);
}

const SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="40mm" height="30mm" viewBox="0 0 40 30"><rect x="1" y="1" width="20" height="20"/><circle cx="30" cy="20" r="8"/></svg>';

test('Import per Dialog und per Drag & Drop, ein Undo-Schritt', async ({ page }) => {
  await open(page);
  const past0 = await pastLen(page);
  const chooser = page.waitForEvent('filechooser');
  await page.getByRole('button', { name: 'Datei öffnen' }).click();
  await (await chooser).setFiles({ name: 'form.svg', mimeType: 'image/svg+xml', buffer: Buffer.from(SVG) });
  await page.waitForFunction(() => (window as any).__lc.useDoc.getState().doc.elements.length > 0);
  const n = (await els(page)).length;
  expect(await pastLen(page)).toBe(past0 + 1);
  const dt = await page.evaluateHandle((svg) => { const d = new DataTransfer(); d.items.add(new File([svg], 'zwei.svg', { type: 'image/svg+xml' })); return d; }, SVG);
  await page.getByTestId('canvas-host').dispatchEvent('dragover', { dataTransfer: dt });
  await page.getByTestId('canvas-host').dispatchEvent('drop', { dataTransfer: dt });
  await page.waitForFunction((k) => (window as any).__lc.useDoc.getState().doc.elements.length > k, n);
  expect(await pastLen(page)).toBe(past0 + 2);
});

test('Spiegeln, Kontur, Aufteilen, Rechtsklick-Menü', async ({ page }) => {
  await open(page);
  await page.keyboard.press('t');
  await clickMm(page, { x: 60, y: 120 });
  await page.waitForFunction(() => (window as any).__lc.useDoc.getState().doc.elements.length === 1);
  await page.getByTestId('text-input').fill('HI');
  await page.waitForFunction(() => (window as any).__lc.useDoc.getState().doc.elements[0].text === 'HI');
  await page.waitForTimeout(80);
  await page.getByTestId('text-input').blur();

  const box0 = await bounds(page);
  const p = await at(page, { x: box0.minX + 0.3, y: (box0.minY + box0.maxY) / 2 });
  await page.mouse.click(p.x, p.y, { button: 'right' });
  await page.getByRole('menuitem', { name: 'In Pfade umwandeln' }).click();
  expect((await els(page))[0].text).toBeNull();

  await page.getByTestId('split').click();
  expect(await els(page)).toHaveLength(2);
  await page.keyboard.press('Control+g');

  await page.getByTitle('Links und rechts spiegeln').click();
  const b1 = await bounds(page, 0);
  expect(b1.maxX).toBeCloseTo(box0.maxX, 0);

  await page.getByTestId('contour').click();
  await page.getByTestId('contour-ok').click();
  const all = await page.evaluate(() => { const d = (window as any).__lc.useDoc.getState().doc; return d.elements.map((e: any) => ({ kind: e.kind, layer: d.layers.find((l: any) => l.id === e.layerId).name, g: e.groupId })); });
  const c = all.at(-1);
  expect(c.kind).toBe('Kontur'); expect(c.layer).toBe('Schneiden');
  expect(all.every((e: { g: string }) => e.g === c.g)).toBe(true);
  const cb = await bounds(page);
  expect(cb.maxX).toBeGreaterThan(box0.maxX + 1);
});

test('Bild: Modus, Regler als ein Schritt, Vektorisieren, Hintergrund bleibt draußen', async ({ page }) => {
  await open(page);
  await richMotif(page);
  await clickMm(page, { x: 60, y: 275 });
  await expect(page.getByTestId('image-mode')).toHaveValue('DITHER');
  await page.getByTestId('image-mode').selectOption('THRESHOLD');
  await page.waitForTimeout(100);
  const mode = await page.evaluate(() => (window as any).__lc.useDoc.getState().doc.elements.at(-1).imageMode);
  expect(mode).toBe('THRESHOLD');
  const past = await pastLen(page);
  const range = page.locator('input[type=range]').first(), rb = (await range.boundingBox())!;
  await page.mouse.move(rb.x + rb.width / 2, rb.y + rb.height / 2); await page.mouse.down();
  await page.mouse.move(rb.x + rb.width * 0.7, rb.y + rb.height / 2, { steps: 6 }); await page.mouse.up();
  expect(await pastLen(page)).toBe(past + 1);
  await page.getByTestId('vectorize').click();
  await page.getByTestId('vectorize-ok').click();
  const last = await page.evaluate(() => { const e = (window as any).__lc.useDoc.getState().doc.elements.at(-1); return { kind: e.kind, n: e.paths.length, raster: e.raster }; });
  expect(last.kind).toBe('Vektor'); expect(last.n).toBeGreaterThan(0); expect(last.raster).toBeNull();

  // Background from the Pi: shown, but the project JSON does not change or grow.
  await page.route('**/api/workspace/scan', (r) => r.fulfill({ status: 200, contentType: 'image/png', body: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==', 'base64') }));
  const before = await page.evaluate(() => JSON.stringify((window as any).__lc.useDoc.getState().doc));
  await page.getByTestId('bg-button').click();
  await page.getByRole('button', { name: 'Scan vom Pi laden' }).click();
  await page.waitForFunction(() => (window as any).__lc.useEditor.getState().bgOn);
  const after = await page.evaluate(() => JSON.stringify((window as any).__lc.useDoc.getState().doc));
  expect(after).toBe(before);
});

test('Gedrehte Form behält beim Skalieren ihre Achsen', async ({ page }) => {
  await open(page);
  await drawRect(page, { x: 100, y: 100 }, { x: 160, y: 140 });
  const rot = page.getByRole('textbox', { name: 'Drehung' });
  await rot.fill('90'); await rot.press('Enter');
  const b = await bounds(page), [before] = await els(page);
  await drag(page, { x: (b.minX + b.maxX) / 2, y: b.maxY }, { x: (b.minX + b.maxX) / 2, y: b.maxY + 30 });
  const [after] = await els(page), a = await bounds(page);
  expect(after.t.rotation).toBeCloseTo(90, 3);
  expect(after.t.scaleX).toBeGreaterThan(before.t.scaleX * 1.3);
  expect(after.t.scaleY).toBeCloseTo(before.t.scaleY, 3);
  expect(a.minY).toBeCloseTo(b.minY, 0);
  expect(a.maxX - a.minX).toBeCloseTo(b.maxX - b.minX, 0);
});

test('Kontur um ein Bild folgt den dunklen Stellen', async ({ page }) => {
  await open(page);
  await richMotif(page);
  await clickMm(page, { x: 70, y: 278 });
  await page.getByTestId('contour').click();
  await page.getByTestId('contour-ok').click();
  await page.waitForTimeout(100);
  const last = await page.evaluate(() => { const e = (window as any).__lc.useDoc.getState().doc.elements.at(-1); return { kind: e.kind, n: e.paths.length }; });
  expect(last.kind).toBe('Kontur'); expect(last.n).toBeGreaterThan(0);
  const b = await bounds(page);
  expect(b.maxX - b.minX).toBeLessThan(80);
});

test('Export legt eine SVG-Datei ab', async ({ page }) => {
  await open(page);
  await drawRect(page, { x: 60, y: 60 }, { x: 120, y: 120 });
  await page.keyboard.press('Control+e');
  const dl = page.waitForEvent('download');
  await page.getByTestId('export-ok').click();
  expect((await dl).suggestedFilename()).toMatch(/\.svg$/);
});

test('Alt+Ziehen kopiert, Esc bricht das Ziehen ab', async ({ page }) => {
  await open(page);
  await drawRect(page, { x: 60, y: 60 }, { x: 120, y: 120 });
  const a = await at(page, { x: 70, y: 60 }), b = await at(page, { x: 200, y: 200 });
  await page.keyboard.down('Alt');
  await page.mouse.move(a.x, a.y); await page.mouse.down(); await page.mouse.move(b.x, b.y, { steps: 5 }); await page.mouse.up();
  await page.keyboard.up('Alt');
  expect(await els(page)).toHaveLength(2);
  const past = await pastLen(page), x0 = (await els(page))[1].t.x;
  const c = await at(page, { x: 200, y: 200 }), d = await at(page, { x: 260, y: 260 });
  await page.mouse.move(c.x, c.y); await page.mouse.down(); await page.mouse.move(d.x, d.y, { steps: 5 });
  await page.keyboard.press('Escape');
  await page.mouse.up();
  expect((await els(page))[1].t.x).toBeCloseTo(x0, 3);
  expect(await pastLen(page)).toBe(past);
});

for (const theme of ['light', 'dark'] as const) {
  test(`Bilder ${theme}`, async ({ page }) => {
    await open(page, theme);
    await page.waitForTimeout(300);
    await page.screenshot({ path: shot(`leer-${theme}`) });
    await richMotif(page);
    await page.screenshot({ path: shot(`reich-${theme}`) });
    await clickMm(page, { x: 90, y: 60 });
    await page.mouse.move(800, 860);
    await page.waitForTimeout(100);
    await page.getByTestId('layer-more-Schneiden').click();
    await page.screenshot({ path: shot(`auswahl-${theme}`) });
    await page.getByTestId('layer-more-Schneiden').click();
    await clickMm(page, { x: 60, y: 275 });
    await page.mouse.move(800, 860);
    await page.waitForTimeout(150);
    await page.screenshot({ path: shot(`bild-${theme}`) });
    await page.keyboard.press('Escape');
    await page.keyboard.press('a');
    await clickMm(page, { x: 118, y: 85 });
    await clickMm(page, { x: 118, y: 85 });
    await page.mouse.move(800, 860);
    await page.waitForTimeout(100);
    await page.screenshot({ path: shot(`knoten-${theme}`) });
    // Warnings on the object, context menu, background popover.
    await page.keyboard.press('v');
    await page.route('**/api/workspace/scan', (r) => r.fulfill({ status: 200, contentType: 'image/png', body: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==', 'base64') }));
    await page.getByTestId('bg-button').click();
    await page.getByRole('button', { name: 'Scan vom Pi laden' }).click();
    await page.waitForFunction(() => (window as any).__lc.useEditor.getState().bgOn);
    await page.waitForTimeout(100);
    await page.screenshot({ path: shot(`hintergrund-${theme}`) });
    await page.keyboard.press('Escape');
    await page.mouse.click(700, 830);
    await page.evaluate(() => { const lc = (window as any).__lc; lc.useEditor.getState().set({ bgOn: false }); });
    await page.keyboard.press('Escape');
    await drawRect(page, { x: 310, y: 10 }, { x: 345, y: 30 });
    await drawRect(page, { x: 340, y: 200 }, { x: 389, y: 240 });
    const x = page.getByRole('textbox', { name: 'Position X' });
    await x.fill('360'); await x.press('Enter');
    const keep = page.getByRole('button', { name: 'Diese Fassung behalten' });
    if (await keep.isVisible()) await keep.click();
    const star = await at(page, { x: 225, y: 118 });
    await page.mouse.click(star.x, star.y, { button: 'right' });
    await page.waitForTimeout(100);
    await page.screenshot({ path: shot(`warnung-${theme}`) });
  });
}
for (const [w, h] of [[1280, 720], [2560, 1440], [1000, 640]] as const) {
  test(`Bilder ${w}x${h}`, async ({ page }) => {
    await page.setViewportSize({ width: w, height: h });
    await open(page);
    await page.waitForTimeout(250);
    await page.screenshot({ path: shot(`leer-${w}`) });
    await richMotif(page);
    await clickMm(page, { x: 90, y: 60 });
    await page.waitForTimeout(150);
    await page.screenshot({ path: shot(`reich-${w}`) });
  });
}
