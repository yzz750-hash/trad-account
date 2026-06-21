import { test, expect } from '@playwright/test';

test.describe('Voucher Workflow', () => {
  test.beforeEach(async ({ page }) => {
    // Login before each test
    await page.goto('/login');
    await page.fill('#username', 'admin');
    await page.fill('#password', 'admin123');
    await page.click('button[type="submit"]');
    // Wait for redirect to home
    await page.waitForURL('**/');
  });

  test('voucher list page loads after login', async ({ page }) => {
    await page.goto('/voucher');
    await expect(page).toHaveURL(/\/voucher/);
    // The page should show the voucher list header or filter bar
    await expect(page.locator('text=凭证').first()).toBeVisible({ timeout: 10000 });
  });

  test('voucher page shows filter bar', async ({ page }) => {
    await page.goto('/voucher');
    // VoucherFilterBar should render with date inputs
    await expect(page.locator('input[type="date"]').first()).toBeVisible({ timeout: 10000 });
  });

  test('reports page loads and shows tab navigation', async ({ page }) => {
    await page.goto('/reports');
    await expect(page).toHaveURL(/\/reports/);
    // Tab navigation should be visible
    await expect(page.locator('text=资产负债表').first()).toBeVisible({ timeout: 10000 });
    await expect(page.locator('text=利润表').first()).toBeVisible({ timeout: 10000 });
  });

  test('balance sheet tab loads report data', async ({ page }) => {
    await page.goto('/reports');
    // Click balance sheet tab (already active by default)
    // Wait for the query button or auto-load
    const queryButton = page.locator('button:has-text(查询)').first();
    if (await queryButton.isVisible({ timeout: 5000 }).catch(() => false)) {
      await queryButton.click();
    }
    // After loading, should see either data or empty state
    await page.waitForTimeout(3000);
    // Should not show error state
    await expect(page.locator('text=加载失败')).toHaveCount(0);
  });

  test('income statement tab switches and loads', async ({ page }) => {
    await page.goto('/reports');
    // Click income statement tab
    await page.locator('text=利润表').first().click();
    // Wait for tab content to appear
    await page.waitForTimeout(2000);
    // Should show income statement related content
    await expect(page.locator('text=营业收入').first()).toBeVisible({ timeout: 10000 });
  });
});

test.describe('Period-End Closing', () => {
  test('period-end page loads', async ({ page }) => {
    // Login
    await page.goto('/login');
    await page.fill('#username', 'admin');
    await page.fill('#password', 'admin123');
    await page.click('button[type="submit"]');
    await page.waitForURL('**/');

    await page.goto('/period-end');
    await expect(page).toHaveURL(/\/period-end/);
    // The page should show closing operations
    await expect(page.locator('text=期末结账').first()).toBeVisible({ timeout: 10000 });
  });
});
