import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'
import { ymGoal } from '../ym'
import { Wallet, Zap, CheckCircle, X, Loader, ShieldCheck, Crown } from 'lucide-react'
import api from '../api'

const RUBLE_SIGN = '₽'
const decodeUnicodeEscapes = (value) => {
  if (value === null || value === undefined) return ''
  return String(value).replace(/\\u([0-9a-fA-F]{4})/g, (_, hex) =>
    String.fromCharCode(parseInt(hex, 16))
  )
}
const normalizePriceRub = (value) => {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (value === null || value === undefined) return 0
  const decoded = decodeUnicodeEscapes(value)
  const cleaned = decoded
    .replace(/[₽]|руб\.?|рублей|\/нед|\/week/gi, '')
    .replace(/\s+/g, '')
    .replace(',', '.')
    .replace(/[^\d.-]/g, '')
  const numeric = Number(cleaned)
  return Number.isFinite(numeric) ? numeric : 0
}
const normalizePackage = (pkg) => ({
  ...pkg,
  label: decodeUnicodeEscapes(pkg?.label || ''),
  description: decodeUnicodeEscapes(pkg?.description || ''),
  price_rub: normalizePriceRub(pkg?.price_rub),
})
/* ms-level payment logger */
function payLog(action, data = {}) {
  const ts = performance.now().toFixed(1)
  const isoNow = new Date().toISOString()
  const entry = { ts_ms: ts, iso: isoNow, action, ...data }
  console.log('[PAY]', JSON.stringify(entry))
  try { api.trackAction('pay_' + action, JSON.stringify({ ts_ms: ts, ...data })) } catch {}
}



export default function BillingPage() {
  const { user, refreshUser } = useAuth()
  const [packages, setPackages] = useState([])
  const [loading, setLoading] = useState(null)
  const [params, setParams] = useSearchParams()
  const paymentSuccess = params.get('payment') === 'success'
  const paymentFail = params.get('payment') === 'fail'

  const [caseToast, setCaseToast] = useState(false)

  useEffect(() => {
    ymGoal('page_billing')
    api.trackAction('page_billing')
    api.getPackages().then(data => {
      if (data.case_packages) {
        const casePackages = (Array.isArray(data.case_packages) ? data.case_packages : []).map(normalizePackage)
        setPackages(casePackages)
        const priceLog = casePackages.map(p => `${p.type}=${p.price_rub}`).join(',')
        api.trackAction('ab_prices_shown', `promo=${data.promo ? 'A' : 'B'} ${priceLog}`)
      } else {
        const fallback = Array.isArray(data?.token_packages)
          ? data.token_packages
          : (Array.isArray(data) ? data : [])
        setPackages(fallback.map(normalizePackage))
      }
    }).catch(() => {})

    let timer = null
    let watchEs = null  // SSE для live-watch оплаты
    if (paymentSuccess || paymentFail) {
      if (paymentSuccess) {
        ymGoal('payment_success')
        const opId = params.get('op') || ''
        const txId = params.get('tx') || ''

        // Сначала одноразовый confirm-payment (мгновенный путь если Tochka
        // уже ответила paid к моменту редиректа).
        api.confirmPayment(opId, txId).then(refreshUser).catch(() => {})

        // Live-watch: SSE стрим ловит зачисление как только Точка вернула
        // paid. На стороне сервера каждую секунду пробит Tochka API первые
        // 10 сек, потом 3 сек, потом 10 сек до deadline=10 мин.
        if (txId) {
          try {
            watchEs = new EventSource(`/api/billing/watch/${encodeURIComponent(txId)}`, {
              withCredentials: true,
            })
            watchEs.onmessage = (e) => {
              try {
                const data = JSON.parse(e.data)
                if (data.status === 'credited') {
                  refreshUser()
                  ymGoal('payment_credited')
                }
                if (data.status === 'done' || data.status === 'cancelled' || data.status === 'timeout') {
                  watchEs?.close()
                  watchEs = null
                }
              } catch {}
            }
            watchEs.onerror = () => {
              watchEs?.close()
              watchEs = null
            }
          } catch {}
        }
      }
      timer = setTimeout(() => setParams({}), 5000)
    }

    return () => {
      if (timer) clearTimeout(timer)
      if (watchEs) watchEs.close()
    }
  }, [])

  const handleCasePurchase = async (packageType) => {
    const clickTs = performance.now()
    payLog('click', { packageType, page: 'billing' })
    const goalMap = {
      single_case: 'purchase_single_case',
      subscription_monthly: 'purchase_subscription',
    }

    ymGoal(goalMap[packageType] || 'purchase_case_unknown')
    setLoading(packageType)
    try {
      const apiStart = performance.now()
      payLog('api_start', { packageType, since_click_ms: (apiStart - clickTs).toFixed(1) })
      const result = await api.purchaseAttempt(packageType)
      const apiEnd = performance.now()
      payLog('api_response', { packageType, api_latency_ms: (apiEnd - apiStart).toFixed(1), has_url: !!result.payment_url })
      if (result.payment_url) {
        payLog('redirect_start', { packageType, total_ms: (performance.now() - clickTs).toFixed(1) })
        window.location.href = result.payment_url
        return
      }
      setCaseToast(true)
    } catch (e) {
      alert(e.message || 'Ошибка оплаты')
    } finally {
      setLoading(null)
    }
  }

  return (
      <div className="flex-1 overflow-y-auto" style={{ scrollbarGutter: 'stable' }}>
        <div className="max-w-3xl mx-auto px-6 py-6 sm:py-8">
          <div className="animate-in">
            <h1 className="text-2xl font-display font-bold mb-6">Оплата</h1>

            <CasesStatusCard user={user} />
            <InviteSection refreshUser={refreshUser} />

            <h2 className="text-lg font-semibold mb-4">Тарифы</h2>
            <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
              {(Array.isArray(packages) ? packages : []).map((pkg) => {
                const isSub = pkg.type === 'subscription_monthly'
                const isHighlight = false
                // Описание по типу: единый формат → карточки одинаковой высоты
                // и одинаково понятны. `pkg.description` из бэка имеет приоритет.
                const description = pkg.description || (isSub
                  ? 'Безлимитное количество дел в течение 30 дней'
                  : 'Одна генерация проекта судебного акта')
                const priceSuffix = isSub ? ' / мес' : ''

                return (
                  <div key={pkg.type} className={`card p-5 flex flex-col min-h-[260px] ${isHighlight ? 'border-brand-500 ring-2 ring-brand-500/20 relative' : ''}`}>
                    {isHighlight && (
                      <div className="absolute -top-2.5 left-4 bg-brand-600 text-white text-xs font-medium px-2.5 py-0.5 rounded-full">
                        Популярный
                      </div>
                    )}
                    <div className="flex items-center gap-2 mb-3 min-h-[40px]">
                      <div className={`w-9 h-9 rounded-lg flex items-center justify-center shrink-0 ${isSub ? 'bg-amber-50' : 'bg-brand-50'}`}>
                        {isSub ? <Crown size={18} className="text-amber-600" /> : <Zap size={18} className="text-brand-600" />}
                      </div>
                      <div className="font-semibold text-sm">{pkg.label}</div>
                    </div>
                    <div className="text-2xl font-bold mb-1">
                      {pkg.price_rub.toLocaleString('ru')} {RUBLE_SIGN}{priceSuffix}
                    </div>
                    <div className="text-sm text-surface-500 mb-4 flex-1">{description}</div>
                    <button
                      onClick={() => handleCasePurchase(pkg.type)}
                      disabled={loading !== null}
                      className={isHighlight ? 'btn-primary w-full' : 'btn-secondary w-full'}
                    >
                      {loading === pkg.type ? 'Загрузка...' : 'Купить'}
                    </button>
                  </div>
                )
              })}
            </div>

            <p className="text-xs text-surface-400 mt-6 text-center leading-relaxed">
              <a href={`${import.meta.env.VITE_API_URL || ''}/docs/oferta`} target="_blank" rel="noopener" className="underline hover:text-surface-600">Публичная оферта</a>
            </p>

            {caseToast && (
              <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 max-w-md w-full px-4">
                <div className="card p-4 border-brand-200 bg-brand-50 text-sm text-brand-800 shadow-lg flex items-start gap-3">
                  <ShieldCheck size={20} className="text-brand-600 shrink-0 mt-0.5" />
                  <div className="flex-1">
                    <div className="font-medium mb-0.5">Оплата временно недоступна</div>
                    <div className="text-brand-600 text-xs">Мы уведомим вас, когда подключим оплату.</div>
                  </div>
                  <button onClick={() => setCaseToast(false)} className="text-brand-400 hover:text-brand-700">
                    <X size={16} />
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    )
}

function CasesStatusCard({ user }) {
  const subActive = user?.subscription_until && new Date(user.subscription_until) > new Date()
  const paidCases = user?.paid_cases_left || 0
  const freeCases = user?.free_cases_left || 0

  const formatDate = (iso) => {
    const d = new Date(iso)
    return d.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric' })
  }

  return (
    <div className="card p-6 mb-6 bg-gradient-to-br from-brand-600 to-brand-800 text-white">
      <div className="flex items-center gap-3 mb-3">
        <Wallet size={24} />
        <span className="font-medium">Ваш тариф</span>
      </div>
      <div className="space-y-1.5">
        {subActive ? <div className="text-lg font-semibold">Подписка активна до {formatDate(user.subscription_until)}</div> : null}
        {paidCases > 0 ? <div className="text-lg font-semibold">Оплаченных дел: {paidCases}</div> : null}
        {freeCases > 0 ? <div className="text-brand-200">Бесплатных дел: {freeCases}</div> : null}
        {!subActive && paidCases === 0 && freeCases === 0 ? (
          <div className="text-brand-200">Бесплатное дело использовано</div>
        ) : null}
      </div>
    </div>
  )
}

function InviteSection({ refreshUser }) {
  const [code, setCode] = useState('')
  const [activating, setActivating] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')

  const handleActivate = async () => {
    if (code.trim().length < 3) {
      setError('Введите промокод')
      return
    }
    setError('')
    setResult(null)
    setActivating(true)
    try {
      const res = await api.activateInvite(code.trim())
      try {
        api.trackAction('promo_activated', code.trim())
      } catch {}
      setResult(res)
      setCode('')
      await refreshUser()
    } catch (e) {
      setError(e.message)
    } finally {
      setActivating(false)
    }
  }

  return (
    <div className="card p-4 mb-6">
      <div className="text-sm font-medium mb-2">Промокод</div>
      <div className="flex gap-2">
        <input
          value={code}
          onChange={e => setCode(e.target.value.toUpperCase())}
          onKeyDown={e => e.key === 'Enter' && handleActivate()}
          placeholder="Введите промокод"
          maxLength={32}
          className="input flex-1"
        />
        <button
          onClick={handleActivate}
          disabled={activating || !code.trim()}
          className="btn-primary px-4"
        >
          {activating ? <Loader size={16} className="animate-spin" /> : 'Применить'}
        </button>
      </div>
      {result ? (
        <div className="flex items-center gap-2 mt-3 p-3 rounded-lg bg-emerald-50 border border-emerald-200">
          <CheckCircle size={20} className="text-emerald-600 shrink-0" />
          <span className="text-sm font-medium text-emerald-800">{result.message}</span>
        </div>
      ) : null}
      {error ? <p className="text-red-500 text-sm mt-2">{error}</p> : null}
    </div>
  )
}
