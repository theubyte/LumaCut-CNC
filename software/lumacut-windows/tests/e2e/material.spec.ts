import { expect, type Page, test } from '@playwright/test';

test.describe.configure({ mode: 'serial' });
const SHOTS = 'tests/e2e/screenshots';
const NAME = `Birke Test ${Date.now() % 100000}`;

const open = async (page: Page, dest = 'material', theme: 'light' | 'dark' = 'light') => {
  await page.addInitScript(([t, d]) => { localStorage.setItem('lc.theme', JSON.stringify(t)); localStorage.setItem('lc.dest', JSON.stringify(d)); }, [theme, dest]);
  await page.goto('/');
  await expect(page.getByTestId('estop')).toBeVisible();
};
const materials = async (page: Page) => (await (await page.request.get('/api/materials')).json()).materials as Record<string, any>[];
const entry = async (page: Page, process: string) => (await materials(page)).find((m) => m.name === NAME && m.process === process);
const workspace = async (page: Page) => (await page.request.get('/api/workspace')).json();

test('Bibliothek vom Pi, Suche', async ({ page }) => {
  await open(page);
  await expect(page.getByTestId('mt-item').first()).toBeVisible();
  const before = await page.getByTestId('mt-item').count();
  expect(before).toBeGreaterThan(1);
  await page.getByTestId('mt-search').fill('zzzz');
  await expect(page.getByTestId('mt-item')).toHaveCount(0);
  await expect(page.locator('.mt-list')).toContainText('Nichts gefunden');
  await page.getByTestId('mt-search').fill('');
  await expect(page.getByTestId('mt-item')).toHaveCount(before);
  await page.screenshot({ path: `${SHOTS}/material-liste.png` });
});

test('Anlegen, ändern, Prozess hinzufügen und löschen', async ({ page }) => {
  await open(page);
  await page.getByTestId('mt-new').click();
  await expect(page.getByTestId('mt-save')).toBeDisabled();
  await page.getByTestId('mt-name').fill(NAME);
  await page.getByLabel('Stärke').fill('4'); await page.getByLabel('Stärke').blur();
  await page.screenshot({ path: `${SHOTS}/material-neu.png` });
  await page.getByTestId('mt-save').click();
  await expect(page.getByTestId('mt-title')).toHaveText(NAME);
  await expect.poll(async () => (await materials(page)).filter((m) => m.name === NAME).length).toBe(2);

  // a value commits with Enter and reaches the Pi
  await page.getByLabel('Gravieren Leistung').fill('33');
  await page.keyboard.press('Enter');
  await expect.poll(async () => (await entry(page, 'Gravieren'))?.power_pct).toBe(33);
  await page.getByLabel('Schneiden Tempo').fill('650,5');
  await page.keyboard.press('Tab');
  await expect.poll(async () => (await entry(page, 'Schneiden'))?.speed_mm_min).toBe(650.5);
  // below the reliable power is not accepted
  await page.getByLabel('Gravieren Leistung').fill('3');
  await page.keyboard.press('Enter');
  await expect.poll(async () => (await entry(page, 'Gravieren'))?.power_pct).toBe(8);

  // missing process, then delete it again
  await page.getByTestId('mt-add-Markieren').click();
  await expect.poll(async () => !!(await entry(page, 'Markieren'))).toBe(true);
  await page.getByTestId('mt-del-Markieren').click();
  await page.getByRole('dialog').getByRole('button', { name: 'Löschen' }).click();
  await expect.poll(async () => !!(await entry(page, 'Markieren'))).toBe(false);
  await expect(page.getByTestId('mt-add-Markieren')).toBeVisible();
});

test('Tonkurve wird gezeigt', async ({ page }) => {
  const g = await entry(page, 'Gravieren');
  const rev = (await (await page.request.get('/api/materials')).json()).revision;
  const r = await page.request.put(`/api/materials/${g!.id}`, { data: { base_revision: rev, tone_curve: { points: [{ power: 10, speed: 3000, tone: .2 }, { power: 20, speed: 3000, tone: .45 }, { power: 35, speed: 3000, tone: .7, clean: false }, { power: 50, speed: 3000, tone: .88 }] } } });
  expect(r.ok()).toBe(true);
  await open(page);
  await page.getByTestId('mt-item').filter({ hasText: NAME }).click();
  await expect(page.getByTestId('mt-tone')).toContainText('4 Messpunkte');
  await page.screenshot({ path: `${SHOTS}/material-tonkurve.png` });
});

test('Verwenden: Arbeitsstand des Pi, Werte auf den Ebenen, ein Undo-Schritt', async ({ page }) => {
  await page.request.put('/api/workspace', { data: { material: null } });
  await open(page);
  await page.getByTestId('mt-item').filter({ hasText: NAME }).click();
  await expect(page.getByTestId('mt-use')).toHaveText('Dieses Material verwenden');
  await page.getByTestId('mt-use').click();
  await expect(page.getByTestId('mt-use')).toHaveText('Wird verwendet');
  await expect(page.getByTestId('mt-current-chip')).toHaveCount(1);
  const ws = await workspace(page);
  expect(ws.material).toEqual({ name: NAME, thickness_mm: 4 });
  expect(ws.updated_by).toBe('Windows');
  await page.screenshot({ path: `${SHOTS}/material-aktuell.png` });

  const doc = await page.evaluate(async () => {
    const { useDoc } = await import('/src/store/doc.ts');
    const s = useDoc.getState();
    const by = (n: string) => s.doc.layers.find((l: { name: string }) => l.name === n)!;
    const out = { engrave: by('Gravieren').powerPct, name: by('Gravieren').materialName, cutSpeed: by('Schneiden').speed, line: by('Linie').materialName, past: s.past.length, darkness: !!by('Gravieren').darkness };
    s.undo();
    const undone = useDoc.getState().doc.layers.find((l: { name: string }) => l.name === 'Gravieren')!.materialName;
    return { ...out, undone };
  });
  expect(doc).toEqual({ engrave: 8, name: NAME, cutSpeed: 650.5, line: null, past: 1, darkness: true, undone: null });

  // a job needs this on the Pi: the Pi now accepts the material
  const stored = await workspace(page);
  expect(stored.material.name).toBe(NAME);

  // another device changes it: the app follows on its own
  await page.request.put('/api/workspace', { data: { material: { name: 'Anderes', thickness_mm: 2 } } });
  await expect(page.getByTestId('mt-use')).toHaveText('Dieses Material verwenden', { timeout: 8000 });
});

test('Konflikt: Liste wird neu geladen und der Satz sagt, was zu tun ist', async ({ page }) => {
  await open(page);
  await page.getByTestId('mt-item').filter({ hasText: NAME }).click();
  await expect(page.getByLabel('Schneiden Leistung')).toBeVisible();
  const list = await (await page.request.get('/api/materials')).json();
  const other = list.materials.find((m: { name: string }) => m.name !== NAME);
  await page.request.put(`/api/materials/${other.id}`, { data: { base_revision: list.revision, notes: 'x' } });
  await page.getByLabel('Schneiden Leistung').fill('70');
  await page.keyboard.press('Enter');
  await expect(page.locator('.toast').last()).toContainText('neu geladen');
  expect((await entry(page, 'Schneiden'))?.power_pct).not.toBe(70);
});

test('Umbenennen und ganz löschen', async ({ page }) => {
  await open(page);
  await page.getByTestId('mt-item').filter({ hasText: NAME }).click();
  await page.getByTestId('mt-edit').click();
  await page.getByTestId('mt-name').fill(`${NAME} neu`);
  await page.getByTestId('mt-save').click();
  await expect(page.getByTestId('mt-title')).toHaveText(`${NAME} neu`);
  await expect.poll(async () => (await materials(page)).filter((m) => m.name === `${NAME} neu`).length).toBe(2);
  await page.getByTestId('mt-edit').click();
  await page.getByTestId('mt-group-delete').click();
  await page.getByRole('button', { name: 'Löschen', exact: true }).click();
  await expect.poll(async () => (await materials(page)).filter((m) => m.name.startsWith(NAME)).length).toBe(0);
});

test('Ohne Pi: Liste aus dem Zwischenspeicher, nicht änderbar', async ({ page }) => {
  await open(page);
  await expect(page.getByTestId('mt-item').first()).toBeVisible();
  await page.route('**/api/**', (r) => r.abort());
  await page.reload();
  await expect(page.locator('.mt-offline')).toContainText('Kein Kontakt', { timeout: 10000 });
  await expect(page.getByTestId('mt-item').first()).toBeVisible();
  await expect(page.getByTestId('mt-new')).toBeDisabled();
  await expect(page.getByTestId('mt-use')).toBeDisabled();
  await page.screenshot({ path: `${SHOTS}/material-offline.png` });
});

test('Optionen: Adresse prüfen, Thema, Update, Kürzel', async ({ page }) => {
  await open(page, 'einstellungen');
  await expect(page.getByTestId('o-online')).toContainText('Verbunden', { timeout: 8000 });
  await expect(page.getByTestId('o-address')).toHaveValue('http://192.168.2.89:8080');
  await page.getByTestId('o-test').click();
  await expect(page.getByTestId('o-check')).toContainText('Erreichbar');
  await page.getByTestId('o-address').fill('http://u:p@1.2.3.4');
  await expect(page.getByTestId('o-test')).toBeDisabled();
  await expect(page.getByTestId('o-connection')).toContainText('ohne Benutzer');
  await page.getByTestId('o-address').fill('http://192.168.2.89:8080');
  await page.getByRole('radio', { name: 'Dunkel' }).click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  await page.screenshot({ path: `${SHOTS}/optionen-dunkel.png`, fullPage: false });
  await page.getByRole('radio', { name: 'Hell' }).click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
  await page.getByTestId('o-check-update').click();
  await expect(page.getByTestId('o-update-result')).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/optionen-hell.png` });
  await expect(page.getByTestId('o-keys')).toContainText('NOT-AUS');
});

for (const theme of ['light', 'dark'] as const) {
  for (const [w, h] of [[1000, 640], [1280, 720], [2560, 1440]] as const) {
    test(`Aussehen ${theme} ${w}x${h}`, async ({ page }) => {
      await page.setViewportSize({ width: w, height: h });
      await open(page, 'material', theme);
      await expect(page.getByTestId('mt-item').first()).toBeVisible();
      await page.waitForTimeout(250);
      await page.screenshot({ path: `${SHOTS}/material-${theme}-${w}.png` });
      await page.getByTestId('nav-einstellungen').click();
      await page.waitForTimeout(250);
      await page.screenshot({ path: `${SHOTS}/optionen-${theme}-${w}.png` });
    });
  }
}
