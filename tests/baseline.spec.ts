import { test, expect } from '@playwright/test';

test('home renders', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'ProofRun Demo Shop' })).toBeVisible();
});

test('healthy cart shows the total', async ({ page }) => {
  await page.goto('/cart?fixture=ok');
  await expect(page.getByText('Total: $42.00')).toBeVisible();
});

test('layout-shift page renders its button', async ({ page }) => {
  await page.goto('/cart?fixture=layout-shift');
  await expect(page.getByRole('button', { name: 'Pay now' })).toBeAttached();
});
