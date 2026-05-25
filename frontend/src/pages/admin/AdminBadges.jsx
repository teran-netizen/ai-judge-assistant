import React from 'react'

export function BillingBadge({ c }) {
  // For assistants: show judge's billing status
  const judge = c.judge_of?.length > 0 ? c.judge_of[0] : null
  if (judge) {
    const hasSub = judge.subscription_until && new Date(judge.subscription_until) > new Date()
    if (hasSub) return <><span className="px-1.5 py-0.5 bg-blue-100 text-blue-700 rounded text-[10px] font-bold" title="Через судью">SUB*</span></>
    const jPaid = (judge.paid_cases_left || 0)
    if (jPaid > 0) return <><span className="px-1.5 py-0.5 bg-blue-100 text-blue-700 rounded text-[10px] font-bold" title="Через судью">PAID:{jPaid}*</span></>
    const jFree = (judge.free_cases_left || 0)
    if (jFree > 0) return <><span className="px-1.5 py-0.5 bg-blue-100 text-blue-700 rounded text-[10px] font-bold" title="Через судью">FREE:{jFree}*</span></>
    return <><span className="px-1.5 py-0.5 bg-red-100 text-red-700 rounded text-[10px] font-bold" title="Через судью">0 дел*</span></>
  }

  if (c.billing_model === 'cases') {
    const hasSub = c.subscription_until && new Date(c.subscription_until) > new Date()
    if (hasSub) return <><span className="px-1.5 py-0.5 bg-violet-100 text-violet-700 rounded text-[10px] font-bold">SUB</span></>
    if (c.paid_cases_left > 0) return <><span className="px-1.5 py-0.5 bg-emerald-100 text-emerald-700 rounded text-[10px] font-bold">PAID:{c.paid_cases_left}</span></>
    if (c.free_cases_left > 0) return <><span className="px-1.5 py-0.5 bg-blue-100 text-blue-700 rounded text-[10px] font-bold">FREE:{c.free_cases_left}</span></>
    return <><span className="px-1.5 py-0.5 bg-red-100 text-red-700 rounded text-[10px] font-bold">0 дел</span></>
  }
  return <span className="px-1.5 py-0.5 bg-surface-100 text-surface-500 rounded text-[10px] font-bold">TOK</span>
}

export function BalanceCell({ c, compact }) {
  // For assistants: show judge's balance instead of own
  const judge = c.judge_of?.length > 0 ? c.judge_of[0] : null
  if (judge) {
    const hasSub = judge.subscription_until && new Date(judge.subscription_until) > new Date()
    if (hasSub) {
      const dt = new Date(judge.subscription_until).toLocaleDateString('ru', { day: '2-digit', month: '2-digit' })
      return compact
        ? <span className="text-violet-600" title="Баланс судьи">{'∞'} до {dt}</span>
        : <span className="text-violet-600 text-xs" title="Баланс судьи">{'∞'} до {dt}</span>
    }
    const jTotal = (judge.free_cases_left || 0) + (judge.paid_cases_left || 0)
    return compact
      ? <span title="Баланс судьи">{jTotal} дел</span>
      : <span className="text-xs" title="Баланс судьи">{jTotal} дел</span>
  }

  const total = (c.free_cases_left || 0) + (c.paid_cases_left || 0)
  const hasSub = c.subscription_until && new Date(c.subscription_until) > new Date()
  if (hasSub) {
    const dt = new Date(c.subscription_until).toLocaleDateString('ru', { day: '2-digit', month: '2-digit' })
    return compact ? <span className="text-violet-600">{'∞'} до {dt}</span> : <span className="text-violet-600 text-xs">{'∞'} до {dt}</span>
  }
  return compact ? <span>{total} дел</span> : <span className="text-xs">{total} дел</span>
}

export function PurchaseAttemptsLog({ attempts }) {
  const typeNames = {
    single_case: '1 дело',
    case_pack_5: '5 дел',
    subscription_monthly: 'Подписка',
  }
  const statusBadge = (a) => {
    if (a.description && a.description.includes('Оплачено')) return <span className="px-1.5 py-0.5 bg-emerald-100 text-emerald-700 rounded text-[9px] font-bold">✅ Зачислено</span>
    if (a.has_payment_link) return <span className="px-1.5 py-0.5 bg-blue-100 text-blue-600 rounded text-[9px] font-bold">Ссылка создана</span>
    return <span className="px-1.5 py-0.5 bg-surface-100 text-surface-500 rounded text-[9px] font-bold">Клик</span>
  }
  return (
    <div className="mb-3 p-2.5 bg-amber-50 border border-amber-200 rounded-lg">
      <div className="text-[11px] font-medium text-amber-700 uppercase tracking-wide mb-1.5">💳 Оплата</div>
      {attempts.map((a, i) => (
        <div key={i} className="text-xs text-amber-800 flex items-center gap-2 py-0.5">
          <span className="text-amber-500 text-[10px] w-20 shrink-0">{a.created_time}</span>
          <span className="font-medium">{typeNames[a.type] || a.type} ({a.amount_rub || '?'}₽)</span>
          {statusBadge(a)}
        </div>
      ))}
    </div>
  )
}

export function UtmBadges({ source, compact }) {
  // Parse "source=yandex&medium=cpc&campaign=123&content=456&term=keyword"
  const parts = {}
  ;(source || '').split('&').forEach(p => {
    const [k, ...v] = p.split('=')
    if (k && v.length) parts[k] = decodeURIComponent(v.join('=').replace(/\+/g, ' '))
  })

  // Show term/source as main label, full UTM on hover
  const term = parts['term'] || parts['utm_term'] || parts['source'] || parts['utm_source'] || ''

  return (
    <div className="flex flex-wrap gap-0.5" title={source}>
      {term ? (
        <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-blue-50 text-blue-700 max-w-[140px] truncate">{term}</span>
      ) : (
        <span className="text-[10px] text-surface-300">—</span>
      )}
    </div>
  )
}

export function ProviderBadges({ u }) {
  return (
    <div className="flex gap-1">
      {u.yandex_id && <span className="px-1.5 py-0.5 bg-red-50 text-red-600 rounded text-[10px] font-medium">{'\u042f'}</span>}
      {u.vk_id && <span className="px-1.5 py-0.5 bg-blue-50 text-blue-600 rounded text-[10px] font-medium">VK</span>}
    </div>
  )
}
