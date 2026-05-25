/**
 * Auth setup: создаёт JWT cookie для тестов.
 * Использует dev-login (доступен на localhost) или API token.
 *
 * Для продакшн-тестов: задать E2E_AUTH_COOKIE=<jwt_value> в env
 */
import { test as setup, expect } from '@playwright/test'

const AUTH_FILE = 'e2e/.auth/user.json'

setup('authenticate', async ({ page, baseURL }) => {
  const authCookie = process.env.E2E_AUTH_COOKIE

  if (authCookie) {
    // Прямая установка cookie (для CI/продакшн)
    const domain = new URL(baseURL).hostname
    await page.context().addCookies([{
      name: 'access_token',
      value: authCookie,
      domain,
      path: '/',
      httpOnly: true,
      secure: baseURL.startsWith('https'),
      sameSite: 'Lax',
    }])
    await page.goto('/')
    await expect(page.locator('text=Новое дело')).toBeVisible({ timeout: 10_000 })
  } else {
    // Dev-login (только на localhost)
    await page.goto('/login')
    const devButton = page.locator('button:has-text("Dev Login"), button:has-text("Тестовый вход")')
    if (await devButton.isVisible({ timeout: 3_000 }).catch(() => false)) {
      await devButton.click()
      await expect(page.locator('text=Новое дело')).toBeVisible({ timeout: 10_000 })
    } else {
      throw new Error(
        'Dev login not available. Set E2E_AUTH_COOKIE env var for production testing.\n' +
        'Get cookie: docker compose exec db psql -U judge -d ai_judge -c "SELECT ... FROM users LIMIT 1"'
      )
    }
  }

  await page.context().storageState({ path: AUTH_FILE })
})
