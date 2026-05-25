import { useState, useEffect } from 'react'
import { ymGoal, tmrGoal } from '../ym'
import { Scale, Clock, BookOpen, Camera, Shield, Sparkles, ArrowRight, FileText, MessageSquareText, Users, BriefcaseBusiness, CheckCircle2 } from 'lucide-react'

import api from '../api'
const API = import.meta.env.VITE_API_URL || ''

// PKCE helpers для VK ID
async function generatePKCE() {
  const array = new Uint8Array(32)
  crypto.getRandomValues(array)
  const verifier = btoa(String.fromCharCode(...array))
    .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier))
  const challenge = btoa(String.fromCharCode(...new Uint8Array(digest)))
    .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
  return { verifier, challenge }
}


function EmailOTPForm() {
  const [email, setEmail] = useState('')
  const [code, setCode] = useState('')
  const [step, setStep] = useState('email')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [countdown, setCountdown] = useState(0)

  useEffect(() => {
    if (countdown > 0) {
      const t = setTimeout(() => setCountdown(c => c - 1), 1000)
      return () => clearTimeout(t)
    }
  }, [countdown])

  const handleSend = async () => {
    if (!email.trim() || loading) return
    setLoading(true); setError('')
    try {
      await api.sendOTP(email.trim().toLowerCase())
      setStep('code'); setCountdown(60)
    } catch (e) { setError(e.message || 'Ошибка') }
    finally { setLoading(false) }
  }

  const handleVerify = async () => {
    if (!code.trim() || loading) return
    setLoading(true); setError('')
    try {
      const utm = sessionStorage.getItem('utm_source') || ''
      const data = await api.verifyOTP(email.trim().toLowerCase(), code.trim(), utm || undefined)
      if (data && data.refresh_token) localStorage.setItem('refresh_token', data.refresh_token)
      window.location.href = '/'
    } catch (e) { setError(e.message || 'Неверный код') }
    finally { setLoading(false) }
  }

  if (step === 'code') {
    return (
      <div className="w-full">
        <p className="text-center text-surface-500 text-sm mb-3">
          {'Код отправлен на '}<strong>{email}</strong>
        </p>
        <div className="space-y-2 mb-3">
          <input type="text" inputMode="numeric" maxLength={6} value={code}
            onChange={e => setCode(e.target.value.replace(/[^0-9]/g, '').slice(0, 6))}
            onKeyDown={e => e.key === 'Enter' && handleVerify()}
            placeholder="000000" autoFocus
            className="w-full px-4 py-3 border-2 border-brand-500 rounded-lg text-center text-xl font-bold tracking-[4px] outline-none" />
          <button onClick={handleVerify} disabled={code.length < 6 || loading}
            className="w-full py-3 bg-brand-600 text-white font-semibold rounded-lg disabled:opacity-40 hover:bg-brand-700 transition-colors">
            {loading ? '...' : 'Войти'}
          </button>
        </div>
        <div className="text-center text-sm">
          {countdown > 0
            ? <span className="text-surface-400">{'Повторно через '}{countdown}{'с'}</span>
            : <button onClick={handleSend} disabled={loading} className="text-brand-600 hover:underline">Отправить повторно</button>}
          {' \u00b7 '}
          <button onClick={() => { setStep('email'); setCode(''); setError('') }} className="text-surface-400 hover:text-surface-600">Изменить</button>
        </div>
        {error && <p className="text-red-500 text-sm text-center mt-2">{error}</p>}
      </div>
    )
  }

  return (
    <div className="w-full">
      <div className="flex gap-2">
        <input type="email" value={email} onChange={e => setEmail(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && handleSend()}
          placeholder="Email"
          className="flex-1 px-4 py-3 border border-surface-300 rounded-lg text-base outline-none focus:border-brand-500 transition-colors" />
        <button onClick={handleSend} disabled={!email.trim() || loading}
          className="px-4 py-3 bg-brand-600 text-white rounded-lg disabled:opacity-40 hover:bg-brand-700 transition-colors">
          {loading ? <span className="inline-block w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" /> : <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>}
        </button>
      </div>
      {error && <p className="text-red-500 text-sm text-center mt-2">{error}</p>}
    </div>
  )
}


function LoginButtons({ referral }) {
  const ref = /^[a-z0-9]{1,16}$/i.test(referral) ? referral : ''
  const host = window.location.hostname || ''
  const isLocalDevHost =
    host === 'localhost' ||
    host.startsWith('192.168.') ||
    host.startsWith('10.') ||
    window.location.port === '8081'
  const isDevAccessEnabled = isLocalDevHost || import.meta.env.VITE_DEV_ACCESS === '1'
  const getOAuthState = () => {
    const nonce = crypto.randomUUID()
    localStorage.setItem('oauth_nonce', nonce)
    // Capture UTM: из URL или из sessionStorage (если пришёл на / с UTM, потом перешёл на /login)
    const params = new URLSearchParams(window.location.search)
    const utmKeys = ['utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term']
    const utmParts = utmKeys
      .map(k => { const v = params.get(k) || sessionStorage.getItem(k); return v ? `${k.replace('utm_', '')}=${v.slice(0, 50)}` : '' })
      .filter(Boolean)
    const source = ref || utmParts.join('&') || ''
    return source ? `${nonce}:${source}` : nonce
  }

  return (
    <div className="space-y-3">
      <a
        href="#"
        onClick={async (e) => {
          e.preventDefault()
          const clientId = import.meta.env.VITE_YANDEX_CLIENT_ID || ''
          if (!clientId) { alert('OAuth-провайдер не настроен.'); return }
          const { verifier, challenge } = await generatePKCE()
          localStorage.setItem('yandex_code_verifier', verifier); sessionStorage.setItem('yandex_code_verifier', verifier); document.cookie = 'yandex_cv=' + verifier + ';path=/;max-age=300;SameSite=Lax'
          const redirectUri = encodeURIComponent(`${window.location.origin}/auth/callback?provider=yandex`)
          const state = encodeURIComponent(getOAuthState())
          ymGoal('click_login_yandex'); tmrGoal('click_login_yandex')
          window.location.href = `https://oauth.yandex.ru/authorize?response_type=code&client_id=${clientId}&redirect_uri=${redirectUri}&state=${state}&code_challenge=${challenge}&code_challenge_method=S256`
        }}
        className="btn w-full justify-center py-3 bg-[#fc3f1d] text-white hover:bg-[#e5371a] font-medium rounded-lg transition-all"
      >
        <svg viewBox="0 0 24 24" className="w-5 h-5 fill-current">
          <path d="M13.32 7.67h-.67c-1.55 0-2.37.82-2.37 2.04 0 1.41.56 2.08 1.75 2.95l.99.72-2.82 4.62H7.59l2.5-4.07c-1.55-1.15-2.42-2.27-2.42-4.13 0-2.5 1.72-4.13 4.98-4.13h3.03V18h-2.36V7.67z"/>
        </svg>
        Войти через Яндекс
      </a>
      <a
        href="#"
        onClick={async (e) => {
          e.preventDefault()
          const clientId = import.meta.env.VITE_VK_CLIENT_ID || ''
          if (!clientId) { alert('OAuth-провайдер не настроен.'); return }
          const { verifier, challenge } = await generatePKCE()
          localStorage.setItem('vk_code_verifier', verifier); sessionStorage.setItem('vk_code_verifier', verifier); document.cookie = 'vk_cv=' + verifier + ';path=/;max-age=300;SameSite=Lax'
          const redirectUri = encodeURIComponent(`${window.location.origin}/auth/vk-callback`)
          const state = encodeURIComponent(getOAuthState())
          ymGoal('click_login_vk'); tmrGoal('click_login_vk')
          window.location.href = `https://id.vk.com/authorize?client_id=${clientId}&redirect_uri=${redirectUri}&response_type=code&state=${state}&scope=email&code_challenge=${challenge}&code_challenge_method=s256`
        }}
        className="btn w-full justify-center py-3 bg-[#0077ff] text-white hover:bg-[#006ae6] font-medium rounded-lg transition-all"
      >
        <svg viewBox="0 0 24 24" className="w-5 h-5 fill-current">
          <path d="M12.77 18.15h1.17s.35-.04.53-.23c.17-.18.16-.5.16-.5s-.02-1.53.69-1.76c.7-.22 1.6 1.47 2.55 2.12.72.49 1.27.38 1.27.38l2.55-.04s1.33-.08.7-1.12c-.05-.08-.37-.77-1.92-2.18-1.62-1.48-1.4-1.24.55-3.79 1.19-1.56 1.66-2.5 1.51-2.91-.14-.39-1-.29-1-.29l-2.87.02s-.21-.03-.37.07c-.15.09-.25.31-.25.31s-.44 1.18-1.03 2.18c-1.25 2.12-1.75 2.23-1.95 2.1-.47-.31-.35-1.24-.35-1.9 0-2.06.31-2.92-.61-3.14-.31-.07-.53-.12-1.31-.13-.99-.01-1.83 0-2.31.24-.31.15-.56.5-.41.52.18.03.6.11.82.41.28.39.27 1.25.27 1.25s.16 2.43-.37 2.73c-.37.2-.87-.22-1.94-2.14-.55-.98-.97-2.07-.97-2.07s-.08-.2-.22-.3c-.17-.13-.41-.17-.41-.17l-2.73.02s-.41.01-.56.19c-.13.16-.01.49-.01.49s2.08 4.87 4.43 7.32c2.16 2.25 4.61 2.1 4.61 2.1z"/>
        </svg>
        Войти через VK
      </a>

      {isDevAccessEnabled && (
        <button
          onClick={async () => {
            try {
              const res = await fetch(`${API}/api/auth/dev-login`, { method: 'POST', credentials: 'include' })
              if (res.ok) window.location.href = '/'
              else alert('Dev login failed: ' + res.status)
            } catch (err) { alert('Dev login error: ' + err.message) }
          }}
          className="btn w-full justify-center py-3 mt-3 bg-yellow-500 text-black hover:bg-yellow-400 font-medium rounded-lg transition-all"
        >
          Dev-доступ
        </button>
      )}
    </div>
  )
}

/* ───────── Steps data ───────── */
const STEPS = [
  {
    img: '/img/judge-overwhelmed.webp', width: 600, height: 865,
    alt: 'Судья завален документами',
    title: 'Знакомая ситуация?',
    text: 'Стопки материалов, десятки дел. На каждое решение уходят часы кропотливой работы с нормами и судебной практикой.',
  },
  {
    img: '/img/judge-smartphone.webp', width: 600, height: 865,
    alt: 'Судья фотографирует документы',
    title: 'Сфотографируйте материалы',
    text: 'Откройте приложение, наведите камеру на исковое заявление, отзыв и доказательства. Можно загрузить PDF или DOC.',
  },
  {
    img: '/img/phone-cases.webp', width: 600, height: 557,
    alt: 'Нажмите кнопку генерации',
    title: 'Нажмите «Сгенерировать»',
    text: 'ИИ распознает текст, определит категорию спора, найдёт применимые нормы и Пленумы ВС РФ.',
  },
  {
    img: '/img/judge-computer.webp', width: 600, height: 532,
    alt: 'Судья работает с проектом решения',
    title: 'Работайте с проектом',
    text: 'Получите готовый черновик решения со ссылками на законы. Редактируйте, дополняйте, используйте как основу.',
  },
  {
    img: '/img/judge-happy.webp', width: 600, height: 799,
    alt: 'Счастливый судья',
    title: 'Всего 5 минут!',
    text: 'Фотографирование и генерация проекта решения заняли 5 минут вместо нескольких часов. Освободите время для сложных дел.',
  },
]

const AI_LAWYER_DOCUMENTS = [
  'Исковое заявление',
  'Возражение на иск',
  'Претензия',
  'Жалоба',
  'Ходатайство',
  'Апелляционная жалоба',
  'Отзыв на иск',
  'Заявление в суд',
  'Правовой разбор договора',
  'Ответ контрагенту',
  'Консультация по документу',
  'План действий по спору',
]

const AI_LAWYER_AUDIENCES = [
  {
    Icon: Users,
    title: 'Для граждан',
    text: 'Если пришел иск, штраф, постановление, отказ, претензия или непонятный договор, сервис поможет быстро понять ситуацию и подготовить первый документ.',
  },
  {
    Icon: BriefcaseBusiness,
    title: 'Для ИП и бизнеса',
    text: 'Подготовьте претензию, ответ контрагенту, жалобу, позицию по спору или разбор договора без долгого поиска шаблонов.',
  },
  {
    Icon: Scale,
    title: 'Для юристов',
    text: 'Используйте ИИ как быстрый черновик: структура документа, факты из материалов, аргументы и ссылки на правовые нормы.',
  },
]

const AI_LAWYER_STEPS = [
  {
    img: '/img/judge-smartphone.webp',
    width: 600,
    height: 865,
    alt: 'Загрузка фото юридических документов',
    title: 'Загрузите материалы',
    text: 'Подойдут фото, PDF, сканы, договоры, иски, постановления, переписка, претензии и другие документы по вашей ситуации.',
  },
  {
    img: '/img/phone-cases.webp',
    width: 600,
    height: 557,
    alt: 'Описание задачи для ИИ-юриста',
    title: 'Опишите задачу своими словами',
    text: 'Напишите, что нужно получить: иск, возражение, жалобу, анализ договора, консультацию по рискам или план дальнейших действий.',
  },
  {
    img: '/img/judge-computer.webp',
    width: 600,
    height: 532,
    alt: 'Готовый проект юридического документа',
    title: 'Получите документ и пояснение',
    text: 'ИИ подготовит документ или правовой разбор, выделит важные обстоятельства и объяснит возможные последствия простым языком.',
  },
]

export default function LoginPage() {
  const rawRef = new URLSearchParams(window.location.search).get('ref') || ''

  return (
    <div className="min-h-screen flex flex-col">

      {/* ===== HERO: оригинальный экран с логином ===== */}
      <section className="min-h-screen flex relative">
        {/* Left — branding */}
        <div className="hidden lg:flex lg:w-1/2 bg-surface-950 text-white items-center justify-center p-12 relative overflow-hidden">
          <div className="absolute inset-0 opacity-[0.03]"
            style={{ backgroundImage: 'url("data:image/svg+xml,%3Csvg width=\'60\' height=\'60\' xmlns=\'http://www.w3.org/2000/svg\'%3E%3Cpath d=\'M30 0 L60 30 L30 60 L0 30Z\' fill=\'none\' stroke=\'white\' stroke-width=\'0.5\'/%3E%3C/svg%3E")', backgroundSize: '60px 60px' }} />
          <div className="relative max-w-md">
            <Scale size={48} className="text-brand-400 mb-4" />
            <p className="text-brand-300 text-base mb-6 tracking-wide">Лёгкое правосудие без зависших дел</p>
            <h1 className="font-display text-4xl font-bold mb-4 leading-tight">
              Проект решения суда<br />за 5 минут за 149 рублей
            </h1>
            <p className="text-surface-400 text-lg leading-relaxed mb-8">
              Загрузите фото материалов дела — ИИ подготовит черновик решения
              со ссылками на законы и Пленумы ВС РФ.
            </p>
            <a href="#steps" className="inline-flex items-center gap-2 text-brand-400 hover:text-brand-300 transition-colors text-sm font-medium">
              Как это работает
              <ArrowRight size={16} />
            </a>
          </div>
        </div>

        {/* Right — login form */}
        <div className="flex-1 flex flex-col">
          {/* Mobile logo - top */}
          <div className="lg:hidden flex items-center gap-3 px-6 pt-5 pb-1">
            <Scale size={44} className="text-brand-600 shrink-0" />
            <div>
              <span className="font-display text-xl font-bold leading-tight block">ИИ Помощник Судьи</span>
              <p className="text-surface-500 text-sm leading-tight mt-0.5">Лёгкое правосудие без зависших дел</p>
            </div>
          </div>

          <div className="flex-1 flex items-center justify-center p-6">
            <div className="w-full max-w-sm">
              <div className="lg:hidden mb-8">
                <h1 className="font-display text-2xl font-bold mb-2 leading-tight">
                Проект решения суда<br />за 5 минут за 149 рублей
              </h1>
              <p className="text-surface-500 text-sm leading-relaxed">
                Загрузите фото материалов дела — ИИ подготовит черновик решения
                со ссылками на законы и Пленумы ВС РФ.
              </p>
            </div>

            <h2 className="text-xl font-semibold mb-2 hidden lg:block">Войти в систему</h2>
            <p className="text-surface-500 text-sm mb-8 hidden lg:block">
              Используйте почту, аккаунт Яндекс или ВКонтакте
            </p>

            <EmailOTPForm />
              <div className="flex items-center gap-3 my-4 w-full">
                <div className="flex-1 h-px bg-surface-200"></div>
                <span className="text-surface-400 text-xs">или</span>
                <div className="flex-1 h-px bg-surface-200"></div>
              </div>
              <LoginButtons referral={rawRef} />

            <p className="text-xs text-surface-400 mt-8 text-center leading-relaxed">
              Регистрируясь, вы принимаете{' '}
              <a href={`${API}/docs/oferta`} target="_blank" rel="noopener" className="underline hover:text-surface-600">пользовательское соглашение</a>
              {' '}и{' '}
              <a href={`${API}/docs/privacy`} target="_blank" rel="noopener" className="underline hover:text-surface-600">политику конфиденциальности</a>
            </p>
            <p className="text-xs text-surface-400 mt-3 text-center leading-relaxed">
            </p>
          </div>
        </div>
        </div>

      </section>

{/* ===== ТАРИФЫ ===== */}
      <section className="py-8 sm:py-14 bg-white">
        <div className="max-w-3xl mx-auto px-4 sm:px-6">
          <h2 className="font-display text-2xl sm:text-3xl font-bold text-center mb-2">Тарифы</h2>
          <p className="text-surface-500 text-center mb-8">Одно дело — любое количество документов и доработок</p>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 max-w-2xl mx-auto">
            <div className="rounded-2xl border-2 border-surface-200 bg-surface-50 p-6 text-center hover:border-brand-300 transition-colors">
              <div className="text-3xl font-bold">149 {'₽'}</div>
              <div className="text-surface-600 font-medium mt-1">1 дело</div>
              <div className="text-surface-400 text-sm mt-2">Готовое решение за 20 минут в совещательной комнате</div>
            </div>

            <div className="rounded-2xl border-2 border-brand-400 bg-brand-50 p-6 text-center">
              <div className="text-3xl font-bold">5 000 {'₽'}</div>
              <div className="text-surface-600 font-medium mt-1">Подписка на месяц</div>
              <div className="text-surface-400 text-sm mt-2">Безлимитное количество дел в течение 30 дней</div>
            </div>
          </div>

          <div className="text-center mt-6">
            <button onClick={() => { window.scrollTo({ top: 0, behavior: 'smooth' }); ymGoal('click_try_service'); tmrGoal('click_try_service') }}
              className="inline-flex items-center gap-2 px-6 py-3 bg-brand-600 text-white font-semibold rounded-xl hover:bg-brand-500 transition-all">
              Начать работу
              <ArrowRight size={18} />
            </button>
          </div>
        </div>
      </section>



      {/* ===== ПОШАГОВАЯ ИНСТРУКЦИЯ СО СТИКЕРАМИ ===== */}
      <section id="steps" className="bg-white">
        <div className="max-w-3xl mx-auto px-4 sm:px-6 py-8 sm:py-14">
          <h2 className="font-display text-2xl sm:text-3xl font-bold text-center mb-2">Как это работает</h2>
          <p className="text-surface-500 text-center mb-6 max-w-lg mx-auto">От стопки бумаг до готового проекта решения — за 5 минут</p>

          <div className="space-y-4 sm:space-y-8">
            {STEPS.map((step, i) => {
              const isEven = i % 2 === 1
              return (
                <div key={i} className={`flex flex-col ${isEven ? 'md:flex-row-reverse' : 'md:flex-row'} items-center gap-0 sm:gap-5 md:gap-8`}>
                  {/* Sticker */}
                  <div className={`flex-shrink-0 w-56 sm:w-56 md:w-52 leading-none sm:mb-0 ${i < 2 ? "-mb-14" : "-mb-4"}`}>
                    <img src={step.img} alt={step.alt} width={step.width} height={step.height} loading={i === 0 ? "eager" : "lazy"} fetchPriority={i === 0 ? "high" : "auto"} className="w-full h-auto" />
                  </div>

                  {/* Text */}
                  <div className={`flex-1 ${isEven ? 'md:text-right' : ''} text-center md:text-left`}>
                    <div className={`inline-flex items-center gap-2 mb-2 ${isEven ? 'md:flex-row-reverse' : ''}`}>
                      <div className="w-8 h-8 rounded-full bg-brand-600 text-white flex items-center justify-center font-bold text-sm">{i + 1}</div>
                      <div className="h-px w-6 bg-brand-200" />
                    </div>
                    <h3 className="font-display text-lg sm:text-xl font-bold mb-1.5 text-surface-900">{step.title}</h3>
                    <p className="text-surface-500 text-sm leading-relaxed">{step.text}</p>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      </section>

      {/* ===== ПРЕИМУЩЕСТВА ===== */}
      <section className="py-16 sm:py-20 bg-white">
        <div className="max-w-6xl mx-auto px-4 sm:px-6">
          <h2 className="font-display text-2xl sm:text-3xl font-bold text-center mb-12 sm:mb-16">Почему это удобно</h2>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
            <div className="bg-surface-50 rounded-2xl p-6 border border-surface-100">
              <div className="w-12 h-12 rounded-xl bg-brand-50 flex items-center justify-center mb-4">
                <Clock size={24} className="text-brand-600" />
              </div>
              <h3 className="font-semibold mb-2">5 минут вместо часов</h3>
              <p className="text-surface-500 text-sm leading-relaxed">Черновик решения готов за 5 минут. Экономия 2-3 часа на каждом деле</p>
            </div>

            <div className="bg-surface-50 rounded-2xl p-6 border border-surface-100">
              <div className="w-12 h-12 rounded-xl bg-emerald-50 flex items-center justify-center mb-4">
                <BookOpen size={24} className="text-emerald-600" />
              </div>
              <h3 className="font-semibold mb-2">Актуальные нормы</h3>
              <p className="text-surface-500 text-sm leading-relaxed">Ссылки на действующие редакции законов и актуальные Пленумы ВС РФ</p>
            </div>

            <div className="bg-surface-50 rounded-2xl p-6 border border-surface-100">
              <div className="w-12 h-12 rounded-xl bg-amber-50 flex items-center justify-center mb-4">
                <Camera size={24} className="text-amber-600" />
              </div>
              <h3 className="font-semibold mb-2">Прямо с телефона</h3>
              <p className="text-surface-500 text-sm leading-relaxed">Сфотографируйте документы камерой — не нужно сканировать или печатать</p>
            </div>

            <div className="bg-surface-50 rounded-2xl p-6 border border-surface-100">
              <div className="w-12 h-12 rounded-xl bg-blue-50 flex items-center justify-center mb-4">
                <Shield size={24} className="text-blue-600" />
              </div>
              <h3 className="font-semibold mb-2">Безопасно</h3>
              <p className="text-surface-500 text-sm leading-relaxed">Сервис не хранит загруженные документы. Оригиналы удаляются сразу после обработки</p>
            </div>
          </div>
        </div>
      </section>

      {/* ── Reviews ── */}
      <section className="py-8 sm:py-14">
        <div className="max-w-5xl mx-auto px-4">
          <h2 className="font-display text-2xl sm:text-3xl font-bold text-center mb-8">Отзывы судей</h2>
          <div className="grid sm:grid-cols-2 gap-4 sm:gap-6">
<div className="bg-white rounded-2xl p-6 shadow-sm border border-surface-100">              <div className="flex items-center gap-2 mb-3">                <div className="text-amber-400 text-sm">{"⭐".repeat(5)}</div>              </div>              <p className="text-surface-700 text-sm leading-relaxed">Я стала выдавать решение сразу. Удаляюсь в совещательную комнату на 20 минут и выдаю готовое решение.</p>            </div>
            <div className="bg-white rounded-2xl p-6 shadow-sm border border-surface-100">
              <div className="flex items-center gap-2 mb-3">
                <div className="text-amber-400 text-sm">{'⭐'.repeat(5)}</div>
              </div>
              <p className="text-surface-700 text-sm leading-relaxed">У меня завал из 60 дел за 5 месяцев, не успевала отписывать многотомники, нервные срывы и рыдания. После 10 дней работы с программой осталось 20 дел. Я в восторге, давно пора было сделать такую программу.</p>
            </div>
            <div className="bg-white rounded-2xl p-6 shadow-sm border border-surface-100">
              <div className="flex items-center gap-2 mb-3">
                <div className="text-amber-400 text-sm">{'⭐'.repeat(5)}</div>
              </div>
              <p className="text-surface-700 text-sm leading-relaxed">Что мне понравилось больше всего — помимо скорости написания текста решения, ещё и то, что корректно отражаются обстоятельства дела, нормы права подстраиваются под ситуацию.</p>
            </div>
            <div className="bg-white rounded-2xl p-6 shadow-sm border border-surface-100">
              <div className="flex items-center gap-2 mb-3">
                <div className="text-amber-400 text-sm">{'⭐'.repeat(5)}</div>
              </div>
              <p className="text-surface-700 text-sm leading-relaxed">Наконец-то на просторах интернета появилось то, что реально помогает справиться с гигантским объёмом без ущерба качеству. Программа реально работает!</p>
            </div>
            <div className="bg-white rounded-2xl p-6 shadow-sm border border-surface-100">
              <div className="flex items-center gap-2 mb-3">
                <div className="text-amber-400 text-sm">{'⭐'.repeat(5)}</div>
              </div>
              <p className="text-surface-700 text-sm leading-relaxed">Недавно надо было писать решение по гражданскому делу из 6 томов — пять уточнений иска, возражения, многочисленные письменные позиции. Как же удобно, что всё это можно сфотографировать! По итогу решение было написано за 5 минут, на которое я потратила бы недели.</p>
            </div>
          </div>
        </div>
      </section>

      {/* ===== CTA ВНИЗУ ===== */}

      <section className="py-16 sm:py-20 bg-surface-950 text-white">
        <div className="max-w-2xl mx-auto px-4 sm:px-6 text-center">
          <div className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-white/10 text-brand-300 text-sm font-medium mb-6">
            <Sparkles size={16} />
          </div>
          <h2 className="font-display text-2xl sm:text-3xl font-bold mb-4">Попробуйте прямо сейчас</h2>
          <p className="text-surface-400 mb-8">Войдите через Яндекс или ВК, загрузите материалы дела — получите проект решения.</p>
          <button onClick={() => { window.scrollTo({ top: 0, behavior: 'smooth' }); ymGoal('click_try_service'); tmrGoal('click_try_service') }}
            className="inline-flex items-center gap-2 px-8 py-3.5 bg-brand-600 text-white font-semibold rounded-xl hover:bg-brand-500 transition-all text-base">
            Начать работу
            <ArrowRight size={18} />
          </button>
        </div>
      </section>

      {/* ===== FOOTER ===== */}
      <footer className="border-t border-surface-800 bg-surface-950">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 py-6 flex flex-col sm:flex-row items-center justify-between gap-3 text-xs text-surface-500">
          <div>ИП Терехов А.Н. · ИНН 543801783326 · ОГРНИП 318547600153413</div>
          <div className="flex items-center gap-4">
            <a href={`${API}/docs/oferta`} target="_blank" rel="noopener" className="hover:text-surface-300 transition-colors">Публичная оферта</a>
            <a href={`${API}/docs/privacy`} target="_blank" rel="noopener" className="hover:text-surface-300 transition-colors">Конфиденциальность</a>
          </div>
        </div>
      </footer>
    </div>
  )
}

export function AiLawyerPage() {
  const rawRef = new URLSearchParams(window.location.search).get('ref') || ''

  useEffect(() => {
    document.title = 'ИИ-юрист онлайн — юридический документ и консультация за 149 ₽'
  }, [])

  return (
    <div className="min-h-screen flex flex-col">
      <section className="min-h-screen flex relative">
        <div className="hidden lg:flex lg:w-1/2 bg-surface-950 text-white items-center justify-center p-12 relative overflow-hidden">
          <div className="absolute inset-0 opacity-[0.03]"
            style={{ backgroundImage: 'url("data:image/svg+xml,%3Csvg width=\'60\' height=\'60\' xmlns=\'http://www.w3.org/2000/svg\'%3E%3Cpath d=\'M30 0 L60 30 L30 60 L0 30Z\' fill=\'none\' stroke=\'white\' stroke-width=\'0.5\'/%3E%3C/svg%3E")', backgroundSize: '60px 60px' }} />
          <div className="relative max-w-md">
            <Scale size={48} className="text-brand-400 mb-4" />
            <p className="text-brand-300 text-base mb-6 tracking-wide">ИИ юрист «Помощник судьи»</p>
            <h1 className="font-display text-4xl font-bold mb-4 leading-tight">
              Юридический документ<br />за 5 минут за 149 рублей
            </h1>
            <p className="text-surface-400 text-lg leading-relaxed mb-8">
              Загрузите документы, переписку или описание ситуации — нейросеть подготовит документ или решение суда,
              доработает его по вашим пожеланиям и ответит на вопросы. AI-ревизор проверит правовые нормы в готовом документе на актуальность.
            </p>
          </div>
        </div>

        <div className="flex-1 flex flex-col">
          <div className="lg:hidden flex items-center gap-3 px-6 pt-5 pb-1">
            <Scale size={44} className="text-brand-600 shrink-0" />
            <div>
              <span className="font-display text-xl font-bold leading-tight block">ИИ Помощник Судьи</span>
              <p className="text-surface-500 text-sm leading-tight mt-0.5">ИИ-юрист для документов и консультаций</p>
            </div>
          </div>

          <div className="flex-1 flex items-center justify-center p-6">
            <div className="w-full max-w-sm">
              <div className="lg:hidden mb-8">
                <h1 className="font-display text-2xl font-bold mb-2 leading-tight">
                  Юридический документ<br />за 5 минут за 149 рублей
                </h1>
                <p className="text-surface-500 text-sm leading-relaxed">
                  Загрузите документы, переписку или описание ситуации — нейросеть подготовит документ или решение суда,
                  доработает его по вашим пожеланиям и ответит на вопросы.
                </p>
              </div>

              <h2 className="text-xl font-semibold mb-2 hidden lg:block">Начать работу</h2>
              <p className="text-surface-500 text-sm mb-8 hidden lg:block">
                Войдите, загрузите материалы и опишите, какой документ нужен
              </p>

              <EmailOTPForm />
              <div className="flex items-center gap-3 my-4 w-full">
                <div className="flex-1 h-px bg-surface-200"></div>
                <span className="text-surface-400 text-xs">или</span>
                <div className="flex-1 h-px bg-surface-200"></div>
              </div>
              <LoginButtons referral={rawRef} />

              <p className="text-xs text-surface-400 mt-8 text-center leading-relaxed">
                Регистрируясь, вы принимаете{' '}
                <a href={`${API}/docs/oferta`} target="_blank" rel="noopener" className="underline hover:text-surface-600">пользовательское соглашение</a>
                {' '}и{' '}
                <a href={`${API}/docs/privacy`} target="_blank" rel="noopener" className="underline hover:text-surface-600">политику конфиденциальности</a>
              </p>
            </div>
          </div>
        </div>
      </section>

      <section id="documents" className="py-10 sm:py-16 bg-white">
        <div className="max-w-5xl mx-auto px-4 sm:px-6">
          <div className="text-center mb-8">
            <h2 className="font-display text-2xl sm:text-3xl font-bold mb-2">Что можно получить</h2>
            <p className="text-surface-500 max-w-2xl mx-auto">
              Сервис подходит для бытовых, судебных и договорных ситуаций: от первого разбора до проекта документа.
            </p>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
            {AI_LAWYER_DOCUMENTS.map(item => (
              <div key={item} className="bg-surface-50 rounded-xl border border-surface-100 px-4 py-3 text-sm font-medium text-surface-700 flex items-center gap-2">
                <CheckCircle2 size={16} className="text-brand-600 shrink-0" />
                <span>{item}</span>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="py-10 sm:py-16 bg-surface-50">
        <div className="max-w-6xl mx-auto px-4 sm:px-6">
          <h2 className="font-display text-2xl sm:text-3xl font-bold text-center mb-10">Для кого подходит</h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
            {AI_LAWYER_AUDIENCES.map(({ Icon, title, text }) => (
              <div key={title} className="bg-white rounded-2xl p-6 border border-surface-100 shadow-sm">
                <div className="w-12 h-12 rounded-xl bg-brand-50 flex items-center justify-center mb-4">
                  <Icon size={24} className="text-brand-600" />
                </div>
                <h3 className="font-semibold mb-2">{title}</h3>
                <p className="text-surface-500 text-sm leading-relaxed">{text}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section id="steps" className="bg-white">
        <div className="max-w-3xl mx-auto px-4 sm:px-6 py-10 sm:py-16">
          <h2 className="font-display text-2xl sm:text-3xl font-bold text-center mb-2">Как это работает</h2>
          <p className="text-surface-500 text-center mb-6 max-w-lg mx-auto">
            Не нужно знать юридические термины. Достаточно загрузить материалы и описать задачу обычными словами.
          </p>

          <div className="space-y-4 sm:space-y-8">
            {AI_LAWYER_STEPS.map((step, i) => {
              const isEven = i % 2 === 1
              return (
                <div key={step.title} className={`flex flex-col ${isEven ? 'md:flex-row-reverse' : 'md:flex-row'} items-center gap-0 sm:gap-5 md:gap-8`}>
                  <div className={`flex-shrink-0 w-56 sm:w-56 md:w-52 leading-none sm:mb-0 ${i === 0 ? '-mb-14' : '-mb-4'}`}>
                    <img src={step.img} alt={step.alt} width={step.width} height={step.height} loading={i === 0 ? 'eager' : 'lazy'} fetchPriority={i === 0 ? 'high' : 'auto'} className="w-full h-auto" />
                  </div>

                  <div className={`flex-1 ${isEven ? 'md:text-right' : ''} text-center md:text-left`}>
                    <div className={`inline-flex items-center gap-2 mb-2 ${isEven ? 'md:flex-row-reverse' : ''}`}>
                      <div className="w-8 h-8 rounded-full bg-brand-600 text-white flex items-center justify-center font-bold text-sm">{i + 1}</div>
                      <div className="h-px w-6 bg-brand-200" />
                    </div>
                    <h3 className="font-display text-lg sm:text-xl font-bold mb-1.5 text-surface-900">{step.title}</h3>
                    <p className="text-surface-500 text-sm leading-relaxed">{step.text}</p>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      </section>

      <section className="py-10 sm:py-16 bg-white">
        <div className="max-w-6xl mx-auto px-4 sm:px-6">
          <h2 className="font-display text-2xl sm:text-3xl font-bold text-center mb-10">Почему это удобно</h2>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
            <div className="bg-surface-50 rounded-2xl p-6 border border-surface-100">
              <div className="w-12 h-12 rounded-xl bg-brand-50 flex items-center justify-center mb-4">
                <Clock size={24} className="text-brand-600" />
              </div>
              <h3 className="font-semibold mb-2">Быстро</h3>
              <p className="text-surface-500 text-sm leading-relaxed">Первый проект документа или консультация по материалам готовится за несколько минут.</p>
            </div>

            <div className="bg-surface-50 rounded-2xl p-6 border border-surface-100">
              <div className="w-12 h-12 rounded-xl bg-emerald-50 flex items-center justify-center mb-4">
                <FileText size={24} className="text-emerald-600" />
              </div>
              <h3 className="font-semibold mb-2">По вашим файлам</h3>
              <p className="text-surface-500 text-sm leading-relaxed">Можно загрузить фото, сканы, PDF, договоры, иски, постановления и переписку.</p>
            </div>

            <div className="bg-surface-50 rounded-2xl p-6 border border-surface-100">
              <div className="w-12 h-12 rounded-xl bg-amber-50 flex items-center justify-center mb-4">
                <MessageSquareText size={24} className="text-amber-600" />
              </div>
              <h3 className="font-semibold mb-2">Понятным языком</h3>
              <p className="text-surface-500 text-sm leading-relaxed">ИИ объясняет, что означает документ, какие есть риски и какие шаги можно предпринять.</p>
            </div>

            <div className="bg-surface-50 rounded-2xl p-6 border border-surface-100">
              <div className="w-12 h-12 rounded-xl bg-blue-50 flex items-center justify-center mb-4">
                <Shield size={24} className="text-blue-600" />
              </div>
              <h3 className="font-semibold mb-2">Без обязательной подписки</h3>
              <p className="text-surface-500 text-sm leading-relaxed">Можно оплатить один документ за 149 рублей или взять месячный тариф для постоянной работы.</p>
            </div>
          </div>
        </div>
      </section>

      <section className="py-10 sm:py-16 bg-surface-50">
        <div className="max-w-3xl mx-auto px-4 sm:px-6">
          <h2 className="font-display text-2xl sm:text-3xl font-bold text-center mb-2">Тарифы</h2>
          <p className="text-surface-500 text-center mb-8">Разовый документ или месячный тариф для постоянной работы</p>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 max-w-2xl mx-auto">
            <div className="rounded-2xl border-2 border-surface-200 bg-white p-6 text-center hover:border-brand-300 transition-colors">
              <div className="text-3xl font-bold">149 ₽</div>
              <div className="text-surface-700 font-semibold mt-1">1 документ</div>
              <div className="text-surface-500 text-sm mt-2">
                Загрузка материалов, генерация документа или консультации и ответы на вопросы по результату.
              </div>
            </div>

            <div className="rounded-2xl border-2 border-brand-400 bg-white p-6 text-center shadow-sm">
              <div className="text-3xl font-bold">5 000 ₽</div>
              <div className="text-surface-700 font-semibold mt-1">Подписка на месяц</div>
              <div className="text-surface-500 text-sm mt-2">
                Для регулярной работы с документами, доработками, вопросами и проверкой правовых норм AI-ревизором.
              </div>
              <div className="text-surface-400 text-xs mt-3 leading-relaxed">
                Можно подключить ассистента: он сможет заводить дела и загружать материалы в ваш личный кабинет.
              </div>
            </div>
          </div>

          <div className="text-center mt-6">
            <button onClick={() => { window.scrollTo({ top: 0, behavior: 'smooth' }); ymGoal('click_try_ai_lawyer_price'); tmrGoal('click_try_ai_lawyer_price') }}
              className="inline-flex items-center gap-2 px-6 py-3 bg-brand-600 text-white font-semibold rounded-xl hover:bg-brand-500 transition-all">
              Начать работу
              <ArrowRight size={18} />
            </button>
          </div>
        </div>
      </section>

      <section className="py-10 sm:py-16 bg-white">
        <div className="max-w-5xl mx-auto px-4">
          <div className="text-center mb-8">
            <h2 className="font-display text-2xl sm:text-3xl font-bold mb-2">Отзывы специалистов</h2>
            <p className="text-surface-500 max-w-2xl mx-auto">
              Сервис начинался как инструмент для работы с судебными документами. Поэтому первые отзывы пришли от людей,
              которые ежедневно работают с большими объемами юридических текстов.
            </p>
          </div>
          <div className="grid sm:grid-cols-2 gap-4 sm:gap-6">
            <div className="bg-white rounded-2xl p-6 shadow-sm border border-surface-100">
              <div className="text-amber-400 text-sm mb-3">{'⭐'.repeat(5)}</div>
              <p className="text-surface-700 text-sm leading-relaxed">Помогает быстро собрать структуру документа и не начинать с пустого листа. Особенно удобно, когда материалов много.</p>
            </div>
            <div className="bg-white rounded-2xl p-6 shadow-sm border border-surface-100">
              <div className="text-amber-400 text-sm mb-3">{'⭐'.repeat(5)}</div>
              <p className="text-surface-700 text-sm leading-relaxed">Корректно вытаскивает обстоятельства из документов и превращает их в понятный проект. Потом остается проверить и доработать детали.</p>
            </div>
            <div className="bg-white rounded-2xl p-6 shadow-sm border border-surface-100">
              <div className="text-amber-400 text-sm mb-3">{'⭐'.repeat(5)}</div>
              <p className="text-surface-700 text-sm leading-relaxed">Фотографирование документов сильно экономит время. Не нужно вручную перепечатывать материалы, чтобы получить первичный правовой текст.</p>
            </div>
            <div className="bg-white rounded-2xl p-6 shadow-sm border border-surface-100">
              <div className="text-amber-400 text-sm mb-3">{'⭐'.repeat(5)}</div>
              <p className="text-surface-700 text-sm leading-relaxed">Хороший инструмент для первого проекта: видна логика, структура и слабые места позиции. Для сложных дел удобно брать как основу.</p>
            </div>
          </div>
        </div>
      </section>

      <section className="py-10 sm:py-16 bg-surface-50">
        <div className="max-w-4xl mx-auto px-4 sm:px-6">
          <h2 className="font-display text-2xl sm:text-3xl font-bold text-center mb-8">Важные вопросы</h2>
          <div className="grid md:grid-cols-2 gap-4">
            <div className="bg-white rounded-2xl p-5 border border-surface-100">
              <h3 className="font-semibold mb-2">Можно ли загрузить фото документов?</h3>
              <p className="text-surface-500 text-sm leading-relaxed">Да. Можно загрузить фото с телефона, сканы, PDF и другие файлы с материалами по ситуации.</p>
            </div>
            <div className="bg-white rounded-2xl p-5 border border-surface-100">
              <h3 className="font-semibold mb-2">Это заменяет юриста?</h3>
              <p className="text-surface-500 text-sm leading-relaxed">Нет. Сервис готовит проект и первичный разбор. В сложных и дорогих спорах документ лучше дополнительно проверить у юриста.</p>
            </div>
            <div className="bg-white rounded-2xl p-5 border border-surface-100">
              <h3 className="font-semibold mb-2">Можно ли использовать документ в суде?</h3>
              <p className="text-surface-500 text-sm leading-relaxed">Документ можно использовать как основу: проверить факты, реквизиты, приложения и при необходимости отредактировать перед подачей.</p>
            </div>
            <div className="bg-white rounded-2xl p-5 border border-surface-100">
              <h3 className="font-semibold mb-2">Можно ли подключить ассистента?</h3>
              <p className="text-surface-500 text-sm leading-relaxed">Да. В подписке можно добавить помощника, который будет загружать материалы, заводить дела и готовить их в вашем личном кабинете на вашей подписке.</p>
            </div>
          </div>
        </div>
      </section>

      <section className="py-10 sm:py-16 bg-white">
        <div className="max-w-3xl mx-auto px-4 sm:px-6">
          <div className="rounded-2xl border border-surface-200 bg-surface-50 p-6 sm:p-8">
            <div className="inline-flex items-center gap-2 text-brand-600 font-semibold mb-3">
              <BookOpen size={18} />
              Важно понимать
            </div>
            <p className="text-surface-600 text-sm sm:text-base leading-relaxed">
              ИИ-юрист готовит проект документа и первичный правовой разбор по тем материалам, которые вы загрузили.
              Он помогает быстро понять ситуацию, собрать позицию и получить основу для дальнейшей работы, но не является
              адвокатом или представителем в суде.
            </p>
          </div>
        </div>
      </section>

      <section className="py-16 sm:py-20 bg-surface-950 text-white">
        <div className="max-w-2xl mx-auto px-4 sm:px-6 text-center">
          <div className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-white/10 text-brand-300 text-sm font-medium mb-6">
            <Sparkles size={16} />
            Документ по вашим материалам
          </div>
          <h2 className="font-display text-2xl sm:text-3xl font-bold mb-4">Получите документ за 5 минут</h2>
          <p className="text-surface-400 mb-8">
            Войдите через email, Яндекс или VK, загрузите документы и опишите задачу. ИИ подготовит проект и объяснит ситуацию.
          </p>
          <button onClick={() => { window.scrollTo({ top: 0, behavior: 'smooth' }); ymGoal('click_try_ai_lawyer_bottom'); tmrGoal('click_try_ai_lawyer_bottom') }}
            className="inline-flex items-center gap-2 px-8 py-3.5 bg-brand-600 text-white font-semibold rounded-xl hover:bg-brand-500 transition-all text-base">
            Начать работу
            <ArrowRight size={18} />
          </button>
        </div>
      </section>

      <footer className="border-t border-surface-800 bg-surface-950">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 py-6 flex flex-col sm:flex-row items-center justify-between gap-3 text-xs text-surface-500">
          <div>ИП Терехов А.Н. · ИНН 543801783326 · ОГРНИП 318547600153413</div>
          <div className="flex items-center gap-4">
            <a href={`${API}/docs/oferta`} target="_blank" rel="noopener" className="hover:text-surface-300 transition-colors">Публичная оферта</a>
            <a href={`${API}/docs/privacy`} target="_blank" rel="noopener" className="hover:text-surface-300 transition-colors">Конфиденциальность</a>
          </div>
        </div>
      </footer>
    </div>
  )
}
