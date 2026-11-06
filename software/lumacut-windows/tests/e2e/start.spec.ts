import { test, expect, type Page } from '@playwright/test';

/**
 * Bereich Starten gegen den Simulator mit --slow:
 * LC_PORT=5185 LUMACUT_DEV_PI=http://127.0.0.1:8092 npx playwright test tests/e2e/start.spec.ts
 * Motive kommen über dieselben Module ins Dokument wie in der App; es gibt keinen eigenen Test-Hook.
 */
const shot = (name: string) => `tests/e2e/screenshots/start-${name}.png`;

async function open(page: Page, theme: 'light' | 'dark' = 'light', viewport = { width: 1440, height: 900 }, extra: Record<string, string> = {}) {
  await page.setViewportSize(viewport);
  await page.addInitScript(([t, e]) => {
    localStorage.setItem('lc.theme', JSON.stringify(t));
    localStorage.setItem('lc.dest', JSON.stringify('start'));
    for (const [k, v] of Object.entries(e as Record<string, string>)) localStorage.setItem(k, v);
  }, [theme, extra] as const);
  await page.goto('/');
  await expect(page.getByTestId('start-view')).toBeVisible();
  await expect(page.getByTestId('conn-chip')).not.toHaveText('Pi nicht erreichbar');
}

interface Motif { power?: number; speed?: number; size?: number; x?: number; y?: number; plates?: number; rotatedImage?: boolean; fill?: boolean; title?: string }
/** Ein Rechteck (und je Platte eins mehr) auf der Linien- oder Gravierebene. */
async function setMotif(page: Page, m: Motif = {}) {
  await page.evaluate(async (m) => {
    const model = await import('/src/core/model.ts');
    const { useDoc } = await import('/src/store/doc.ts');
    const d = model.newDoc(m.title ?? 'Teststern');
    const layer = d.layers.find((l) => l.name === (m.fill ? 'Gravieren' : 'Linie'))!;
    if (m.power != null) layer.powerPct = m.power;
    if (m.speed != null) layer.speed = m.speed;
    const s = m.size ?? 60;
    const square = [{ x: 0, y: 0 }, { x: s, y: 0 }, { x: s, y: s }, { x: 0, y: s }, { x: 0, y: 0 }];
    const star = Array.from({ length: 11 }, (_, i) => { const r = (i % 2 ? .2 : .5) * s, a = i / 10 * Math.PI * 2 - Math.PI / 2; return { x: s / 2 + r * Math.cos(a), y: s / 2 + r * Math.sin(a) }; });
    const plates = m.plates ?? 1;
    for (let p = 0; p < plates; p++) {
      d.elements.push(model.newElement(layer.id, 'Rechteck', { paths: [square], plate: p, transform: { x: m.x ?? 60, y: (m.y ?? 60) + p * 20, scaleX: 1, scaleY: 1, rotation: 0 } }));
      d.elements.push(model.newElement(layer.id, 'Stern', { paths: [star], plate: p, transform: { x: m.x ?? 60, y: (m.y ?? 60) + p * 20, scaleX: 1, scaleY: 1, rotation: 0 } }));
    }
    if (m.rotatedImage) d.elements.push(model.newElement(layer.id, 'Bild', { raster: { width: 2, height: 2, grayBase64: 'AAAAAA==' }, imageWidthMm: 20, imageHeightMm: 20, transform: { x: 150, y: 150, scaleX: 1, scaleY: 1, rotation: 30 } }));
    d.plateCount = plates;
    useDoc.getState().load(d);
  }, m);
}
const setMaterial = (page: Page, material: { name: string; thickness_mm: number } | null) => page.request.put('/api/workspace', { data: { material, updated_by: 'Test' } });
const status = (page: Page) => page.request.get('/api/status').then((r) => r.json());
async function untilIdle(page: Page) {
  await expect.poll(async () => { const s = await status(page); return ['idle', 'complete', 'aborted', 'error'].includes(s.job.state) && !['running', 'starting'].includes(s.frame.state); }, { timeout: 60_000 }).toBe(true);
}
const ready = (page: Page) => expect(page.getByTestId('estimate')).not.toHaveText(/^[–…]$/, { timeout: 20_000 });
const check = (page: Page, id: string) => page.locator(`[data-check="${id}"]`);
async function clearJobs(page: Page) {
  await page.request.post('/api/action', { form: { op: 'queue_clear' } });
  const { files } = await page.request.get('/api/jobs').then((r) => r.json());
  for (const f of files) await page.request.post(`/api/jobs/${encodeURIComponent(f.name)}/delete`);
}

test.describe.configure({ mode: 'serial' });

test('leerer Zustand sagt, was zu tun ist', async ({ page }) => {
  await open(page);
  await setMaterial(page, null);
  await expect(page.getByTestId('preview-empty')).toContainText('Noch kein Motiv');
  await expect(page.getByTestId('start')).toBeDisabled();
  await expect(page.getByTestId('frame')).toBeDisabled();
  await page.waitForTimeout(300);
  await page.screenshot({ path: shot('leer-light') });
});

test('Prüfungen nennen jeden Grund in einem Satz', async ({ page }) => {
  await open(page);
  await setMaterial(page, null);
  await setMotif(page, { rotatedImage: true, power: 5 });
  await expect(check(page, 'material')).toContainText('Kein Material gewählt');
  await expect(check(page, 'rotated')).toContainText('gedreht');
  await expect(check(page, 'moved')).toContainText('neu scannen');
  await expect(page.getByTestId('start')).toBeDisabled();
  await page.waitForTimeout(400);
  await page.screenshot({ path: shot('pruefungen-light') });

  await setMotif(page, { x: 340, y: 340, size: 60 });
  await expect(check(page, 'outside')).toContainText('Arbeitsfläche');

  await setMotif(page, { x: 330, y: 2, size: 20 });
  await expect(check(page, 'park')).toContainText('Park-Ecke');
  await expect(page.getByTestId('start')).toBeDisabled();

  await setMotif(page, { speed: 29000 });
  await expect(page.locator('[data-check^="fast-"]')).toContainText('zu schnell');

  await setMotif(page, { power: 5 });
  await setMaterial(page, { name: 'Testpappel', thickness_mm: 8 });
  await expect(page.locator('[data-check^="weak-"]')).toContainText('unter 8 %');
  await expect(check(page, 'untested')).toContainText('Materialtest');
  await expect(check(page, 'material')).toHaveCount(0);
  await ready(page);
  await expect(page.getByTestId('start')).toBeEnabled();
});

test('Vorschau: Zoom, Verschieben, Schritte, Abspielen', async ({ page }) => {
  await open(page);
  await setMaterial(page, { name: 'Testpappel', thickness_mm: 8 });
  await setMotif(page, { plates: 3 });
  await ready(page);
  await expect(page.getByTestId('layer-table')).toContainText('Markieren');
  await expect(page.getByRole('radiogroup', { name: 'Platte wählen' })).toBeVisible();
  await page.getByRole('radio', { name: '2', exact: true }).click();
  await page.waitForTimeout(800); // neue Platte: Auftrag wird neu berechnet

  const canvas = page.getByTestId('preview-canvas');
  const box = (await canvas.boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.wheel(0, -600);
  await expect(page.getByTestId('zoom-value')).not.toHaveText('100 %');
  await page.mouse.down(); await page.mouse.move(box.x + box.width / 2 - 80, box.y + box.height / 2 - 40, { steps: 4 }); await page.mouse.up();
  await canvas.dblclick();
  await expect(page.getByTestId('zoom-value')).toHaveText('100 %');

  const slider = page.getByTestId('preview-slider');
  const max = +(await slider.getAttribute('max'))!;
  await expect(slider).toHaveValue(String(max));
  await page.getByRole('button', { name: 'Zum Anfang' }).click();
  await expect(slider).toHaveValue('0');
  await page.getByTestId('step-forward').click();
  const one = +(await slider.inputValue());
  await page.getByTestId('step-forward').click();
  expect(+(await slider.inputValue())).toBeGreaterThan(one);
  await page.getByTestId('step-back').click();
  await expect(slider).toHaveValue(String(one));
  await page.getByTestId('play').click();
  await expect.poll(async () => +(await slider.inputValue())).toBeGreaterThan(one);
  await page.getByTestId('play').click();
  await page.screenshot({ path: shot('abspielen-light') });
});

test('Zeichnen bleibt mit einer halben Million Segmente flüssig', async ({ page }) => {
  await open(page);
  const result = await page.evaluate(async () => {
    const { PathRaster } = await import('/src/features/start/raster.ts');
    const n = 500_000;
    const xy = new Float32Array(n * 4), power = new Uint8Array(n), line = new Uint32Array(n);
    // Gravur: 2500 Zeilen je 200 Segmente auf 250 × 250 mm, jede zweite Fahrt hin und her.
    for (let i = 0; i < n; i++) {
      const row = Math.floor(i / 200), col = i % 200, y = 50 + row * 0.1, dir = row % 2 ? -1 : 1;
      const x0 = dir > 0 ? 60 + col * 1.25 : 310 - col * 1.25;
      xy.set([x0, y, x0 + dir * 1.25, y], i * 4);
      power[i] = (col * row) % 255;
      line[i] = i;
    }
    const tp = { count: n, xy, power, line, bounds: null, stats: { cutMm: 0, travelMm: 0, seconds: 0, maxPower: 255, warnings: [] }, lineCount: n };
    const r = new PathRaster();
    const ink = { cut: [20, 24, 40] as [number, number, number], travel: [120, 128, 150] as [number, number, number] };
    const ms: number[] = [];
    for (let k = 0; k < 8; k++) {
      const t = performance.now();
      r.render(tp, n * k / 8, { scale: 2.2 + k * .1, ox: 40, oy: 30 }, 1100, 840, ink, { showTravel: true, bedWidth: 370 });
      ms.push(performance.now() - t);
    }
    return ms.sort((a, b) => a - b)[4];
  });
  console.log(`500.000 Segmente: ${result.toFixed(1)} ms je Bild (Median)`);
  expect(result).toBeLessThan(100);
});

for (const theme of ['light', 'dark'] as const) test(`großes Bild über den echten Weg: Dokument, Worker, Vorschau (${theme})`, async ({ page }) => {
  await open(page, theme);
  await setMaterial(page, { name: 'Testpappel', thickness_mm: 8 });
  await page.evaluate(async () => {
    const model = await import('/src/core/model.ts');
    const { useDoc } = await import('/src/store/doc.ts');
    const d = model.newDoc('Fotogravur');
    const layer = d.layers.find((l) => l.name === 'Gravieren')!;
    const w = 1500, h = 1000, gray = new Uint8Array(w * h);
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
      const r = Math.hypot(x - w / 2, y - h / 2) / 500;
      gray[y * w + x] = Math.max(0, Math.min(255, 128 + 110 * Math.cos(r * 18) * (1 - r * .4) + (x % 7) * 2));
    }
    let bin = ''; for (let i = 0; i < gray.length; i += 8192) bin += String.fromCharCode(...gray.subarray(i, i + 8192));
    d.elements.push(model.newElement(layer.id, 'Bild', { raster: { width: w, height: h, grayBase64: btoa(bin) }, imageWidthMm: 150, imageHeightMm: 100, transform: { x: 40, y: 60, scaleX: 1, scaleY: 1, rotation: 0 } }));
    useDoc.getState().load(d);
  });
  await ready(page);
  const slider = page.getByTestId('preview-slider'), canvas = page.getByTestId('preview-canvas');
  const count = +(await slider.getAttribute('max'))!;
  expect(count).toBeGreaterThan(200_000);
  const box = (await canvas.boundingBox())!;
  await page.mouse.move(box.x + box.width / 3, box.y + box.height / 3);
  const times: number[] = [];
  for (let i = 0; i < 6; i++) { await page.mouse.wheel(0, i < 3 ? -240 : 240); await page.waitForTimeout(120); times.push(+(await canvas.getAttribute('data-render-ms'))!); }
  times.sort((a, b) => a - b);
  console.log(`${count} Segmente im echten Auftrag: ${times[3]} ms je Bild (Median), bis ${times[5]} ms`);
  expect(times[3]).toBeLessThan(120);
  await canvas.dblclick();
  await slider.fill(String(Math.floor(count * .55)));
  await page.waitForTimeout(250);
  await page.screenshot({ path: shot(`foto-${theme}`) });
  await slider.fill(String(count));
  await page.waitForTimeout(250);
  await page.screenshot({ path: shot(`foto-ganz-${theme}`) });
});

test('Rahmen und Start gehen durch den Go-Dialog, Abbrechen beendet den Lauf', async ({ page }) => {
  await open(page);
  await clearJobs(page);
  await setMaterial(page, { name: 'Testpappel', thickness_mm: 8 });
  await setMotif(page, { size: 90, title: 'Rennlauf' });
  await ready(page);
  await page.waitForTimeout(300);
  await page.screenshot({ path: shot('bereit-light') });

  // Nein heißt nein: nichts bewegt sich.
  await page.getByTestId('frame').click();
  await page.getByRole('dialog').getByRole('button', { name: 'Abbrechen' }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  expect((await status(page)).frame.state).not.toBe('running');

  await page.getByTestId('frame').click();
  const homing = !(await status(page)).homed;
  await page.getByTestId('go-confirm').click();
  if (homing) await page.getByTestId('go-confirm').click({ timeout: 60_000 });
  await expect.poll(async () => (await status(page)).frame.state, { timeout: 30_000 }).toMatch(/running|starting|complete/);
  await untilIdle(page);

  await page.getByTestId('start').click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toContainText('Rennlauf.gcode');
  await page.keyboard.press('Enter'); // Enter darf nicht starten: der Fokus liegt auf Abbrechen.
  await expect(dialog).toHaveCount(0);
  expect(['idle', 'complete', 'aborted', 'error']).toContain((await status(page)).job.state);

  await page.getByTestId('start').click();
  await page.getByTestId('go-confirm').click();
  await expect(page.getByTestId('run-file')).toHaveText('Rennlauf.gcode', { timeout: 15_000 });
  await expect(page.getByTestId('start')).toHaveCount(0);
  await expect(page.locator('[data-phase="now"]')).toBeVisible();
  await expect.poll(async () => (await status(page)).job.state, { timeout: 40_000 }).toBe('running');
  await expect.poll(async () => +(await page.getByTestId('preview-canvas').getAttribute('data-upto'))!, { timeout: 30_000 }).toBeGreaterThan(0);
  await expect(page.getByTestId('run-remaining')).toContainText('noch ca.');
  await page.screenshot({ path: shot('lauf-light') });

  await page.getByTestId('job-abort').click();
  await expect(page.getByTestId('job-result')).toHaveAttribute('data-state', 'aborted', { timeout: 60_000 });
  await page.screenshot({ path: shot('abgebrochen-light') });
  await untilIdle(page);
});

test('Ablehnung durch den Pi erscheint als Prüfung, nicht als Absturz', async ({ page }) => {
  await open(page);
  await setMaterial(page, { name: 'Testpappel', thickness_mm: 8 });
  await setMotif(page, { title: 'Abgelehnt' });
  await ready(page);
  await page.route('**/api/upload', (r) => r.fulfill({ status: 400, contentType: 'application/json', body: JSON.stringify({ error: 'G-Code Zeile 7: Laserleistung über dem Grenzwert' }) }));
  await page.getByTestId('start').click();
  await expect(check(page, 'rejected')).toContainText('G-Code Zeile 7');
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await page.unroute('**/api/upload');

  // Echte Ablehnung beim Start: der Simulator kennt die Datei, autorun scheitert aber am Pi-Satz.
  await page.route('**/api/action', async (r) => {
    if ((r.request().postData() ?? '').includes('op=autorun')) await r.fulfill({ status: 400, contentType: 'application/json', body: JSON.stringify({ error: 'Kein Abtastpunkt erreichbar: Motiv weiter in die Mitte legen' }) });
    else await r.continue();
  });
  await setMotif(page, { title: 'Abgelehnt', size: 61 });
  await ready(page);
  await expect(check(page, 'rejected')).toHaveCount(0);
  await page.getByTestId('start').click();
  await page.getByTestId('go-confirm').click();
  await expect(check(page, 'rejected')).toContainText('Kein Abtastpunkt');
  await expect(page.getByTestId('start-view')).toBeVisible();
  await page.waitForTimeout(200);
  await page.screenshot({ path: shot('abgelehnt-light') });
});

test('Fehler im Lauf: der Satz des Pi steht als Ergebnis da', async ({ page }) => {
  await open(page);
  await setMaterial(page, { name: 'Testpappel', thickness_mm: 4 }); // der Simulator misst 8 mm
  await setMotif(page, { title: 'Zu hoch' });
  await ready(page);
  await page.getByTestId('start').click();
  await page.getByTestId('go-confirm').click();
  await expect(page.getByTestId('job-result')).toHaveAttribute('data-state', 'error', { timeout: 60_000 });
  await expect(page.getByTestId('job-result')).toContainText('Gemessen 8.0 mm');
  await page.screenshot({ path: shot('fehler-light') });
  await untilIdle(page);
});

test('Warteschlange und gespeicherte Aufträge', async ({ page }) => {
  await open(page, 'light', { width: 1440, height: 900 }, { 'lc.start.dock': '1' });
  await clearJobs(page);
  await setMaterial(page, { name: 'Testpappel', thickness_mm: 8 });
  await setMotif(page, { title: 'Erster' });
  await ready(page);
  await page.getByTestId('queue-add-current').click();
  await expect(page.getByTestId('queue-item')).toHaveCount(1);
  await setMotif(page, { title: 'Zweiter', size: 40 });
  await ready(page);
  await page.getByTestId('queue-add-current').click();
  await expect(page.getByTestId('queue-item')).toHaveCount(2);
  await expect(page.getByTestId('queue-count')).toHaveText('2');
  await expect(page.getByTestId('job-row')).toHaveCount(2);

  // Vorschau eines gespeicherten Auftrags, dann zurück.
  await page.getByTestId('job-row').filter({ hasText: 'Erster.gcode' }).getByTestId('job-preview').click();
  await expect(page.getByTestId('source-name')).toHaveText('Erster.gcode');
  await ready(page);
  await page.waitForTimeout(200);
  await page.screenshot({ path: shot('warteschlange-light') });
  await page.getByTestId('back-to-motif').click();
  await expect(page.getByTestId('source-name')).toHaveCount(0);

  // Einträge bearbeiten.
  await page.getByRole('button', { name: 'Zweiter.gcode überspringen' }).click();
  await expect(page.getByTestId('queue-item').nth(1)).toHaveAttribute('data-state', 'skipped');
  await page.getByRole('button', { name: 'Zweiter.gcode entfernen' }).click();
  await expect(page.getByTestId('queue-item')).toHaveCount(1);
  await expect(page.getByTestId('job-row').filter({ hasText: 'Erster.gcode' }).getByTestId('job-delete')).toBeDisabled();

  // Export.
  const dl = page.waitForEvent('download');
  await page.getByTestId('job-row').filter({ hasText: 'Zweiter.gcode' }).getByTestId('job-export').click();
  expect((await dl).suggestedFilename()).toBe('Zweiter.gcode');

  // Lauf mit Go, dann Pause und Abbruch.
  await page.getByTestId('queue-run').click();
  await page.getByTestId('go-confirm').click();
  await expect(page.getByTestId('run-file')).toHaveText('Erster.gcode', { timeout: 15_000 });
  await page.getByTestId('queue-pause').click();
  await expect.poll(async () => (await status(page)).queue.state, { timeout: 10_000 }).toMatch(/pausing|paused/);
  await page.getByTestId('job-abort').click();
  await untilIdle(page);
  await expect(page.getByTestId('queue-item').first()).toHaveAttribute('data-state', /aborted|done/, { timeout: 30_000 });
  await page.getByTestId('queue-clear').click();
  await expect(page.getByTestId('queue-item')).toHaveCount(0);

  // Löschen fragt nach.
  await page.getByTestId('job-row').filter({ hasText: 'Zweiter.gcode' }).getByTestId('job-delete').click();
  await page.getByRole('dialog').getByRole('button', { name: 'Löschen' }).click();
  await expect(page.getByTestId('job-row').filter({ hasText: 'Zweiter.gcode' })).toHaveCount(0);
});

test('Projekte: auf dem Pi speichern und öffnen, lokale Datei, Konflikt', async ({ page }) => {
  await open(page, 'light', { width: 1440, height: 900 }, { 'lc.sync.e2e': '1' });
  await setMotif(page, { title: 'Ablage' });
  await page.evaluate(async () => { const s = await import('/src/pi/sync.ts'); void s.saveProjectToPi(); });
  const name = page.getByTestId('project-name');
  await expect(name).toHaveValue('Ablage');
  await page.waitForTimeout(300);
  await page.screenshot({ path: shot('projekt-speichern-light') });
  await page.getByTestId('project-save').click();
  await expect(name).toHaveCount(0);

  await page.evaluate(async () => { (await import('/src/store/doc.ts')).useDoc.getState().reset(); });
  await page.evaluate(async () => { const s = await import('/src/pi/sync.ts'); void s.openProjectDialog(); });
  await page.getByTestId('project-list').getByRole('button', { name: /Ablage/ }).first().click();
  await expect.poll(() => page.evaluate(async () => (await import('/src/store/doc.ts')).useDoc.getState().doc.title)).toBe('Ablage');
  await expect.poll(() => page.evaluate(async () => (await import('/src/store/doc.ts')).useDoc.getState().doc.elements.length)).toBe(2);

  // Lokale Datei.
  const dl = page.waitForEvent('download');
  const saved = await page.evaluate(async () => (await import('/src/pi/sync.ts')).saveLocal());
  expect(saved).toBe(true);
  expect((await dl).suggestedFilename()).toBe('Ablage.lumacut');

  // Konflikt: hier geändert, und auf dem Pi hat ein anderes Gerät geschrieben.
  await expect.poll(async () => (await status(page)).sync.project, { timeout: 10_000 }).toBeGreaterThan(0);
  await page.waitForTimeout(2500);
  await page.evaluate(async () => { (await import('/src/store/doc.ts')).useDoc.getState().commit((d) => ({ ...d, title: 'Hier geändert' })); });
  const other = await page.evaluate(async () => { const m = await import('/src/core/model.ts'); return m.toJson(m.newDoc('Vom Tablet')); });
  const put = await page.request.put('/api/workspace/project?by=Tablet', { data: other, headers: { 'Content-Type': 'application/json' } });
  expect(put.ok()).toBe(true);
  await expect(page.getByTestId('conflict-take')).toBeVisible({ timeout: 15_000 });
  await page.waitForTimeout(250);
  await page.screenshot({ path: shot('konflikt-light') });
  await page.getByTestId('conflict-take').click();
  await expect.poll(() => page.evaluate(async () => (await import('/src/store/doc.ts')).useDoc.getState().doc.title)).toBe('Vom Tablet');
});

for (const [theme, size] of [['dark', { width: 1440, height: 900 }], ['light', { width: 1280, height: 720 }], ['dark', { width: 1000, height: 640 }], ['light', { width: 2560, height: 1440 }]] as const) {
  test(`Layout ${theme} ${size.width}x${size.height}`, async ({ page }) => {
    await open(page, theme, size, { 'lc.start.dock': size.height > 700 ? '1' : '0' });
    await setMaterial(page, { name: 'Testpappel', thickness_mm: 8 });
    await setMotif(page, { size: 120, plates: 2, power: 5 });
    await ready(page);
    await page.waitForTimeout(400);
    await page.screenshot({ path: shot(`layout-${theme}-${size.width}`) });
    const side = await page.locator('.start-side').boundingBox();
    expect(side!.x + side!.width).toBeLessThanOrEqual(size.width);
    await expect(page.getByTestId('start')).toBeInViewport();
  });
}

test('NOT-AUS während des Laufs: Ergebnis und Sperre stehen auf der Seite', async ({ page }) => {
  await open(page, 'dark');
  await setMaterial(page, { name: 'Testpappel', thickness_mm: 8 });
  await setMotif(page, { size: 90, title: 'Notlauf' });
  await ready(page);
  await page.getByTestId('start').click();
  await page.getByTestId('go-confirm').click();
  await expect.poll(async () => (await status(page)).job.state, { timeout: 40_000 }).toBe('running');
  await page.getByTestId('estop').click();
  await expect(check(page, 'machine')).toContainText('Not-Aus', { timeout: 15_000 });
  await expect(page.getByTestId('start')).toBeDisabled();
  await page.waitForTimeout(300);
  await page.screenshot({ path: shot('notaus-dark') });
  // Der Simulator kann den Riegel nicht lösen (M115 nach dem Reset scheitert), darum steht dieser Test zuletzt.
  await expect(page.getByRole('button', { name: 'Not-Aus quittieren' })).toBeVisible();
  await expect.poll(async () => (await status(page)).job.state, { timeout: 30_000 }).toBe('aborted');
  await expect(page.getByTestId('job-result')).toHaveAttribute('data-state', 'aborted');
});
