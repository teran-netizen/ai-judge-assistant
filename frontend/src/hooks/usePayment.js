import { useState, useRef } from 'react'
import { ymGoal } from '../ym'
import api from '../api'

const GOAL_MAP = {
  single_case: 'purchase_single_case',
  subscription_monthly: 'purchase_subscription',
}

/**
 * Shared payment hook — eliminates duplicated handleBuy logic
 * across PaywallModal and UpsellModal.
 */
export default function usePayment(returnUrl = '') {
  const [loading, setLoading] = useState(null)
  const [error, setError] = useState(null)
  const lastClickRef = useRef(0)

  const handleBuy = async (packageType) => {
    // Debounce: ignore clicks within 3 seconds
    const now = Date.now()
    if (now - lastClickRef.current < 10000) return
    lastClickRef.current = now

    if (loading) return
    setLoading(packageType)
    setError(null)
    ymGoal(GOAL_MAP[packageType] || 'purchase_case_unknown')
    api.trackAction('click_buy', packageType)
    try {
      const result = await api.purchaseAttempt(packageType, returnUrl)
      if (result.payment_url) {
        api.trackAction('payment_redirect', packageType)
        window.location.href = result.payment_url
        return
      }
      // No payment_url — Tochka error
      setError(result.message || 'Оплата временно недоступна')
      setLoading(null)
    } catch {
      setError('Ошибка соединения. Попробуйте позже.')
      setLoading(null)
    }
  }

  return { handleBuy, loading, error }
}
