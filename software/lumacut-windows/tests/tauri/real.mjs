// Drives the REAL app window (Tauri + WebView2), not a browser: fonts, IPC, CSP, workers, file paths.
// Always against the simulator (LUMACUT_PI_URL). Usage: node tests/tauri/real.mjs <path-to-exe> [sim-url]
import { spawn } from 'node:child_process';
import { mkdirSync } from 'node:fs';
import { chromium } from '@playwright/test';

const exe = process.argv[2];
const sim = process.argv[3] ?? 'http://127.0.0.1:8090';
const out = 'tests/e2e/screenshots/real';
mkdirSync(out, { recursive: true });
const app = spawn(exe, [], { env: { ...process.env, LUMACUT_PI_URL: sim, WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS: '--remote-debugging-port=9333' }, stdio: 'ignore' });
let exited = null;
app.on('exit', (code) => { exited = code; });
app.on('error', (e) => { exited = String(e); });
const fails = [];
const check = (name, ok, extra = '') => { console.log(`${ok ? 'OK  ' : 'FEHL'} ${name} ${extra}`); if (!ok) fails.push(name); };

try {
  let browser;
  let last = '';
  for (let i = 0; i < 120 && !browser && exited === null; i++) {
    try { browser = await chromium.connectOverCDP('http://127.0.0.1:9333'); } catch (e) { last = String(e).slice(0, 300); await new Promise((r) => setTimeout(r, 500)); }
  }
  if (!browser) throw new Error(`App-Fenster nicht erreichbar, Prozess-Ende: ${exited}, zuletzt: ${last}`);
  const page = browser.contexts()[0].pages()[0];
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  await page.waitForSelector('[data-testid=estop]');
  await page.waitForTimeout(2500);
  check('läuft in Tauri', await page.evaluate(() => '__TAURI_INTERNALS__' in window));
  check('Simulator verbunden über Rust', (await page.getByTestId('conn-chip').innerText()) !== 'Pi nicht erreichbar', await page.getByTestId('conn-chip').innerText());
  const size = await page.evaluate(() => [innerWidth, innerHeight]);
  console.log('Fenster', size.join('x'));

  // Motiv: draw, system fonts, job worker.
  await page.getByTestId('nav-motiv').click();
  await page.waitForTimeout(800);
  await page.screenshot({ path: `${out}/motiv-leer.png` });
  const fontCount = await page.evaluate(async () => (await window.__TAURI_INTERNALS__.invoke('list_system_fonts')).length);
  check('Systemschriften gelesen', fontCount > 20, String(fontCount));
  const canvas = page.locator('canvas').first();
  const b = await canvas.boundingBox();
  await page.keyboard.press('r');
  await page.mouse.move(b.x + b.width * 0.3, b.y + b.height * 0.35);
  await page.mouse.down();
  await page.mouse.move(b.x + b.width * 0.55, b.y + b.height * 0.6, { steps: 6 });
  await page.mouse.up();
  await page.waitForTimeout(300);
  await page.keyboard.press('t');
  await page.mouse.click(b.x + b.width * 0.35, b.y + b.height * 0.45);
  await page.keyboard.type('LumaCut');
  await page.waitForTimeout(600);
  check('Text direkt getippt', (await page.getByTestId('text-input').inputValue()) === 'LumaCut', await page.getByTestId('text-input').inputValue());
  await page.keyboard.press('Escape');
  await page.waitForTimeout(600);
  await page.screenshot({ path: `${out}/motiv-text.png` });

  // Starten: real worker build, preview.
  await page.getByTestId('nav-start').click();
  await page.waitForTimeout(2500);
  await page.screenshot({ path: `${out}/starten.png` });
  const body = await page.locator('.main').innerText();
  check('Auftrag im Worker gebaut', /Laserweg/.test(body));

  for (const v of ['maschine', 'material', 'werkstatt', 'platine', 'einstellungen']) {
    await page.getByTestId(`nav-${v}`).click();
    await page.waitForTimeout(900);
    await page.screenshot({ path: `${out}/${v}.png` });
  }
  await page.getByTestId('nav-maschine').click();
  await page.waitForTimeout(500);
  await page.getByRole('tab', { name: 'Kamera' }).click();
  await page.waitForTimeout(1500);
  await page.screenshot({ path: `${out}/kamera.png` });

  // Go dialog appears, cancel; NOT-AUS through Rust.
  await page.getByRole('tab', { name: 'Steuerung' }).click();
  await page.getByTestId('m-home').click();
  await page.waitForTimeout(400);
  check('Go-Dialog vor der Referenzfahrt', await page.getByTestId('go-confirm').isVisible());
  await page.screenshot({ path: `${out}/go.png` });
  await page.keyboard.press('Escape');
  await page.getByTestId('estop').click();
  await page.waitForTimeout(1500);
  check('NOT-AUS erreicht den Simulator', /Not-Aus/.test(await page.getByTestId('conn-chip').innerText()));
  check('Keine Fehler in der Konsole', errors.length === 0, errors.slice(0, 5).join(' | '));
  await browser.close();
} catch (e) {
  fails.push(String(e)); console.log('FEHL', e);
} finally {
  app.kill();
}
console.log(fails.length ? `FEHLER: ${fails.length}` : 'ALLES OK');
process.exit(fails.length ? 1 : 0);
