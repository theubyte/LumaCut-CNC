import { expect, type Page, test } from '@playwright/test';

// Real operation against the simulator (tools/sim_pi.py): clicks, keys, go dialogs, then what the Pi says.
// Runs in order and shares the simulator state; start a fresh simulator for a fresh run.
test.describe.configure({ mode: 'serial' });
const SHOTS = 'tests/e2e/screenshots';

const open = async (page: Page, dest: string, tab?: string, theme: 'light' | 'dark' = 'light') => {
  await page.addInitScript(([t, d]) => { localStorage.setItem('lc.theme', JSON.stringify(t)); localStorage.setItem('lc.dest', JSON.stringify(d)); }, [theme, dest]);
  await page.goto('/');
  await expect(page.getByTestId('estop')).toBeVisible();
  if (tab) await page.getByRole('tab', { name: tab }).click();
};
const status = async (page: Page) => (await page.request.get('/api/status')).json();
const confirmGo = (page: Page) => page.getByTestId('go-confirm').click();
const cancelGo = (page: Page) => page.getByRole('dialog').getByRole('button', { name: 'Abbrechen' }).click();
const shot = (page: Page, name: string) => page.screenshot({ path: `${SHOTS}/maschine-${name}.png` });
const until = async (page: Page, fn: (s: Record<string, any>) => boolean) => expect.poll(async () => fn(await status(page)), { timeout: 15000 }).toBe(true);
const form = (op: string, f: Record<string, string> = {}) => ({ form: { op, ...f } });

test('Steuerung gesperrt, Referenz mit Rückfrage, Abbrechen tut nichts', async ({ page }) => {
  await open(page, 'maschine');
  await expect(page.getByTestId('m-headline')).toHaveText('Nicht referenziert');
  await shot(page, 'steuerung-ungereferenziert');
  // every move is locked and says why
  for (const id of ['jog-up', 'jog-left', 'jog-zup']) await expect(page.getByTestId(id)).toBeDisabled();
  await expect(page.getByTestId('m-park')).toHaveAttribute('data-lock', /referenziert/i);
  await expect(page.getByTestId('m-probe')).toHaveAttribute('data-lock', /referenziert/i);
  await expect(page.getByTestId('m-moveto')).toHaveAttribute('data-lock', /referenziert/i);
  await expect(page.getByTestId('m-origin-set')).toHaveAttribute('data-lock', /referenziert/i);
  await expect(page.getByTestId('lock-line').first()).toContainText('Nicht referenziert');
  // a key while locked moves nothing, it tells the reason
  const before = (await status(page)).position;
  await page.keyboard.press('ArrowRight');
  await expect(page.locator('.toast').last()).toContainText('referenziert');
  expect((await status(page)).position).toEqual(before);

  const s0 = await status(page);
  await page.getByTestId('m-home-next').click();
  const dlg = page.getByRole('dialog');
  if (s0.home_needs_confirm) await expect(dlg).toContainText('Steht der Kopf frei');
  else await expect(dlg).toContainText('Referenzfahrt');
  await shot(page, 'go-dialog');
  // Enter must not confirm: the focus is on cancel
  await page.keyboard.press('Enter');
  await expect(dlg).toBeHidden();
  expect((await status(page)).homed).toBe(false);
  await page.getByTestId('m-home').click();
  await cancelGo(page);
  expect((await status(page)).homed).toBe(false);
  await page.getByTestId('m-home').click();
  await confirmGo(page);
  await until(page, (s) => s.homed === true);
  await expect(page.getByTestId('m-headline')).toHaveText('Bereit');
  await expect(page.getByTestId('jog-up')).toBeEnabled();
});

test('Jog: Richtung von der Tür gesehen, Maus und Tasten, Schrittweiten', async ({ page }) => {
  await open(page, 'maschine');
  await expect(page.getByTestId('jog-up')).toBeEnabled();
  // leave the corner first so all directions are free
  await page.getByTestId('m-moveto').click();
  await confirmGo(page);
  await until(page, (s) => s.position[1] === 100);
  const pos = async () => (await status(page)).position as number[];
  const moved = async (act: () => Promise<unknown>, axis: number, delta: number) => {
    const a = await pos();
    await act();
    await expect.poll(async () => +((await pos())[axis] - a[axis]).toFixed(3), { timeout: 5000 }).toBe(delta);
  };
  // 1 mm is the default; screen right = work +X = machine -X (Android: right = X-)
  await moved(() => page.getByTestId('jog-right').click(), 0, -1);
  await moved(() => page.getByTestId('jog-left').click(), 0, 1);
  await moved(() => page.getByTestId('jog-up').click(), 1, -1);
  await moved(() => page.getByTestId('jog-down').click(), 1, 1);
  // Z stays locked until a surface is measured, because the Pi refuses it, and it says so
  await expect(page.getByTestId('jog-zup')).toHaveAttribute('data-lock', /Abtasten/);
  await page.keyboard.press('PageUp');
  await expect(page.locator('.toast').last()).toContainText('Abtasten');
  await page.getByTestId('m-probe').click();
  await confirmGo(page);
  await until(page, (s) => s.workpiece_surface_z != null);
  await expect(page.getByTestId('jog-zup')).toBeEnabled();
  await moved(() => page.getByTestId('jog-zup').click(), 2, 1);
  await moved(() => page.getByTestId('jog-zdown').click(), 2, -1);
  // the displayed X is the work coordinate: it grows when moving right
  await expect.poll(async () => { const t = await page.getByTestId('m-x').innerText(); return t !== '–'; }).toBe(true);
  const shownX = async () => parseFloat((await page.getByTestId('m-x').innerText()).replace(',', '.'));
  const x0 = await shownX();
  await page.getByTestId('jog-right').click();
  await expect.poll(shownX, { timeout: 4000 }).toBeCloseTo(x0 + 1, 1);
  await page.getByTestId('jog-left').click();

  await page.getByRole('radio', { name: '10' }).click();
  await moved(() => page.keyboard.press('ArrowDown'), 1, 10);
  await moved(() => page.keyboard.press('ArrowUp'), 1, -10);
  await page.getByRole('radio', { name: '0,1' }).click();
  await moved(() => page.keyboard.press('ArrowRight'), 0, -0.1);
  await moved(() => page.keyboard.press('ArrowLeft'), 0, 0.1);
  await moved(() => page.keyboard.press('PageUp'), 2, 0.1);
  await moved(() => page.keyboard.press('PageDown'), 2, -0.1);
  await page.getByRole('radio', { name: '1', exact: true }).click();

  // in a text field the arrows belong to the field
  const a = await pos();
  await page.getByLabel('Ziel X').focus();
  await page.keyboard.press('ArrowLeft');
  await page.keyboard.press('PageUp');
  await page.waitForTimeout(400);
  expect(await pos()).toEqual(a);
  await page.getByLabel('Ziel X').blur();

  // not while another tab is active
  await page.getByRole('tab', { name: 'System' }).click();
  await page.keyboard.press('ArrowLeft');
  await page.waitForTimeout(400);
  expect(await pos()).toEqual(a);
});

test('Parken, Position, Abtasten, Ursprung, Licht, Abluft', async ({ page }) => {
  await open(page, 'maschine', 'Steuerung');
  await expect(page.getByTestId('m-probe')).toBeEnabled();

  // moveto: work coordinates go through toMachine, with a go
  await page.getByLabel('Ziel X').fill('120'); await page.getByLabel('Ziel X').blur();
  await page.getByLabel('Ziel Y').fill('140'); await page.getByLabel('Ziel Y').blur();
  await page.getByTestId('m-moveto').click();
  await expect(page.getByRole('dialog')).toContainText('X 120,0');
  await cancelGo(page);
  const travel = (await status(page)).config.travels.x;
  await page.getByTestId('m-moveto').click();
  await confirmGo(page);
  await until(page, (s) => s.position[0] === travel - 120 && s.position[1] === 140);
  await expect(page.getByTestId('m-x')).toHaveText('120,0');

  // probe through the go dialog
  await page.getByTestId('m-probe').click();
  await expect(page.getByRole('dialog')).toContainText('Liegt das Objekt noch');
  await cancelGo(page);
  await page.getByTestId('m-probe').click();
  await confirmGo(page);
  await expect(page.locator('.toast').last()).toContainText('Werkstückoberfläche', { timeout: 8000 });
  await expect(page.getByTestId('m-surface')).not.toHaveText('–');

  // origin without go, no move
  await page.getByTestId('m-origin-set').click();
  await until(page, (s) => Array.isArray(s.origin?.user));
  await expect(page.getByTestId('row-origin')).toContainText('X 120,0, Y 140,0');
  await page.getByTestId('m-origin-clear').click();
  await page.getByRole('dialog').getByRole('button', { name: 'Löschen' }).click();
  await until(page, (s) => s.origin?.user == null);

  // light: no go; brightness goes to the Pi
  await page.getByRole('switch', { name: 'Licht' }).click();
  await until(page, (s) => s.lights === true);
  await page.getByTestId('row-light').locator('input[type=range]').fill('35');
  await until(page, (s) => s.light_brightness === 35);
  await page.getByRole('switch', { name: 'Licht' }).click();
  await until(page, (s) => s.lights === false);

  await page.getByRole('switch', { name: 'Abluft' }).click();
  await until(page, (s) => s.exhaust === true);
  await page.getByRole('switch', { name: 'Abluft' }).click();
  await until(page, (s) => s.exhaust === false);

  await shot(page, 'steuerung-hell');
  await page.getByTestId('m-park').click();
  await expect(page.getByRole('dialog')).toContainText('Kopf parken');
  await confirmGo(page);
  await until(page, (s) => s.position[0] === 0 && s.position[1] === 0);
});

test('Bettkarte messen und Stand zeigen', async ({ page }) => {
  await open(page, 'maschine', 'Kalibrieren');
  await page.getByTestId('kal-bett').click();
  await expect(page.getByTestId('kal-detail')).toContainText('Noch nicht gemessen');
  await page.getByTestId('bed-measure').click();
  await expect(page.getByRole('dialog')).toContainText('Bett frei räumen');
  await cancelGo(page);
  await page.getByTestId('bed-measure').click();
  await confirmGo(page);
  await until(page, (s) => s.job?.file === 'Bettkarte' && s.job?.state === 'complete');
  await expect(page.getByTestId('bed-points')).toHaveText('6 × 6');
  await expect(page.getByTestId('bed-grid').locator('.m-bedcell')).toHaveCount(36);
  await shot(page, 'kalibrieren-bett');
  await page.getByRole('tab', { name: 'Steuerung' }).click();
  await expect(page.getByTestId('row-bedmap')).toContainText('6 × 6');
  await page.getByTestId('m-bedmap-clear').click();
  await page.getByRole('dialog').getByRole('button', { name: 'Löschen' }).click();
  await until(page, (s) => s.bed_map == null);
  await expect(page.getByTestId('row-bedmap')).toContainText('Noch nicht gemessen');
});

test('Bewegung testen und speichern', async ({ page }) => {
  await open(page, 'maschine', 'Kalibrieren');
  await page.request.post('/api/action', form('moveto', { x: '180', y: '180' }));
  await page.getByTestId('kal-bewegung').click();
  await expect(page.getByTestId('motion-accel')).toContainText('Firmware');
  await page.waitForTimeout(1300); // next status poll knows the new head position
  await page.getByLabel('Beschleunigung').fill('1500'); await page.getByLabel('Beschleunigung').blur();
  await page.getByTestId('motion-test').click();
  await expect(page.getByRole('dialog')).toContainText('1500 mm/s²');
  await cancelGo(page);
  await page.getByTestId('motion-test').click();
  await confirmGo(page);
  await expect(page.locator('.toast').last()).toContainText('Testfahrt', { timeout: 15000 });
  await page.getByTestId('motion-save').click();
  await page.getByRole('dialog').getByRole('button', { name: 'Speichern' }).click();
  await until(page, (s) => s.config?.motion?.accel === 1500);
  await expect(page.getByTestId('motion-accel')).toContainText('1.500');
  await shot(page, 'kalibrieren-bewegung');
  await page.getByTestId('motion-reset').click();
  await until(page, (s) => s.config?.motion?.accel == null);
});

test('Materialtest: jede Sperre erklärt, Freigabe geht durch den Go-Dialog', async ({ page }) => {
  await page.request.put('/api/workspace', { data: { material: null } });
  await open(page, 'maschine', 'Kalibrieren');
  await page.getByTestId('kal-material').click();
  await expect(page.getByTestId('matcal-start')).toHaveAttribute('data-lock', /Kamera nicht kalibriert/);
  // calibration from the app stored on the Pi (dot grid model)
  const cal = await (await page.request.get('/api/camera/calibration')).json();
  const put = await page.request.put('/api/camera/calibration', { data: { revision: cal.revision, calibrated: true, updated_by: 'Test',
    android: { photoWidth: 1280, photoHeight: 720, scanZ: 31, aboveSurface: 31, lens: { cx: 640, cy: 360, f: 900, k1: 0, k2: 0, rmsMm: 0.12, g: [1, 0, 0, 0, 1, 0, 0, 0, 1] } } } });
  expect(put.ok()).toBe(true);
  await page.reload();
  await page.getByRole('tab', { name: 'Kalibrieren' }).click();
  await page.getByTestId('kal-material').click();
  await expect(page.getByTestId('matcal-start')).toHaveAttribute('data-lock', /Kein Material gewählt/);
  await page.request.put('/api/workspace', { data: { material: { name: 'Sperrholz', thickness_mm: 4 } } });
  await expect(page.getByTestId('matcal-start')).toBeEnabled({ timeout: 8000 });
  await page.getByRole('radio', { name: 'Schnitt' }).click();
  await expect(page.getByTestId('matcal-start')).toHaveAttribute('data-lock', /hochlegen/);
  await page.getByRole('radio', { name: 'Gravur' }).click();
  await page.getByTestId('matcal-start').click();
  const dlg = page.getByRole('dialog');
  await expect(dlg).toContainText('Sperrholz');
  await expect(dlg.getByText('Brille auf')).toBeVisible();
  await expect(dlg.getByTestId('go-confirm')).toHaveText('Lasern');
  await shot(page, 'go-laser');
  await cancelGo(page);
  expect((await status(page)).material_calibration).toBeNull();
  // the go really starts it: the Pi either runs it (and the outcome shows) or refuses in a sentence
  await page.getByTestId('matcal-start').click();
  await confirmGo(page);
  await expect(page.getByTestId('matcal-last').or(page.locator('.toast-bad'))).toBeVisible({ timeout: 15000 });
  await until(page, (s) => !['probing', 'running'].includes(s.job?.state));
  await page.waitForTimeout(1200);
  await shot(page, 'kalibrieren-materialtest');
  await page.request.put('/api/workspace', { data: { material: null } });
});

test('Einstellwerte eintragen löscht die Oberfläche und wird angezeigt', async ({ page }) => {
  await open(page, 'maschine', 'Kalibrieren');
  await page.getByTestId('kal-fokus').click();
  await page.getByTestId('focus-edit').click();
  await page.getByLabel('Fokusabstand').fill('12,5'); await page.getByLabel('Fokusabstand').blur();
  await page.getByTestId('settings-save').click();
  await until(page, (s) => s.config?.focus_gap_mm === 12.5);
  await expect(page.getByTestId('kal-detail')).toContainText('12,5 mm');
});

test('Kamera: Live-Vorschau läuft, stoppt mit dem Reiter, Einstellungen gehen an den Pi', async ({ page }) => {
  let snaps = 0;
  page.on('request', (r) => { if (r.url().includes('/api/camera/snapshot')) snaps++; });
  await open(page, 'maschine', 'Kamera');
  await expect(page.getByTestId('cam-image')).toBeVisible({ timeout: 10000 });
  await expect.poll(() => snaps, { timeout: 8000 }).toBeGreaterThan(2);
  // Das Bild wird laufend getauscht: warten, bis ein fertig dekodiertes da ist.
  await expect.poll(() => page.getByTestId('cam-image').evaluate((i: HTMLImageElement) => [i.naturalWidth, i.naturalHeight]), { timeout: 8000 }).toEqual([1280, 720]);
  await shot(page, 'kamera-hell');

  await page.getByTestId('cam-exp-auto').getByRole('checkbox').uncheck();
  await expect.poll(async () => (await (await page.request.get('/api/camera/settings')).json()).exposure).not.toBeNull();
  await page.getByTestId('cam-wb-auto').getByRole('checkbox').uncheck();
  await expect.poll(async () => (await (await page.request.get('/api/camera/settings')).json()).white_balance).toBe(4500);
  await shot(page, 'kamera-fest');
  await page.getByTestId('cam-exp-auto').getByRole('checkbox').check();
  await page.getByTestId('cam-wb-auto').getByRole('checkbox').check();
  await expect.poll(async () => (await (await page.request.get('/api/camera/settings')).json()).white_balance).toBeNull();

  await page.getByTestId('cam-pause').click();
  await page.waitForTimeout(700);
  let held = snaps;
  await page.waitForTimeout(900);
  expect(snaps).toBe(held);
  await page.getByTestId('cam-pause').click();
  await expect.poll(() => snaps, { timeout: 5000 }).toBeGreaterThan(held);

  await page.getByRole('tab', { name: 'Steuerung' }).click();
  await page.waitForTimeout(700);
  held = snaps;
  await page.waitForTimeout(900);
  expect(snaps).toBe(held);
});

test('Kamera: ohne Kamera, mit Fehler und während eines Auftrags', async ({ page }) => {
  let snaps = 0;
  page.on('request', (r) => { if (r.url().includes('/api/camera/snapshot')) snaps++; });
  await page.route('**/api/status', async (route) => {
    const res = await route.fetch(); const j = await res.json();
    j.camera = { available: false, device: '/dev/video0' };
    await route.fulfill({ response: res, json: j });
  });
  await open(page, 'maschine', 'Kamera');
  await expect(page.getByTestId('cam-preview')).toContainText('Keine Kamera am Pi');
  await page.waitForTimeout(800);
  expect(snaps).toBe(0);
  await shot(page, 'kamera-keine');
  await page.unroute('**/api/status');

  await page.route('**/api/camera/snapshot*', (route) => route.fulfill({ status: 503, json: { error: 'Kamera antwortet nicht.' } }));
  await expect(page.getByTestId('cam-preview')).toContainText('Kamera antwortet nicht', { timeout: 8000 });
  await page.unroute('**/api/camera/snapshot*');
  await expect(page.getByTestId('cam-image')).toBeVisible({ timeout: 8000 });

  await page.route('**/api/status', async (route) => {
    const res = await route.fetch(); const j = await res.json();
    j.job = { state: 'running', file: 'a.gcode', line: 1, total: 9 };
    await route.fulfill({ response: res, json: j });
  });
  await expect(page.locator('.m-preview-foot')).toContainText('Ruht', { timeout: 5000 });
  await page.waitForTimeout(500);
  const held = snaps;
  await page.waitForTimeout(800);
  expect(snaps).toBe(held);
});

test('Scan vom Pi wird angezeigt', async ({ page }) => {
  await open(page, 'maschine', 'Kamera');
  await expect(page.getByTestId('cam-scan')).toContainText('noch kein Scan');
  const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==', 'base64');
  const r = await page.request.put('/api/workspace/scan', { data: png, headers: { 'Content-Type': 'image/png' } });
  expect(r.ok()).toBe(true);
  await expect(page.getByTestId('cam-scan-image')).toBeVisible({ timeout: 8000 });
});

test('Not-Aus sperrt alles, Quittieren gibt frei, danach neu referenzieren', async ({ page }) => {
  await open(page, 'maschine', 'Steuerung');
  await expect(page.getByTestId('jog-up')).toBeEnabled();
  await page.getByTestId('estop').click();
  await expect(page.getByTestId('m-headline')).toHaveText('Not-Aus aktiv');
  await expect(page.getByTestId('jog-up')).toBeDisabled();
  await expect(page.getByTestId('m-home')).toHaveAttribute('data-lock', /Not-Aus/);
  await expect(page.getByTestId('m-park')).toHaveAttribute('data-lock', /Not-Aus/);
  await expect(page.getByRole('switch', { name: 'Licht' })).toBeDisabled();
  await expect(page.getByRole('switch', { name: 'Abluft' })).toBeDisabled();
  await shot(page, 'steuerung-notaus');
  await page.getByTestId('m-estop-reset').click();
  await until(page, (s) => s.emergency_latched === false);
  await expect(page.getByTestId('m-headline')).toHaveText('Nicht referenziert');
  await expect(page.getByTestId('jog-up')).toBeDisabled();
  await page.getByTestId('m-home-next').click();
  await confirmGo(page);
  await until(page, (s) => s.homed === true);
});

test('LightBurn, fehlende Freigabe und kein Pi sperren und sagen es', async ({ page }) => {
  await open(page, 'maschine', 'Steuerung');
  await expect(page.getByTestId('m-headline')).toHaveText(/Bereit/);
  await page.route('**/api/status', async (route) => {
    const res = await route.fetch(); const j = await res.json();
    j.owner = 'lightburn';
    await route.fulfill({ response: res, json: j });
  });
  await expect(page.getByTestId('m-headline')).toHaveText('LightBurn verbunden');
  await expect(page.getByTestId('jog-up')).toBeDisabled();
  await expect(page.getByTestId('m-park')).toHaveAttribute('data-lock', /LightBurn/);
  await page.unroute('**/api/status');
  await page.route('**/api/status', async (route) => {
    const res = await route.fetch(); const j = await res.json();
    j.config.validated = false; j.homed = false;
    await route.fulfill({ response: res, json: j });
  });
  await expect(page.getByTestId('m-home')).toHaveAttribute('data-lock', /freigegeben/);
  await page.unroute('**/api/status');
  await page.route('**/api/status', (route) => route.abort());
  await expect(page.getByTestId('m-headline')).toHaveText('Pi nicht erreichbar', { timeout: 8000 });
  await expect(page.getByTestId('m-home')).toHaveAttribute('data-lock', /nicht erreichbar/);
  await shot(page, 'steuerung-offline');
});

test('System zeigt Firmware, Pi, Freigabe und lädt die Sicherung', async ({ page }) => {
  await open(page, 'maschine', 'System');
  await expect(page.getByTestId('sys-firmware')).toContainText('LumaCut CNC');
  await expect(page.getByTestId('sys-mechanik')).toContainText('freigegeben');
  await expect(page.getByTestId('sys-pi')).toContainText('Freier Speicher');
  const dl = page.waitForEvent('download');
  await page.getByTestId('sys-backup').click();
  const file = await dl;
  expect(file.suggestedFilename()).toMatch(/^lumacut-sicherung-\d{4}-\d\d-\d\d\.json$/);
  await shot(page, 'system-hell');
});

for (const theme of ['light', 'dark'] as const) {
  for (const [w, h] of [[1000, 640], [1280, 720], [1440, 900], [2560, 1440]] as const) {
    test(`Aussehen ${theme} ${w}x${h}`, async ({ page }) => {
      await page.setViewportSize({ width: w, height: h });
      await open(page, 'maschine', undefined, theme);
      const tag = `${theme}-${w}`;
      for (const t of ['Steuerung', 'Kamera', 'Kalibrieren', 'System']) {
        await page.getByRole('tab', { name: t }).click();
        await page.waitForTimeout(t === 'Kamera' ? 900 : 300);
        await page.screenshot({ path: `${SHOTS}/maschine-${t.toLowerCase()}-${tag}.png` });
        const over = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth || document.documentElement.scrollHeight > innerHeight);
        expect(over).toBe(false);
      }
    });
  }
}
