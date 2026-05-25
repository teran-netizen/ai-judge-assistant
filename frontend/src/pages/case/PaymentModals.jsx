import React, { useCallback, useEffect, useState } from 'react'
import api from '../../api'

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
    .replace(/[₽]|руб\.?|рублей|\\u20bd|\/нед|\/мес|\/week|\/month/gi, '')
    .replace(/\s+/g, '')
    .replace(',', '.')
    .replace(/[^\d.-]/g, '')

  const numeric = Number(cleaned)
  return Number.isFinite(numeric) ? numeric : 0
}

const normalizePackage = (pkg = {}) => ({
  ...pkg,
  label: decodeUnicodeEscapes(pkg.label || ''),
  description: decodeUnicodeEscapes(pkg.description || ''),
  price_rub: normalizePriceRub(pkg.price_rub),
})

function payLog(action, data = {}) {
  const ts = performance.now().toFixed(1)
  const isoNow = new Date().toISOString()
  const entry = { ts_ms: ts, iso: isoNow, action, ...data }
  console.log('[PAY]', JSON.stringify(entry))
  try {
    api.trackAction?.(`pay_${action}`, JSON.stringify({ ts_ms: ts, ...data }))
  } catch {}
}

function PaymentError({ error }) {
  if (!error) return null
  return <div className="mt-3 text-sm text-red-600 text-center">{error}</div>
}

function usePayment() {
  const [loading, setLoading] = useState(null)
  const [error, setError] = useState('')

  const handleBuy = useCallback(async (packageType, returnUrl) => {
    const clickTs = performance.now()
    payLog('click', { packageType })
    setLoading(packageType)
    setError('')

    try {
      const apiStart = performance.now()
      payLog('api_start', { packageType, since_click_ms: (apiStart - clickTs).toFixed(1) })
      const res = await api.purchaseAttempt(packageType, returnUrl)
      const apiEnd = performance.now()

      payLog('api_response', {
        packageType,
        api_latency_ms: (apiEnd - apiStart).toFixed(1),
        has_url: !!res.payment_url,
        has_qr: !!res.qr,
      })

      if (res.payment_url) {
        if (res.operation_id) {
          localStorage.setItem('pending_payment_op', res.operation_id)
        }
        if (res.transaction_id) {
          localStorage.setItem('pending_payment_tx', res.transaction_id)
        }
        localStorage.setItem('pending_payment_ts', String(Date.now()))
        api.savePendingPayment?.(res.operation_id || '', res.transaction_id || '')
        payLog('redirect_start', { packageType, total_ms: (apiEnd - clickTs).toFixed(1) })
        window.location.href = res.payment_url
        return
      }
    } catch (e) {
      payLog('error', { packageType, error: (e.message || '').slice(0, 100) })
      setError(e.message || 'Ошибка оплаты')
    } finally {
      setLoading(null)
    }
  }, [])

  return { handleBuy, loading, error }
}

function usePackages() {
  const [packages, setPackages] = useState([])

  useEffect(() => {
    api
      .getPackages?.()
      .then((data) => {
        const normalized = (Array.isArray(data?.case_packages) ? data.case_packages : []).map(normalizePackage)
        setPackages(normalized)
      })
      .catch(() => {})
  }, [])

  return { packages }
}

const Spinner = () => (
  <svg className="animate-spin h-5 w-5 text-brand-500" viewBox="0 0 24 24">
    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
  </svg>
)

const SpinnerSm = () => (
  <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
  </svg>
)

const durationSuffix = (pkg) => {
  const days = Number(pkg?.duration_days || 0)
  if (days >= 28) return 'мес'
  if (days > 0 && days <= 3) return `${days} дня`
  if (days > 0) return 'нед'
  return ''
}

function PkgButton({ pkg, onClick, loading, highlight, badge }) {
  const isBusy = loading === pkg.type
  const isAnyBusy = loading !== null
  const isSub = !!pkg.duration_days

  return (
    <button
      onClick={() => onClick(pkg.type)}
      disabled={isAnyBusy}
      className={`w-full p-4 rounded-xl transition-all text-left relative ${
        isBusy ? 'opacity-80 animate-pulse' : ''
      } ${
        highlight ? 'border-2 border-brand-500 bg-brand-50 hover:bg-brand-100' : 'border border-surface-200 hover:border-brand-300 hover:bg-brand-50'
      }`}
    >
      {badge && (
        <div className="absolute -top-2.5 right-4 bg-red-500 text-white text-[10px] font-bold px-2.5 py-0.5 rounded-full">
          {badge}
        </div>
      )}

      <div className="flex justify-between items-center">
        <div>
          <div className="font-semibold">{pkg.label}</div>
          <div className="text-xs text-surface-400">
            {isSub ? 'Неограниченное количество дел' : pkg.cases === 1 ? 'Разовая генерация' : 'Пакет со скидкой'}
          </div>
        </div>

        <div className="text-right flex items-center gap-2">
          {isBusy && <Spinner />}
          <div>
            <div className="text-lg font-bold">
              {pkg.price_rub.toLocaleString('ru')} {RUBLE_SIGN}{pkg.duration_days ? ' / мес' : ''}
            </div>
          </div>
        </div>
      </div>
    </button>
  )
}

export function PaywallModal({ onClose, promo, tierInfo, returnUrl }) {
  const { handleBuy, loading, error } = usePayment()
  const { packages } = usePackages()

  useEffect(() => {
    payLog('paywall_shown', { tier: tierInfo?.tier })
  }, [tierInfo?.tier])

  const tier = tierInfo?.tier || 'single_case'

  const tierPkg = normalizePackage(
    packages.find((p) => p.type === tier) || {
      type: tier,
      label: tierInfo?.tier_label || '1 дело',
      cases: 1,
      price_rub: tierInfo?.price_rub || 99,
    }
  )

  const subPkg = normalizePackage(
    packages.find((p) => p.type === 'subscription_monthly') || {
      type: 'subscription_monthly',
      label: 'Подписка на месяц',
      duration_days: 30,
      price_rub: 5000,
      old_price_rub: 0,
    }
  )

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 animate-in">
      <div className="bg-white rounded-2xl shadow-xl max-w-md w-full p-6 relative">
        <button onClick={onClose} className="absolute top-3 right-3 text-surface-400 hover:text-surface-600 text-xl leading-none p-1">
          &times;
        </button>

        <div className="text-center mb-6">
          <div className="text-4xl mb-3">{'\u2696\uFE0F'}</div>
          <h2 className="text-xl font-display font-bold">Сгенерировать документ</h2>
          <p className="text-surface-500 text-sm mt-2">Документы загружены</p>
        </div>

        <div className="space-y-3">
          <PkgButton
            pkg={tierPkg}
            onClick={(t) => handleBuy(t, returnUrl)}
            loading={loading}
            highlight
            badge="ВАШ ТАРИФ"
          />
          <PkgButton pkg={subPkg} onClick={(t) => handleBuy(t, returnUrl)} loading={loading} />
        </div>

        <PaymentError error={error} />
        <button onClick={onClose} className="w-full mt-4 text-sm text-surface-400 hover:text-surface-600 py-2">
          Отмена
        </button>
      </div>
    </div>
  )
}

export function UpsellModal({ onClose }) {
  const { handleBuy, loading, error } = usePayment()
  const { packages } = usePackages()
  const subPkg = packages.find((p) => p.type === 'subscription_monthly')
  const subLabel = subPkg ? `${subPkg.price_rub.toLocaleString('ru')} ${RUBLE_SIGN}/мес` : `5 000 ${RUBLE_SIGN}/мес`

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 animate-in">
      <div className="bg-white rounded-2xl shadow-xl max-w-sm w-full p-6 text-center">
        <div className="text-4xl mb-3">{'\u2B50'}</div>
        <h2 className="text-lg font-display font-bold mb-2">Понравился результат?</h2>
        <p className="text-surface-500 text-sm mb-4">Оформите подписку на месяц и пользуйтесь без ограничений</p>

        <button onClick={() => handleBuy('subscription_monthly')} disabled={loading} className="btn-primary w-full py-3 mb-2">
          {loading ? (
            <span className="flex items-center justify-center gap-2">
              <SpinnerSm /> Загрузка...
            </span>
          ) : (
            `Подписка — ${subLabel}`
          )}
        </button>

        <PaymentError error={error} />
        <button onClick={onClose} className="text-sm text-surface-400 hover:text-surface-600 mt-2">
          Позже
        </button>
      </div>
    </div>
  )
}

export function PaywallScreen() {
  const { handleBuy, loading, error } = usePayment()
  const { packages } = usePackages()

  useEffect(() => {
    payLog('paywall_screen_shown')
  }, [])

  const casePkgs = packages.filter((p) => p.cases && p.cases > 0)
  const subPkgs = packages.filter((p) => p.duration_days)

  return (
    <div className="flex-1 flex items-center justify-center p-6">
      <div className="max-w-lg w-full text-center">
        <div className="text-5xl mb-4">{'\uD83D\uDD12'}</div>
        <h2 className="text-xl font-display font-bold mb-2">Выберите тариф</h2>
        <p className="text-surface-500 mb-6">Загрузите документы — стоимость определяется выбранным пакетом</p>

        <div className="grid sm:grid-cols-2 gap-3 mb-4">
          {casePkgs.map((pkg) => (
            <button
              key={pkg.type}
              onClick={() => handleBuy(pkg.type)}
              disabled={loading}
              className={`p-4 rounded-xl border text-left transition-all ${
                loading === pkg.type ? 'opacity-80 animate-pulse border-brand-300' : 'border-surface-200 hover:border-brand-300'
              }`}
            >
              <div className="text-xs text-surface-400 mb-1">{pkg.label}</div>
              <div className="text-sm text-surface-500">{pkg.cases === 1 ? 'Разовая генерация' : 'Пакет со скидкой'}</div>
              <div className="text-xl font-bold mt-2">
                {pkg.price_rub.toLocaleString('ru')} {RUBLE_SIGN}
              </div>
            </button>
          ))}

          {subPkgs.map((pkg) => (
            <button
              key={pkg.type}
              onClick={() => handleBuy(pkg.type)}
              disabled={loading}
              className={`p-4 rounded-xl border-2 border-brand-500 bg-brand-50 hover:bg-brand-100 transition-all text-left relative ${
                loading === pkg.type ? 'opacity-80 animate-pulse' : ''
              }`}
            >
              {pkg.type === 'subscription_monthly' && (
                <div className="absolute -top-2 right-3 bg-brand-600 text-white text-[10px] font-bold px-2 py-0.5 rounded-full">
                  ВЫГОДНО
                </div>
              )}
              <div className="text-xs text-surface-400 mb-1">{pkg.label}</div>
              <div className="text-sm text-surface-500">любое количество дел</div>
              <div className="text-xl font-bold mt-2">
                {pkg.price_rub.toLocaleString('ru')} {RUBLE_SIGN}/{durationSuffix(pkg)}
              </div>
            </button>
          ))}
        </div>

        <PaymentError error={error} />
        <a href="/billing" className="text-sm text-brand-600 hover:text-brand-800">
          Подробнее о тарифах {'\u2192'}
        </a>
      </div>
    </div>
  )
}

