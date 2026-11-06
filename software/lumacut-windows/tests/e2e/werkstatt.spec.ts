import { expect, type Page, test } from '@playwright/test';

const SHOTS = 'tests/e2e/screenshots';
const open = async (page: Page, theme: 'light' | 'dark' = 'light') => {
  await page.addInitScript((t) => { localStorage.setItem('lc.theme', JSON.stringify(t)); localStorage.setItem('lc.dest', JSON.stringify('werkstatt')); }, theme);
  await page.goto('/');
  await expect(page.getByTestId('werkstatt')).toBeVisible();
};
const tool = async (page: Page, id: string) => { await page.getByTestId(`tool-${id}`).click(); await expect(page.getByTestId('ws-wizard')).toBeVisible(); };
const size = async (page: Page) => { const s = page.getByTestId('ws-preview'); return { w: Number(await s.getAttribute('data-w')), h: Number(await s.getAttribute('data-h')) }; };
const setNum = async (page: Page, label: string, v: string) => { const i = page.getByRole('textbox', { name: label, exact: true }); await i.fill(v); await i.press('Enter'); };
/** The running app's store, same module instance through the dev server. */
const docState = (page: Page) => page.evaluate(async () => {
  const { useDoc } = await import('/src/store/doc.ts' as string);
  const s = useDoc.getState();
  return { plateCount: s.doc.plateCount, activePlate: s.doc.activePlate, kinds: s.doc.elements.map((e: { kind: string }) => e.kind), plates: s.doc.elements.map((e: { plate: number }) => e.plate), layers: s.doc.layers.map((l: { name: string }) => l.name), past: s.past.length };
});

test.describe('Werkstatt', () => {
  test('Galerie zeigt Gruppen, Drehachse als Hinweis, hell und dunkel', async ({ page }) => {
    await open(page);
    for (const g of ['Testen', 'Fotos und Stempel', 'Teile', 'Beschriften', 'Anordnen', 'Vorlagen']) await expect(page.getByRole('heading', { name: g })).toBeVisible();
    await expect(page.getByText('keine Drehachse')).toBeVisible();
    await expect(page.locator('.ws-thumb svg').first()).toBeVisible();
    await page.waitForTimeout(300);
    await page.screenshot({ path: `${SHOTS}/werkstatt-galerie-light.png` });
    await page.setViewportSize({ width: 1280, height: 720 });
    await page.screenshot({ path: `${SHOTS}/werkstatt-galerie-1280.png` });
    await page.setViewportSize({ width: 2560, height: 1440 });
    await page.screenshot({ path: `${SHOTS}/werkstatt-galerie-2560.png` });
  });

  test('Box: Werte ändern, Vorschau folgt, Übernehmen landet im Motiv', async ({ page }) => {
    await open(page);
    await tool(page, 'box');
    await expect(page.locator('[data-testid="ws-preview"] path').first()).toBeAttached();
    const before = await size(page);
    await setNum(page, 'Breite', '180');
    await setNum(page, 'Höhe', '70');
    await expect.poll(async () => (await size(page)).w).toBeGreaterThan(before.w);
    await page.getByRole('radio', { name: 'Verzahnt' }).click();
    await expect(page.getByTestId('ws-summary')).toContainText('6 Elemente');
    await page.screenshot({ path: `${SHOTS}/werkstatt-box-light.png` });
    await page.getByRole('radio', { name: 'Auf der Platte' }).click();
    await page.screenshot({ path: `${SHOTS}/werkstatt-box-platte.png` });
    await page.setViewportSize({ width: 1280, height: 720 });
    await page.waitForTimeout(200);
    await page.screenshot({ path: `${SHOTS}/werkstatt-box-1280.png` });
    await page.getByTestId('ws-apply').click();
    await expect(page.getByTestId('nav-motiv')).toHaveAttribute('aria-current', 'page');
    const d = await docState(page);
    expect(d.kinds.sort()).toEqual(['Boden', 'Deckel', 'Hinten', 'Links', 'Rechts', 'Vorne']);
    const undo = await page.evaluate(async () => { const { useDoc } = await import('/src/store/doc.ts' as string); useDoc.getState().undo(); return useDoc.getState().doc.elements.length; });
    expect(undo).toBe(0);
  });

  test('Fehler sind ein Satz und sperren Übernehmen', async ({ page }) => {
    await open(page);
    await tool(page, 'serien');
    await expect(page.getByTestId('ws-apply')).toBeEnabled();
    await page.getByRole('textbox', { name: 'Vorlage' }).fill('ohne Platzhalter');
    await expect(page.getByTestId('ws-error')).toContainText('Platzhalter');
    await expect(page.getByTestId('ws-apply')).toBeDisabled();
  });

  test('Seriennummern: mehrere Platten, Plattenwahl, landen auf neuen Platten', async ({ page }) => {
    await open(page, 'dark');
    await tool(page, 'serien');
    await setNum(page, 'Stück', '120');
    await setNum(page, 'Schildbreite', '80');
    await setNum(page, 'Schildhöhe', '30');
    await expect(page.getByTestId('ws-plates')).toBeVisible();
    const plates = Number(await page.getByTestId('ws-preview').getAttribute('data-plates'));
    expect(plates).toBeGreaterThan(1);
    await page.getByTestId('ws-plates').getByText('Platte 2').click();
    await page.getByRole('radio', { name: 'Auf der Platte' }).click();
    await page.screenshot({ path: `${SHOTS}/werkstatt-serien-dark.png` });
    await page.getByTestId('ws-apply').click();
    const d = await docState(page);
    expect(d.plateCount).toBe(plates);
    expect(new Set(d.plates).size).toBe(plates);
  });

  test('QR: Warnung bei kleinen Punkten, Größe stimmt', async ({ page }) => {
    await open(page);
    await tool(page, 'qr');
    await page.getByRole('textbox', { name: 'Text oder Adresse' }).fill('https://example.org/lumacut');
    await expect.poll(async () => (await size(page)).w).toBeGreaterThan(20);
    const a = await size(page);
    await setNum(page, 'Kantenlänge eines Punktes', '0.5');
    await expect.poll(async () => (await size(page)).w).toBeCloseTo(a.w / 2, 0);
    await expect(page.getByText('lassen sich oft nicht mehr lesen')).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/werkstatt-qr-light.png` });
    await page.getByTestId('ws-apply').click();
    expect((await docState(page)).kinds).toEqual(['QR-Code']);
  });

  for (const [id, name] of [['stempel', 'stempel'], ['zahnrad', 'zahnrad'], ['lineal', 'lineal'], ['massstab', 'massstab'], ['vorlage-untersetzer', 'untersetzer'], ['vorlage-etikett', 'etikett'], ['vorlage-anhaenger', 'anhaenger'], ['vorlage-schild', 'schild']]) {
    test(`Assistent ${name} zeigt Geometrie`, async ({ page }) => {
      await open(page, name === 'stempel' ? 'dark' : 'light');
      await tool(page, id);
      await expect.poll(async () => (await size(page)).w).toBeGreaterThan(5);
      await page.waitForTimeout(150);
      await page.screenshot({ path: `${SHOTS}/werkstatt-${name}.png` });
      await page.getByTestId('ws-apply').click();
      expect((await docState(page)).kinds.length).toBeGreaterThan(0);
    });
  }

  test('Materialtest: Raster bringt eigene Ebenen mit, unter 8 % gesperrt', async ({ page }) => {
    await open(page);
    await tool(page, 'materialtest');
    await expect(page.getByTestId('ws-summary')).toContainText('26 Elemente');
    await page.screenshot({ path: `${SHOTS}/werkstatt-matgrid-light.png` });
    await setNum(page, 'Leistung Stufen', '3');
    await setNum(page, 'Leistung von', '5');
    await expect(page.getByRole('textbox', { name: 'Leistung von' })).toHaveValue('8');
    await setNum(page, 'Leistung von', '20');
    await setNum(page, 'Tempo Stufen', '5');
    await expect(page.getByTestId('ws-summary')).toContainText('16 Elemente');
    await page.getByTestId('ws-apply').click();
    const d = await docState(page);
    expect(d.layers).toContain('Beschriftung');
    expect(d.layers).toContain('20 % · 300 mm/min');
    expect(d.kinds.filter((k: string) => k === 'Testfeld').length).toBe(15);
  });

  test('Materialtest mit Kamera: Go-Dialog, Abbrechen sendet nichts, klarer Hinweis', async ({ page }) => {
    await open(page);
    const posts: string[] = [];
    page.on('request', (r) => { if (r.method() === 'POST' && r.url().includes('/api/action')) posts.push(r.postData() ?? ''); });
    await tool(page, 'materialtest');
    await page.getByRole('radio', { name: 'Automatisch mit Kamera' }).click();
    await expect(page.getByTestId('matcal')).toBeVisible();
    await page.waitForTimeout(1500);
    await page.screenshot({ path: `${SHOTS}/werkstatt-matcal-light.png` });
    const homed = await page.evaluate(async () => (await (await fetch('/api/status')).json()).homed);
    if (!homed) {
      await expect(page.getByTestId('matcal-start')).toBeDisabled();
      await expect(page.getByText(/referenziert/).first()).toBeVisible();
    }
    // Only the simulator sits behind the proxy (LUMACUT_DEV_PI): make it ready as a homed machine.
    const home = await page.evaluate(async () => (await fetch('/api/action', { method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, body: 'op=home&clear=1' })).status);
    expect(home).toBeLessThan(500);
    await page.getByRole('textbox', { name: 'Materialname' }).fill('Sperrholz 4 mm');
    const startBtn = page.getByTestId('matcal-start');
    await expect(startBtn).toBeEnabled({ timeout: 20000 });
    await startBtn.click();
    await expect(page.getByTestId('go-confirm')).toBeVisible();
    await expect(page.getByText('auf „Sperrholz 4 mm“', { exact: false })).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/werkstatt-matcal-go.png` });
    await page.getByRole('dialog').getByRole('button', { name: 'Abbrechen' }).click();
    await page.waitForTimeout(200);
    expect(posts.filter((p) => p.includes('matcal'))).toEqual([]);
    await startBtn.click();
    await page.getByTestId('go-confirm').click();
    await expect.poll(() => posts.filter((p) => p.includes('matcal')).length).toBe(1);
    expect(posts.find((p) => p.includes('matcal'))).toContain('kind=engrave');
    await page.waitForTimeout(800);
    await page.screenshot({ path: `${SHOTS}/werkstatt-matcal-after.png` });
  });

  test('Foto: Testbild, Material setzt Zeilenabstand, echtes Bild wählen', async ({ page }) => {
    await open(page);
    await tool(page, 'foto');
    await expect(page.locator('[data-testid="ws-preview"] image')).toBeAttached();
    await page.getByRole('combobox', { name: 'Material' }).selectOption('eloxal');
    await expect(page.getByRole('textbox', { name: 'Zeilenabstand' })).toHaveValue(/^0[.,]08$/);
    await page.screenshot({ path: `${SHOTS}/werkstatt-foto-light.png` });
    const png = await page.evaluate(async () => {
      const c = new OffscreenCanvas(60, 30); const x = c.getContext('2d')!;
      const g = x.createLinearGradient(0, 0, 60, 0); g.addColorStop(0, '#000'); g.addColorStop(1, '#fff'); x.fillStyle = g; x.fillRect(0, 0, 60, 30);
      const b = new Uint8Array(await (await c.convertToBlob()).arrayBuffer()); return [...b];
    });
    const [chooser] = await Promise.all([page.waitForEvent('filechooser'), page.getByTestId('ws-photo-pick').click()]);
    await chooser.setFiles({ name: 'verlauf.png', mimeType: 'image/png', buffer: Buffer.from(png) });
    await expect(page.getByText('verlauf.png')).toBeVisible();
    await expect.poll(async () => (await size(page)).h).toBeCloseTo(50, 0);
    await page.getByTestId('ws-apply').click();
    const d = await docState(page);
    expect(d.kinds).toEqual(['Foto']);
    expect(d.layers.some((l: string) => l.startsWith('Foto 0,08'))).toBe(true);
  });

  test('Schachteln: ohne Motiv ein Satz, mit Teilen wird angeordnet', async ({ page }) => {
    await open(page);
    await tool(page, 'schachteln');
    await expect(page.getByTestId('ws-error')).toContainText('noch nichts');
    await page.screenshot({ path: `${SHOTS}/werkstatt-schachteln-leer.png` });
    await page.getByTestId('ws-back').click();
    await page.evaluate(async () => {
      const { useDoc } = await import('/src/store/doc.ts' as string);
      const { newElement } = await import('/src/core/model.ts' as string);
      const s = useDoc.getState(); const l = s.layerByName('Schneiden').id;
      const els = Array.from({ length: 9 }, (_, i) => newElement(l, 'Teil', { transform: { x: 100, y: 100, scaleX: 1, scaleY: 1, rotation: 0 }, paths: [[{ x: 0, y: 0 }, { x: 40 + i * 12, y: 0 }, { x: 40 + i * 12, y: 30 + i * 8 }, { x: 0, y: 30 + i * 8 }, { x: 0, y: 0 }]] }));
      s.addElements(els);
    });
    await tool(page, 'schachteln');
    await expect(page.getByTestId('ws-summary')).toContainText('9 Elemente');
    await page.getByRole('radio', { name: 'Auf der Platte' }).click();
    await page.screenshot({ path: `${SHOTS}/werkstatt-schachteln-light.png` });
    await page.getByTestId('ws-apply').click();
    const xs = await page.evaluate(async () => { const { useDoc } = await import('/src/store/doc.ts' as string); return useDoc.getState().doc.elements.map((e: { transform: { x: number } }) => e.transform.x); });
    expect(new Set(xs.map((x: number) => Math.round(x))).size).toBeGreaterThan(2);
  });

  test('Rahmen um das Motiv bleibt an Ort und Stelle', async ({ page }) => {
    await open(page);
    await page.evaluate(async () => {
      const { useDoc } = await import('/src/store/doc.ts' as string);
      const { newElement } = await import('/src/core/model.ts' as string);
      const s = useDoc.getState();
      s.addElements([newElement(s.layerByName('Gravieren').id, 'Teil', { transform: { x: 50, y: 60, scaleX: 1, scaleY: 1, rotation: 0 }, paths: [[{ x: 0, y: 0 }, { x: 20, y: 0 }, { x: 20, y: 10 }, { x: 0, y: 10 }, { x: 0, y: 0 }]] })]);
      s.select([]);
    });
    await tool(page, 'rahmen');
    await expect.poll(async () => (await size(page)).w).toBeCloseTo(30, 0);
    await page.getByTestId('ws-apply').click();
    const t = await page.evaluate(async () => { const { useDoc } = await import('/src/store/doc.ts' as string); const e = useDoc.getState().doc.elements.find((x: { kind: string }) => x.kind === 'Rahmen'); return e.transform; });
    expect(t.x).toBeCloseTo(45, 3); expect(t.y).toBeCloseTo(55, 3);
  });
});

test.describe('Import im Browser', () => {
  const run = (page: Page, make: string) => page.evaluate(async (code) => {
    const imp = await import('/src/core/import/index.ts' as string);
    const { defaultLayers } = await import('/src/core/model.ts' as string);
    const layers = defaultLayers();
    const ctx = { layerByName: (n: string) => layers.find((l: { name: string }) => l.name === n), activeLayer: layers[0] };
    // eslint-disable-next-line no-new-func
    const bytes: Uint8Array = await new Function(`return (async () => { ${code} })()`)();
    const r = await imp.importFile('x', bytes, ctx);
    return { n: r.elements.length, warnings: r.warnings, kinds: r.elements.map((e: { kind: string }) => e.kind), raster: r.elements[0]?.raster ? [r.elements[0].raster.width, r.elements[0].raster.height] : null, size: [r.elements[0]?.imageWidthMm, r.elements[0]?.imageHeightMm], x: r.elements[0]?.transform.x };
  }, make);
  const canvas = (type: string) => `const c = new OffscreenCanvas(200, 100); const x = c.getContext('2d'); x.fillStyle = '#888'; x.fillRect(0,0,200,100); return new Uint8Array(await (await c.convertToBlob({ type: '${type}', quality: .9 })).arrayBuffer());`;

  for (const [label, type] of [['PNG', 'image/png'], ['JPG', 'image/jpeg'], ['WebP', 'image/webp']]) {
    test(`Bild ${label} wird Graustufen-Raster, mittig`, async ({ page }) => {
      await page.goto('/');
      const r = await run(page, canvas(type));
      expect(r.kinds).toEqual(['Bild']);
      expect(r.raster).toEqual([200, 100]);
      expect(r.size[0]).toBeCloseTo(80, 3); expect(r.size[1]).toBeCloseTo(40, 3);
    });
  }
  test('Bild BMP', async ({ page }) => {
    await page.goto('/');
    const r = await run(page, `const w = 2, h = 2; const b = new Uint8Array(54 + 16); const d = new DataView(b.buffer); b[0]=0x42; b[1]=0x4D; d.setUint32(2, 70, true); d.setUint32(10, 54, true); d.setUint32(14, 40, true); d.setInt32(18, w, true); d.setInt32(22, h, true); d.setUint16(26, 1, true); d.setUint16(28, 24, true); d.setUint32(34, 16, true); b.fill(128, 54); return b;`);
    expect(r.raster).toEqual([2, 2]);
  });
  test('PDF ohne Pfade wird Bild mit Warnung, mit Pfaden Vektor', async ({ page }) => {
    await page.goto('/');
    const pdf = (content: string) => `const content = ${JSON.stringify(content)}; const objs = ['<</Type/Catalog/Pages 2 0 R>>','<</Type/Pages/Kids[3 0 R]/Count 1>>','<</Type/Page/Parent 2 0 R/MediaBox[0 0 283.46 283.46]/Contents 4 0 R/Resources<<>>>>','<</Length '+content.length+'>>\\nstream\\n'+content+'\\nendstream']; let s='%PDF-1.5\\n'; const off=[]; objs.forEach((o,i)=>{off.push(s.length); s+=(i+1)+' 0 obj\\n'+o+'\\nendobj\\n';}); const xr=s.length; s+='xref\\n0 '+(objs.length+1)+'\\n0000000000 65535 f \\n'+off.map(o=>String(o).padStart(10,'0')+' 00000 n \\n').join(''); s+='trailer\\n<</Size '+(objs.length+1)+'/Root 1 0 R>>\\nstartxref\\n'+xr+'\\n%%EOF\\n'; return new TextEncoder().encode(s);`;
    const vec = await run(page, pdf('0 0 m 72 0 l 72 72 l h S'));
    expect(vec.kinds).toEqual(['PDF']);
    expect(vec.raster).toBeNull();
    const img = await run(page, pdf('q Q'));
    expect(img.kinds).toEqual(['Bild']);
    expect(img.warnings.join(' ')).toMatch(/als Bild übernommen/);
  });
  test('Export PNG liefert ein Bild', async ({ page }) => {
    await page.goto('/');
    const head = await page.evaluate(async () => {
      const { exportPng } = await import('/src/core/export.ts' as string);
      const { newDoc, newElement } = await import('/src/core/model.ts' as string);
      const d = newDoc(); d.elements.push(newElement(d.layers[0].id, 'x', { paths: [[{ x: 10, y: 10 }, { x: 50, y: 10 }, { x: 50, y: 50 }, { x: 10, y: 10 }]] }));
      const b = await exportPng(d, 0, 4); return [...b.subarray(0, 4)];
    });
    expect(head).toEqual([0x89, 0x50, 0x4E, 0x47]);
  });
});
