import { test, expect, type Page } from '@playwright/test';

const shot = (name: string) => `tests/e2e/screenshots/platine-${name}.png`;

async function open(page: Page, theme: 'light' | 'dark', size?: { width: number; height: number }) {
  if (size) await page.setViewportSize(size);
  await page.addInitScript((t) => { localStorage.setItem('lc.theme', JSON.stringify(t)); localStorage.setItem('lc.dest', JSON.stringify('platine')); }, theme);
  // Project sync (src/pi/sync.ts) may ask when the simulator kept a project from an earlier run.
  await page.addLocatorHandler(page.getByRole('button', { name: 'Diese Fassung behalten' }), async (b) => { await b.click(); });
  await page.goto('/');
  await expect(page.getByTestId('platine')).toBeVisible();
}

for (const theme of ['light', 'dark'] as const) {
  test(`Assistent von Datei bis Motiv, ${theme}`, async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (e) => errors.push(e.message));
    await open(page, theme);

    await page.waitForTimeout(200);
    await page.screenshot({ path: shot(`1-leer-${theme}`) });
    await expect(page.getByTestId('pcb-next')).toBeDisabled();
    await expect(page.getByTestId('pcb-step-3')).toBeDisabled();

    await page.getByTestId('pcb-example').click();
    const rows = page.getByTestId('pcb-files').locator('tbody tr');
    await expect(rows).toHaveCount(7);
    await expect(page.getByTestId('pcb-facts')).toContainText('60,0 × 40,0 mm');
    await expect(page.getByTestId('pcb-facts')).toContainText('26');
    await page.screenshot({ path: shot(`1-dateien-${theme}`) });

    await page.getByTestId('pcb-next').click();
    await expect(page.getByTestId('pcb-bed')).toBeVisible();
    await page.getByRole('radio', { name: 'Unterseite' }).click();
    await expect(page.locator('label.check', { hasText: 'Spiegeln' }).locator('input')).toBeChecked();
    await page.getByRole('radio', { name: 'Oberseite' }).click();
    await expect(page.locator('label.check', { hasText: 'Spiegeln' }).locator('input')).not.toBeChecked();
    await page.screenshot({ path: shot(`2-platine-${theme}`) });

    // Ziehen in der Karte verschiebt die Position
    const x = page.getByLabel('Position X');
    const before = await x.inputValue();
    const b = await page.getByTestId('pcb-bed-board').boundingBox();
    if (!b) throw new Error('Platine nicht sichtbar');
    await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2);
    await page.mouse.down();
    await page.mouse.move(b.x + b.width / 2 - 60, b.y + b.height / 2 + 30, { steps: 4 });
    await page.mouse.up();
    expect(await x.inputValue()).not.toBe(before);
    await page.getByTestId('pcb-center').click();
    await expect(x).toHaveValue(before);

    await page.getByTestId('pcb-next').click();
    await page.getByTestId('pcb-mask').click();
    await page.getByTestId('pcb-silk').click();
    await page.getByLabel('Strahlbreite').fill('0,2');
    await page.getByLabel('Strahlbreite').press('Enter');
    await expect(page.getByTestId('pcb-interval')).toHaveText('0,150 mm');
    await page.screenshot({ path: shot(`3-verfahren-${theme}`) });
    await page.getByRole('radio', { name: 'Isolation' }).click();
    await expect(page.getByLabel('Durchgänge')).toBeVisible();
    await page.getByRole('radio', { name: 'Fotofilm belichten' }).click();
    await expect(page.getByText('Dieser Weg ist hier nicht erprobt')).toBeVisible();
    await page.screenshot({ path: shot(`3-fotofilm-${theme}`) });
    await page.getByRole('radio', { name: 'Raster negativ' }).click();

    await page.getByTestId('pcb-next').click();
    const cv = page.getByTestId('pcb-canvas');
    await expect(cv).toBeVisible();
    await expect(page.getByTestId('pcb-checks')).toContainText('Kleinster Abstand');
    await expect(page.getByTestId('pcb-checks')).toContainText('Kleinste Leiterbreite 0,60 mm');
    await page.waitForTimeout(150);
    await page.screenshot({ path: shot(`4-vorschau-${theme}`) });

    const zoom0 = +(await cv.getAttribute('data-zoom'))!;
    const box = await cv.boundingBox();
    await page.mouse.move(box!.x + box!.width / 2, box!.y + box!.height / 2);
    await page.mouse.wheel(0, -400);
    await expect.poll(async () => +(await cv.getAttribute('data-zoom'))!).toBeGreaterThan(zoom0);
    await page.waitForTimeout(100);
    await page.screenshot({ path: shot(`4-zoom-${theme}`) });
    await page.getByTestId('pcb-fit').click();
    await expect(cv).toHaveAttribute('data-zoom', zoom0.toFixed(2));

    await page.getByTestId('pcb-layer-resist').click();
    await page.getByRole('radio', { name: 'Von unten' }).click();
    await page.waitForTimeout(100);
    await page.screenshot({ path: shot(`4-unten-${theme}`) });
    await page.getByRole('radio', { name: 'Von oben' }).click();
    await page.getByTestId('pcb-layer-resist').click();

    await page.getByTestId('pcb-next').click();
    await expect(page.getByText('Pflicht: Materialtest')).toBeVisible();
    await expect(page.getByTestId('pcb-processes')).toContainText('Ätzresist');
    await expect(page.getByTestId('pcb-workflow')).toContainText('Ätzen');
    await page.screenshot({ path: shot(`5-lasern-${theme}`) });

    // Untergrenze 8 %
    const power = page.getByLabel('Leistung Platine Ätzresist');
    await power.fill('3'); await power.press('Enter');
    await expect(power).toHaveValue('8');
    await power.fill('20'); await power.press('Enter');

    await page.getByTestId('pcb-to-motiv').click();
    await expect(page.getByTestId('nav-motiv')).toHaveAttribute('aria-current', 'page');
    const doc = await page.evaluate(async () => {
      const { useDoc } = await import('/src/store/doc.ts');
      const d = useDoc.getState().doc;
      return { layers: d.layers.map((l) => ({ name: l.name, mode: l.mode, output: l.output, interval: l.intervalMm, power: l.powerPct })), count: d.elements.length, kinds: [...new Set(d.elements.map((e) => e.kind))], undo: useDoc.getState().past.length };
    });
    expect(doc.kinds).toEqual(['Platine']);
    const layer = (n: string) => doc.layers.find((l) => l.name === n);
    expect(layer('Platine Ätzresist')).toMatchObject({ mode: 'FILL', output: true, power: 20 });
    expect(layer('Platine Ätzresist')!.interval).toBeCloseTo(0.15);
    expect(layer('Platine Lötstopp')).toMatchObject({ output: false });
    expect(layer('Platine Beschriftung')).toMatchObject({ output: false });
    expect(layer('Platine Umriss')).toMatchObject({ mode: 'LINE', output: false });
    expect(doc.undo).toBe(1);

    await page.getByTestId('nav-platine').click();
    await expect(page.getByTestId('pcb-processes')).toBeVisible();
    await page.getByTestId('pcb-to-motiv').click();
    await expect(page.getByRole('dialog')).toContainText('ersetzen');
    await page.getByRole('button', { name: 'Abbrechen' }).click();
    await expect(page.getByTestId('pcb-processes')).toBeVisible();

    expect(errors).toEqual([]);
  });
}

test('Dateien wählen, Lage ändern, zu enger Abstand wird gemeldet', async ({ page }) => {
  await open(page, 'light');
  const gerber = '%FSLAX46Y46*%\n%MOMM*%\n%ADD10R,2X2*%\n%ADD11C,0.1*%\nD10*\nX5000000Y5000000D03*\nX7100000Y5000000D03*\nD11*\nX1000000Y9000000D02*\nX9000000Y9000000D01*\nM02*\n';
  const chooser = page.waitForEvent('filechooser');
  await page.getByRole('button', { name: 'Dateien wählen' }).click();
  await (await chooser).setFiles([
    { name: 'eng.GTL', mimeType: 'text/plain', buffer: Buffer.from(gerber) },
    { name: 'unbekannt.xyz', mimeType: 'text/plain', buffer: Buffer.from(gerber) },
  ]);
  const rows = page.getByTestId('pcb-files').locator('tbody tr');
  await expect(rows).toHaveCount(2);
  await expect(page.getByLabel('Lage von eng.GTL')).toHaveValue('copper-top');
  await expect(page.getByLabel('Lage von unbekannt.xyz')).toHaveValue('other');
  await expect(page.getByText('Keine Umrissdatei')).toBeVisible();
  await page.getByLabel('Lage von unbekannt.xyz').selectOption('silk-top');
  await expect(page.getByTestId('pcb-facts')).toContainText('oben');
  await page.getByTestId('pcb-step-4').click();
  await expect(page.getByTestId('pcb-checks')).toContainText('Enger als der Strahl');
  await expect(page.getByTestId('pcb-checks')).toContainText('Schmaler als der Strahl');
  await page.waitForTimeout(150);
  await page.screenshot({ path: shot('4-warnung-light') });
});

for (const [name, size] of [['1280', { width: 1280, height: 720 }], ['2560', { width: 2560, height: 1440 }], ['1000', { width: 1000, height: 640 }]] as const) {
  test(`Layout ${name}`, async ({ page }) => {
    await open(page, 'dark', size);
    await page.getByTestId('pcb-example').click();
    for (const i of [1, 2, 3, 4, 5]) {
      await page.getByTestId(`pcb-step-${i}`).click();
      await page.waitForTimeout(120);
      await page.screenshot({ path: shot(`${i}-${name}`) });
    }
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
    expect(overflow).toBe(false);
  });
}

test('Unterseite mit Isolation: gespiegelt, passt zur Ansicht von unten', async ({ page }) => {
  await open(page, 'light');
  await page.getByTestId('pcb-example').click();
  await page.getByTestId('pcb-step-2').click();
  await page.getByRole('radio', { name: 'Unterseite' }).click();
  await page.waitForTimeout(100);
  await page.screenshot({ path: shot('2-unten-light') });
  await page.getByTestId('pcb-step-3').click();
  await page.getByRole('radio', { name: 'Isolation' }).click();
  await page.getByLabel('Durchgänge').fill('2');
  await page.getByLabel('Durchgänge').press('Enter');
  await page.getByTestId('pcb-rest').click();
  await page.screenshot({ path: shot('3-isolation-light') });
  await page.getByTestId('pcb-step-4').click();
  await expect(page.getByText('So liegt sie unter dem Laser')).toBeVisible();
  await page.waitForTimeout(150);
  await page.screenshot({ path: shot('4-isolation-light') });
  await page.getByRole('radio', { name: 'Von oben' }).click();
  await expect(page.getByText('Nicht die Ansicht unter dem Laser')).toBeVisible();
  await page.getByRole('radio', { name: 'Von unten' }).click();
  await page.getByTestId('pcb-step-5').click();
  await expect(page.getByTestId('pcb-processes')).toContainText('Ätzresist Rest');
  await page.screenshot({ path: shot('5-isolation-light') });
  await page.getByTestId('pcb-to-start').click();
  await expect(page.getByTestId('nav-start')).toHaveAttribute('aria-current', 'page');
  const names = await page.evaluate(async () => {
    const { useDoc } = await import('/src/store/doc.ts');
    return useDoc.getState().doc.layers.map((l) => `${l.name}:${l.mode}`);
  });
  expect(names).toContain('Platine Ätzresist:LINE');
  expect(names).toContain('Platine Ätzresist Rest:FILL');
});
