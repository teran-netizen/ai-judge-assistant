import { createContext, useContext, useState, useEffect, useCallback } from 'react'
import api from '../api'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)

  const fetchUser = useCallback(async () => {
    try {
      const data = await api.getMe()
      setUser(data)
    } catch {
      setUser(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchUser()
  }, [fetchUser])

  useEffect(() => {
    if (!user?.id) return
    const opId = localStorage.getItem('pending_payment_op') || ''
    const txId = localStorage.getItem('pending_payment_tx') || ''
    const ts = parseInt(localStorage.getItem('pending_payment_ts') || '0', 10)
    if (!opId && !txId) return

    // Ignore stale pending entries
    if (ts && (Date.now() - ts) > 24 * 60 * 60 * 1000) {
      localStorage.removeItem('pending_payment_op')
      localStorage.removeItem('pending_payment_tx')
      localStorage.removeItem('pending_payment_ts')
      api.clearPendingPayment?.()
      return
    }

    api.confirmPayment(opId || '', txId || '')
      .then((res) => {
        if (res?.status === 'confirmed' || res?.status === 'already_confirmed') {
          localStorage.removeItem('pending_payment_op')
          localStorage.removeItem('pending_payment_tx')
          localStorage.removeItem('pending_payment_ts')
          api.clearPendingPayment?.()
          fetchUser()
        }
      })
      .catch(() => {})
  }, [user?.id, fetchUser])

  const login = async () => {
    // Cookie is already set by the backend response — just fetch user profile
    await fetchUser()
  }

  const logout = async () => {
    try { await api.logout() } catch {}
    setUser(null)
    window.location.href = '/login'
  }

  const refreshUser = () => fetchUser()

  return (
    <AuthContext.Provider value={{ user, loading, login, logout, refreshUser }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
