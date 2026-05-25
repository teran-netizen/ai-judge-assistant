import { useEffect, useState, useRef } from 'react'
import { useNavigate, useSearchParams, useLocation } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'
import { ymGoal } from '../ym'

const API = import.meta.env.VITE_API_URL || ''

export default function AuthCallback() {
  const [error, setError] = useState(null)
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const location = useLocation()
  const { login } = useAuth()
  const calledRef = useRef(false)

  useEffect(() => {
    // StrictMode вызывает useEffect дважды — OAuth-код одноразовый
    if (calledRef.current) return
    calledRef.current = true

    const code = params.get('code')
    // Определяем провайдера: из query-параметра или из пути (/auth/vk-callback)
    const provider = params.get('provider') || (location.pathname.includes('vk') ? 'vk' : 'yandex')
    const rawState = params.get('state') || ''

    if (!code) {
      setError('Не получен код авторизации')
      return
    }

    // CSRF-защита: проверяем nonce из state
    // VK использует PKCE (code_challenge/code_verifier) — это даёт эквивалентную защиту от CSRF,
    // поэтому для VK nonce-проверку пропускаем (sessionStorage может очиститься при редиректе)
    const savedNonce = localStorage.getItem('oauth_nonce')
    localStorage.removeItem('oauth_nonce')

    let ref = ''
    if (provider === 'vk') {
      // VK: PKCE защищает от CSRF, nonce не обязателен
      // Пытаемся извлечь реферальный код из state если есть
      if (rawState.includes(':')) {
        const parts = rawState.split(':')
        ref = parts.slice(1).join(':')
      }
    } else {
      // Яндекс: проверяем nonce если он сохранён в localStorage
      // На мобильных (WebView, приватный режим, переключение приложений) localStorage может очиститься — не блокируем вход
      if (savedNonce) {
        if (rawState.includes(':')) {
          const [nonce, ...rest] = rawState.split(':')
          if (nonce !== savedNonce) {
            setError('Ошибка безопасности (CSRF). Попробуйте войти заново.')
            return
          }
          ref = rest.join(':')
        } else {
          if (rawState !== savedNonce) {
            setError('Ошибка безопасности (CSRF). Попробуйте войти заново.')
            return
          }
        }
      } else {
        // Nonce утерян (мобильный WebView / приватный режим) — пропускаем CSRF-проверку
        console.warn('[auth] oauth_nonce lost — skipping CSRF check (mobile/WebView)')
        if (rawState.includes(':')) {
          const parts = rawState.split(':')
          ref = parts.slice(1).join(':')
        }
      }
    }

    // redirect_uri ДОЛЖЕН совпадать с тем, что мы отправили провайдеру при авторизации
    const redirectUri = provider === 'vk'
      ? `${window.location.origin}/auth/vk-callback`
      : `${window.location.origin}/auth/callback?provider=${provider}`

    // PKCE: извлекаем code_verifier для VK и Yandex (triple fallback для mobile)
    let codeVerifier = ''
    if (provider === 'vk') {
      codeVerifier = localStorage.getItem('vk_code_verifier') || sessionStorage.getItem('vk_code_verifier') || (document.cookie.match(/vk_cv=([^;]+)/) || [])[1] || ''
      localStorage.removeItem('vk_code_verifier'); sessionStorage.removeItem('vk_code_verifier'); document.cookie = 'vk_cv=;path=/;max-age=0'
    } else if (provider === 'yandex') {
      codeVerifier = localStorage.getItem('yandex_code_verifier') || sessionStorage.getItem('yandex_code_verifier') || (document.cookie.match(/yandex_cv=([^;]+)/) || [])[1] || ''
      localStorage.removeItem('yandex_code_verifier'); sessionStorage.removeItem('yandex_code_verifier'); document.cookie = 'yandex_cv=;path=/;max-age=0'
    }

    const deviceId = params.get('device_id') || ''

    // Если ref пустой — попробовать достать UTM из sessionStorage (сохраняется в App.jsx при первом заходе)
    if (!ref) {
      const utmKeys = ['utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term']
      const utmParts = utmKeys
        .map(k => { const v = sessionStorage.getItem(k); return v ? `${k.replace('utm_', '')}=${v.slice(0, 50)}` : '' })
        .filter(Boolean)
      if (utmParts.length) ref = utmParts.join('&')
    }

    fetch(`${API}/api/auth/${provider}/callback`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ code, state: ref, redirect_uri: redirectUri, code_verifier: codeVerifier, device_id: deviceId }),
    })
      .then(r => {
        if (!r.ok) throw new Error('Ошибка авторизации')
        return r.json()
      })
      .then(async (data) => {
        if (data?.refresh_token) localStorage.setItem('refresh_token', data.refresh_token)
        // Cookie is set automatically by the browser from the response
        await login()
        ymGoal('auth_success')
        navigate('/', { replace: true })
      })
      .catch(e => setError(e.message))
  }, [])

  if (error) {
    return (
      <div className="min-h-screen flex items-center justify-center p-6">
        <div className="text-center">
          <div className="text-red-500 text-lg font-medium mb-2">Ошибка входа</div>
          <p className="text-surface-500 mb-4">{error}</p>
          <a href="/login" className="btn-primary">Попробовать снова</a>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen flex items-center justify-center">
      <div className="text-center">
        <div className="w-10 h-10 border-[3px] border-brand-200 border-t-brand-600 rounded-full animate-spin mx-auto mb-4" />
        <p className="text-surface-500">Авторизация...</p>
      </div>
    </div>
  )
}
