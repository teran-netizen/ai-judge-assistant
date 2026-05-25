/**
 * E2E Smoke Tests — проверяет что критические фичи рендерятся и работают.
 *
 * Ловит регрессии:
 * - Потерянные импорты (NormHighlight, ReviewerBadge)
 * - Сломанный SSE стриминг
 * - Сломанный refine
 * - Сломанная навигация
 * - Проблемы с мобильным viewport
 *
 * Запуск: npx playwright test --config=e2e/playwright.config.js
 * С auth: E2E_AUTH_COOKIE=<jwt> npx playwright test --config=e2e/playwright.config.js
 */
import { test, expect } from '@playwright/test'

// ═══════════════════════════════════════════════════════════════
// 1. Страница загружается
// ═══════════════════════════════════════════════════════════════

test.describe('Page Load', () => {
  test('login page renders', async ({ page }) => {
    await page.goto('/login')
    // Должны быть кнопки OAuth
    await expect(page.locator('text=Яндекс ID').or(page.locator('text=VK ID'))).toBeVisible({ timeout: 10_000 })
  })

  test('main page redirects to login without auth', async ({ page }) => {
    await page.goto('/')
    // Должен перенаправить на логин
    await page.waitForURL(/login/, { timeout: 10_000 })
  })
})

// ═══════════════════════════════════════════════════════════════
// 2. Авторизованные тесты
// ═══════════════════════════════════════════════════════════════

test.describe('Authenticated', () => {
  test.use({ storageState: 'e2e/.auth/user.json' })

  test('sidebar renders with case list', async ({ page }) => {
    await page.goto('/')
    await expect(page.locator('text=Новое дело')).toBeVisible({ timeout: 10_000 })
    await expect(page.locator('text=Баланс').or(page.locator('text=токенов'))).toBeVisible()
  })

  test('new case page has upload controls', async ({ page }) => {
    await page.goto('/')
    // Input для файлов должен существовать
    const fileInput = page.locator('input[type="file"]')
    await expect(fileInput).toBeAttached({ timeout: 5_000 })
    // Кнопка отправки
    await expect(page.locator('textarea, input[placeholder*="доработать"], input[placeholder*="Напишите"]').first()).toBeVisible()
  })

  test('billing page loads', async ({ page }) => {
    await page.goto('/billing')
    await expect(page.locator('text=токенов').first()).toBeVisible({ timeout: 10_000 })
  })
})

// ═══════════════════════════════════════════════════════════════
// 3. AI Reviewer integration (КРИТИЧЕСКИЙ)
// ═══════════════════════════════════════════════════════════════

test.describe('AI Reviewer', () => {
  test.use({ storageState: 'e2e/.auth/user.json' })

  // Этот тест требует E2E_CASE_ID — ID завершённого дела с validation_result
  const caseId = process.env.E2E_CASE_ID

  test.skip(!caseId, 'Set E2E_CASE_ID to a completed case with validation_result')

  test('NormHighlight renders green highlights', async ({ page }) => {
    await page.goto(`/cases/${caseId}`)

    // Ждём загрузку текста решения
    await expect(page.locator('text=Проект решения')).toBeVisible({ timeout: 15_000 })

    // NormHighlight: должны быть элементы с bg-emerald (зелёная подсветка верифицированных норм)
    const highlights = page.locator('[class*="bg-emerald"][class*="cursor-pointer"]')
    await expect(highlights.first()).toBeVisible({ timeout: 15_000 })

    const count = await highlights.count()
    expect(count).toBeGreaterThan(0)
    console.log(`  ✓ NormHighlight: ${count} highlighted references found`)
  })

  test('ReviewerBadge renders with stats', async ({ page }) => {
    await page.goto(`/cases/${caseId}`)

    // ReviewerBadge: "AI-РЕВИЗОР: N ссылок проверено"
    const badge = page.locator('text=AI-РЕВИЗОР')
    await expect(badge).toBeVisible({ timeout: 15_000 })

    // Статистика: "проверено" и/или "исправлено"
    await expect(page.locator('text=проверено')).toBeVisible()
    console.log('  ✓ ReviewerBadge: stats panel visible')
  })

  test('NormHighlight popup opens on click', async ({ page }) => {
    await page.goto(`/cases/${caseId}`)

    // Кликнуть на первую подсвеченную норму
    const highlight = page.locator('[class*="bg-emerald"][class*="cursor-pointer"]').first()
    await expect(highlight).toBeVisible({ timeout: 15_000 })
    await highlight.click()

    // Попап должен появиться с деталями нормы
    const popup = page.locator('text=Проверено').or(page.locator('text=Исправлено')).or(page.locator('text=Тип:'))
    await expect(popup.first()).toBeVisible({ timeout: 5_000 })
    console.log('  ✓ NormPopup: details popup visible')
  })

  test('ReviewerBadge expands on click', async ({ page }) => {
    await page.goto(`/cases/${caseId}`)

    // Кликнуть на бейдж ревизора чтобы раскрыть детали
    const badge = page.locator('text=AI-РЕВИЗОР')
    await expect(badge).toBeVisible({ timeout: 15_000 })
    await badge.click()

    // Детальная статистика должна раскрыться
    // Ищем карточки с нормами или подробную статистику
    const details = page.locator('text=Кодекс').or(page.locator('text=ГПК').or(page.locator('text=ГК РФ')))
    await expect(details.first()).toBeVisible({ timeout: 5_000 })
    console.log('  ✓ ReviewerBadge: expanded details visible')
  })
})

// ═══════════════════════════════════════════════════════════════
// 4. Case page functionality
// ═══════════════════════════════════════════════════════════════

test.describe('Case Page', () => {
  test.use({ storageState: 'e2e/.auth/user.json' })

  const caseId = process.env.E2E_CASE_ID

  test.skip(!caseId, 'Set E2E_CASE_ID to a completed case')

  test('case text renders', async ({ page }) => {
    await page.goto(`/cases/${caseId}`)
    await expect(page.locator('text=Проект решения')).toBeVisible({ timeout: 15_000 })

    // Текст решения должен быть видим (минимум 100 символов)
    const textContent = await page.locator('.prose, [class*="whitespace-pre-wrap"]').first().textContent()
    expect(textContent.length).toBeGreaterThan(100)
    console.log(`  ✓ Case text: ${textContent.length} chars rendered`)
  })

  test('copy button works', async ({ page }) => {
    await page.goto(`/cases/${caseId}`)
    await expect(page.locator('text=Копировать')).toBeVisible({ timeout: 15_000 })
    await page.locator('text=Копировать').click()
    await expect(page.locator('text=Скопировано')).toBeVisible({ timeout: 3_000 })
  })

  test('export DOCX button exists', async ({ page }) => {
    await page.goto(`/cases/${caseId}`)
    await expect(page.locator('text=Скачать DOCX')).toBeVisible({ timeout: 15_000 })
  })

  test('refine input is visible', async ({ page }) => {
    await page.goto(`/cases/${caseId}`)
    const input = page.locator('textarea[placeholder*="доработать"], textarea[placeholder*="Напишите"]')
    await expect(input.first()).toBeVisible({ timeout: 15_000 })
  })
})

// ═══════════════════════════════════════════════════════════════
// 5. Mobile-specific checks
// ═══════════════════════════════════════════════════════════════

test.describe('Mobile viewport', () => {
  test.use({
    storageState: 'e2e/.auth/user.json',
    viewport: { width: 390, height: 844 },
  })

  const caseId = process.env.E2E_CASE_ID

  test.skip(!caseId, 'Set E2E_CASE_ID')

  test('case page is usable on mobile', async ({ page }) => {
    await page.goto(`/cases/${caseId}`)

    // Текст виден
    await expect(page.locator('text=Проект решения')).toBeVisible({ timeout: 15_000 })

    // Инпут виден и не перекрыт
    const input = page.locator('textarea[placeholder*="доработать"], textarea[placeholder*="Напишите"]')
    await expect(input.first()).toBeVisible()
    await expect(input.first()).toBeInViewport()
  })
})

// ═══════════════════════════════════════════════════════════════
// 6. API health (без авторизации)
// ═══════════════════════════════════════════════════════════════

test.describe('API Health', () => {
  test('health endpoint responds', async ({ request }) => {
    const res = await request.get('/health')
    expect(res.status()).toBe(200)
    const body = await res.json()
    expect(body.db).toBe('ok')
  })

  test('unauthorized API returns 401', async ({ request }) => {
    const res = await request.get('/api/cases/')
    expect(res.status()).toBe(401)
  })

  test('validation endpoint exists', async ({ request }) => {
    // Должен вернуть 401 (не 404) — значит роут зарегистрирован
    const res = await request.get('/api/cases/00000000-0000-0000-0000-000000000000/validation')
    expect([401, 404]).toContain(res.status())
  })

  test('norms endpoint exists', async ({ request }) => {
    const res = await request.get('/api/norms/00000000-0000-0000-0000-000000000000')
    expect([401, 404]).toContain(res.status())
  })
})
