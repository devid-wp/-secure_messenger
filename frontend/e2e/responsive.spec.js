import { expect, test } from '@playwright/test'

test('login remains usable at the 390px mobile baseline', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/')

  await expect(page.getByRole('button', { name: 'Sign in' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Create account' })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()
})
