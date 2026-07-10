import { test, expect } from '@playwright/test';
import * as fs from 'fs';
test.setTimeout(8000);                       // refusals must be fast, not 90s of timeout
test('proofrun', async ({ page }) => {
  const observed: string[] = [];
  page.on('pageerror', e => observed.push(String(e?.message ?? e)));
  page.on('console', m => { if (m.type() === 'error') observed.push(m.text()); });
  try {
    await page.goto('__ROUTE__');
    await expect(page.getByText('__EXPECTED__')).toBeVisible({ timeout: 4000 });
  } finally {
    fs.writeFileSync('/tmp/proofrun_observed.json', JSON.stringify(observed));
  }
});
