import { test, expect } from '@playwright/test';

const views = ['material', 'motiv', 'start', 'platine', 'werkstatt', 'maschine', 'einstellungen'];

for (const theme of ['light', 'dark'] as const) {
  test(`alle Bereiche ${theme}`, async ({ page }) => {
    await page.addInitScript((t) => localStorage.setItem('lc.theme', JSON.stringify(t)), theme);
    await page.goto('/');
    await expect(page.getByTestId('estop')).toBeVisible();
    for (const v of views) {
      await page.getByTestId(`nav-${v}`).click();
      await page.waitForTimeout(600);
      await page.screenshot({ path: `tests/e2e/screenshots/${v}-${theme}.png` });
    }
  });
}
