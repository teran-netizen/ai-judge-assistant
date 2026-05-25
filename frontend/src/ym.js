/**
 * Яндекс.Метрика — утилита для отправки целей.
 * Counter ID берётся из window._ymId (устанавливается скриптом в index.html).
 *
 * Использование:
 *   import { ymGoal } from '../ym'
 *   ymGoal('click_login_yandex')
 *   ymGoal('generate_success', { case_id: '...' })
 */

export function ymGoal(goalName, params) {
  try {
    const id = window._ymId || import.meta.env.VITE_YM_COUNTER_ID
    if (id && typeof window.ym === 'function') {
      window.ym(id, 'reachGoal', goalName, params || {})
    }
  } catch {
    // silent — метрика не должна ломать приложение
  }
}

/**
 * VK Top.Mail.Ru — отправка целей пикселя.
 * Counter ID is provided at runtime.
 */
export function tmrGoal(goalName) {
  try {
    const id = window._tmrId || import.meta.env.VITE_TMR_COUNTER_ID
    if (id && Array.isArray(window._tmr)) {
      window._tmr.push({ type: 'reachGoal', id, goal: goalName })
    }
  } catch {
    // silent
  }
}
