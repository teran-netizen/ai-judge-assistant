/**
 * Хук для загрузки данных нормы из API.
 * Кеширует результаты в памяти сессии.
 *
 * Используется в NormHighlight (попап) и ReviewerBadge (карточка исправления).
 */
import { useState, useEffect } from 'react'

const API = import.meta.env.VITE_API_URL || ''

// Кеш в памяти сессии — не перезапрашиваем одну норму дважды
const cache = {}

export default function useNormData(normId) {
  const [data, setData] = useState(cache[normId] || null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!normId) return
    if (cache[normId]) {
      setData(cache[normId])
      return
    }

    setLoading(true)
    fetch(`${API}/api/norms/${normId}`, { credentials: 'include' })
      .then(r => r.ok ? r.json() : null)
      .then(result => {
        if (result) {
          cache[normId] = result
          setData(result)
        }
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [normId])

  return { data, loading }
}
