import React, { useEffect, useState } from 'react'
import {
  ChevronDown, ChevronRight, ChevronUp,
} from 'lucide-react'
import api from '../../api'
import { Spinner, ErrorMsg, EmptyState } from '../AdminPage'
import { BillingBadge, BalanceCell, UtmBadges, ProviderBadges, PurchaseAttemptsLog } from './AdminBadges'
import CasesTimeline from './CasesTimeline'

export default function ClientsTab() {
  const [clients, setClients] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [sortKey, setSortKey] = useState('created_at')
  const [sortDir, setSortDir] = useState('desc')
  const [expanded, setExpanded] = useState(null)
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [filters, setFilters] = useState({
    hasGeneration: false,
    hasRecentGen: false,
    hasError: false,
    hasUpload: false,
    hasPurchaseAttempt: false,
    hasPaid: false,
    isEmpty: false,
    hasReturned: false,
    hasNotReturned: false,
  })

  useEffect(() => {
    api.getAdminClients()
      .then(setClients)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  const toggleFilter = (key) => setFilters(f => ({ ...f, [key]: !f[key] }))

  const toggleSort = (key) => {
    if (sortKey === key) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortKey(key); setSortDir('desc') }
  }

  // Apply filters
  const filtered = clients.filter(c => {
    // Date filter
    if (dateFrom && c.created_at && c.created_at.slice(0, 10) < dateFrom) return false
    if (dateTo && c.created_at && c.created_at.slice(0, 10) > dateTo) return false
    // Event filters (AND logic — must match ALL checked filters)
    const anyFilter = Object.values(filters).some(v => v)
    if (!anyFilter) return true
    if (filters.hasGeneration && !(c.completed_cases > 0)) return false
    if (filters.hasRecentGen) {
      if (!c.last_completed_at) return false
      const hoursAgo = (Date.now() - new Date(c.last_completed_at).getTime()) / 3600000
      if (hoursAgo > 24) return false
    }
    if (filters.hasError && !(c.error_cases > 0)) return false
    if (filters.hasUpload && !(c.total_cases > 0)) return false
    if (filters.hasPurchaseAttempt && !(c.purchase_attempts && c.purchase_attempts.length > 0)) return false
    if (filters.hasPaid && !(c.revenue_kopecks > 0)) return false
    if (filters.isEmpty && !(c.total_cases === 0)) return false
    if (filters.hasReturned && !(c.last_activity && c.created_at && new Date(c.last_activity) - new Date(c.created_at) > 86400000)) return false
    if (filters.hasNotReturned && !(!c.last_activity || new Date(c.last_activity) - new Date(c.created_at) < 86400000)) return false
    return true
  })

  const sorted = [...filtered].sort((a, b) => {
    let va = a[sortKey], vb = b[sortKey]
    if (va == null) va = ''
    if (vb == null) vb = ''
    if (typeof va === 'string') { va = va.toLowerCase(); vb = (vb || '').toLowerCase() }
    if (va < vb) return sortDir === 'asc' ? -1 : 1
    if (va > vb) return sortDir === 'asc' ? 1 : -1
    return 0
  })

  // Aggregation
  const totalGen = filtered.reduce((s, c) => s + c.completed_cases, 0)
  const totalErr = filtered.reduce((s, c) => s + (c.error_cases || 0), 0)
  const totalRevenue = filtered.reduce((s, c) => s + (c.revenue_kopecks || 0), 0)
  const totalPurchaseAttempts = filtered.reduce((s, c) => s + (c.purchase_attempts?.length || 0), 0)
  const totalCost = filtered.reduce((s, c) => s + (c.cost_rub || 0), 0)

  const SortHead = ({ k, children, align, className = '' }) => (
    <th
      className={`pb-2 pr-3 cursor-pointer select-none hover:text-surface-700 ${align === 'right' ? 'text-right' : 'text-left'} ${className}`}
      onClick={() => toggleSort(k)}
    >
      {children} {sortKey === k ? (sortDir === 'asc' ? '↑' : '↓') : ''}
    </th>
  )

  if (loading) return <Spinner />
  if (error) return <ErrorMsg text={error} />
  if (clients.length === 0) return <EmptyState text="Нет клиентов" />

  const statusLabels = { completed: '✅', error: '❌', processing: '⏳', draft: '◻' }

  return (
    <div className="space-y-2">
      {/* Filters */}
      <div className="p-3 bg-surface-50 rounded-lg border border-surface-200 space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs font-medium text-surface-500">Период:</span>
          <input type="date" value={dateFrom} onChange={e => setDateFrom(e.target.value)}
            className="text-xs border border-surface-200 rounded px-2 py-1" />
          <span className="text-xs text-surface-400">—</span>
          <input type="date" value={dateTo} onChange={e => setDateTo(e.target.value)}
            className="text-xs border border-surface-200 rounded px-2 py-1" />
          {(dateFrom || dateTo) && (
            <button onClick={() => { setDateFrom(''); setDateTo('') }}
              className="text-xs text-red-500 hover:text-red-700">✕ Сброс</button>
          )}
        </div>
        <div className="flex gap-1.5 overflow-x-auto pb-1 -mx-1 px-1 snap-x">
          {[
            ['hasGeneration', '✅ Генерация'],
            ['hasRecentGen', '📅 Ген 24ч'],
            ['hasError', '❌ Ошибка'],
            ['hasUpload', '📁 Загрузка'],
            ['hasPurchaseAttempt', '💳 Попытка оплаты'],
            ['hasPaid', '💰 Оплачено'],
            ['isEmpty', '👤 Пустые'],
            ['hasReturned', '🔁 Вернулись'],
            ['hasNotReturned', '🚫 Не вернулись'],
          ].map(([key, label]) => (
            <button key={key} onClick={() => toggleFilter(key)}
              className={`text-xs px-2 py-1 rounded-full border transition-colors whitespace-nowrap ${
                filters[key]
                  ? 'bg-brand-600 text-white border-brand-600'
                  : 'bg-white text-surface-600 border-surface-200 hover:border-brand-300'
              }`}>
              {label}
            </button>
          ))}
        </div>
        <div className="text-xs text-surface-500 grid grid-cols-2 sm:flex sm:flex-wrap sm:gap-x-4 gap-y-0.5">
          <span>Показано: <b>{filtered.length}</b> из {clients.length}</span>
          <span>Генераций: <b>{totalGen}</b></span>
          <span>Ошибок: <b className="text-red-500">{totalErr}</b></span>
          <span>Попыток оплаты: <b className="text-amber-600">{totalPurchaseAttempts}</b></span>
          <span>Выручка: <b className="text-emerald-600">{(totalRevenue / 100).toLocaleString('ru')}₽</b></span>
          <span>Себест.: <b className="text-orange-600">{totalCost.toFixed(0)}₽</b></span>
          <span>Маржа: <b className="text-emerald-600">{(filtered.reduce((s, c) => s + (c.margin_rub || 0), 0)).toFixed(0)}₽</b></span>
        </div>
      </div>

      {/* Desktop table */}
      <div className="hidden sm:block overflow-x-auto">
        <table className="w-full text-sm table-fixed">
          <thead>
            <tr className="border-b border-surface-200 text-xs text-surface-500 uppercase tracking-wide">
              <SortHead k="email" className="w-[180px]">Юзер</SortHead>
              <th className="pb-2 pr-3 text-left w-[40px]">Вход</th>
              <SortHead k="source" className="w-[120px]">UTM</SortHead>
              <SortHead k="city" className="w-[110px]">Город</SortHead>
              <SortHead k="billing_model" className="w-[90px]">Мод.</SortHead>
              <SortHead k="available_cases" align="right" className="w-[50px]">Бал.</SortHead>
              <SortHead k="revenue_kopecks" align="right" className="w-[50px]">Выр.</SortHead>
              <SortHead k="total_cases" align="right" className="w-[35px]">Дел</SortHead>
              <SortHead k="completed_cases" align="right" className="w-[30px]">✅</SortHead>
              <SortHead k="error_cases" align="right" className="w-[30px]">❌</SortHead>
              <SortHead k="cost_rub" align="right" className="w-[50px]">Себ.</SortHead>
              <SortHead k="margin_rub" align="right" className="w-[55px]">Маржа</SortHead>
              <SortHead k="created_at" className="w-[85px]">Рег.</SortHead>
              <SortHead k="last_activity" className="w-[85px]">Визит</SortHead>
              <SortHead k="visit_count" align="right" className="w-[55px]">Входов</SortHead>
              <SortHead k="referral_count" align="right" className="w-[50px]">Привёл</SortHead>
              <th className="py-2 px-2 text-[11px] font-medium text-surface-500 w-[45px]">Реф.</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map(c => {
              const isExp = expanded === c.full_id
              return (
                <React.Fragment key={c.full_id}>
                <tr
                  className={`border-b border-surface-100 hover:bg-surface-50 cursor-pointer ${c.revenue_kopecks > 0 ? 'bg-emerald-50/50' : ''}`}
                  onClick={() => setExpanded(isExp ? null : c.full_id)}
                >
                  <td className="py-2 pr-3">
                    <div className="flex items-center gap-2">
                      {c.total_cases > 0 ? (
                        isExp ? <ChevronDown size={14} className="text-surface-400 shrink-0" /> : <ChevronRight size={14} className="text-surface-400 shrink-0" />
                      ) : <span className="w-3.5" />}
                      {c.is_admin && (
                        <span className="px-1.5 py-0.5 bg-amber-100 text-amber-700 rounded text-[10px] font-bold">ADM</span>
                      )}
                      <div>
                        <div className="font-medium text-surface-900 text-xs">{c.name || c.email || '—'}</div>
                        {c.name && c.email && <div className="text-[10px] text-surface-400">{c.email}</div>}
                        <div className="text-[9px] text-surface-800 font-mono">#{c.display_id || '?'} {c.id?.slice(0,8)}</div>
                        {c.judge_of?.length > 0 && c.judge_of.map(j => {
                          const bal = j.subscription_until && new Date(j.subscription_until) > new Date()
                            ? `VIP ${new Date(j.subscription_until).toLocaleDateString('ru', { day: '2-digit', month: '2-digit' })}`
                            : `${(j.free_cases_left || 0) + (j.paid_cases_left || 0)} дел`
                          const shortName = (j.name || '?').length > 14 ? (j.name || '?').slice(0, 12) + '..' : (j.name || '?')
                          return (
                            <div key={j.full_id} className="mt-0.5">
                              <span className="whitespace-nowrap text-[9px] px-1.5 py-0.5 bg-blue-50 border border-blue-200 rounded" title={`${j.name} — баланс судьи`}>
                                <b className="text-blue-700">Пом.</b> <span className="text-surface-700">→ {shortName} #{j.display_id}</span> <b className="text-blue-600">· {bal}</b>
                              </span>
                            </div>
                          )
                        })}
                        {c.assistants?.length > 0 && c.assistants.map(a => (
                          <div key={a.full_id} className="mt-0.5">
                            <span className="whitespace-nowrap text-[9px] px-1.5 py-0.5 bg-purple-50 border border-purple-200 rounded" title={a.name}>
                              <b className="text-purple-700">Судья</b> <span className="text-surface-700">← {a.name} #{a.display_id}</span>
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>
                  </td>
                  <td className="py-2 pr-3"><ProviderBadges u={c} /></td>
                  <td className="py-2 pr-3">
                    {c.source ? <UtmBadges source={c.source} /> : <span className="text-[10px] text-surface-300">—</span>}
                  </td>
                  <td className="py-2 pr-3 text-xs text-surface-500 whitespace-nowrap">{c.city || '—'}</td>
                  <td className="py-2 pr-3"><BillingBadge c={c} /></td>
                  <td className="py-2 pr-3 text-right font-mono text-xs"><BalanceCell c={c} /></td>
                  <td className="py-2 pr-3 text-right font-mono text-xs">
                    {c.revenue_kopecks > 0 ? (
                      <span className="text-emerald-700 font-medium">{c.revenue_rub.toLocaleString('ru')} ₽</span>
                    ) : '—'}
                  </td>
                  <td className="py-2 pr-3 text-right font-mono text-xs">{c.total_cases}</td>
                  <td className="py-2 pr-3 text-right font-mono text-xs text-emerald-600">{c.completed_cases}</td>
                  <td className="py-2 pr-3 text-right font-mono text-xs text-red-500">{c.error_cases || '—'}</td>
                  <td className="py-2 pr-3 text-right font-mono text-xs text-orange-600">{c.cost_rub > 0 ? c.cost_rub.toFixed(1) + '₽' : '—'}</td>
                  <td className={`py-2 pr-3 text-right font-mono text-xs ${c.judge_of?.length > 0 ? 'text-surface-400' : (c.margin_rub || 0) > 0 ? 'text-emerald-600' : (c.margin_rub || 0) < 0 ? 'text-red-600' : 'text-surface-400'}`}>{c.judge_of?.length > 0 ? '—' : c.margin_rub != null ? c.margin_rub.toFixed(0) + '₽' : '—'}</td>
                  <td className="py-2 pr-3 text-xs text-surface-400 whitespace-nowrap">
                    {c.created_at ? new Date(c.created_at).toLocaleString('ru', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }) : '—'}
                  </td>
                  <td className="py-2 pr-3 text-xs text-surface-400 whitespace-nowrap">
                    {c.last_activity ? new Date(c.last_activity).toLocaleString('ru', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }) : '—'}
                  </td>
                  <td className="py-2 pr-3 text-right font-mono text-xs">{c.visit_count || 1}</td>
                  <td className="py-2 pr-3 text-right font-mono text-xs">{c.referral_count || 0}</td>
                  <td className="py-2 px-2 text-xs text-surface-400">{c.referred_by_id || "—"}</td>
                </tr>
                {isExp && (c.activity_log?.length > 0 || c.cases?.length > 0 || c.purchase_attempts?.length > 0) && (
                  <tr className="bg-surface-50">
                    <td colSpan={17} className="px-6 py-3">
                      <ActivityTimeline activities={c.activity_log} purchases={c.purchase_attempts} cases={c.cases} />
                    </td>
                  </tr>
                )}
                </React.Fragment>
              )
            })}
          </tbody>
        </table>
      </div>

      {/* Mobile card list */}
      <div className="sm:hidden space-y-2">
        {sorted.map(c => {
          const isExp = expanded === c.full_id
          return (
            <div key={c.full_id} className={`card overflow-hidden ${c.revenue_kopecks > 0 ? 'ring-1 ring-emerald-200' : ''}`}>
              <div
                className="p-3 cursor-pointer active:bg-surface-50"
                onClick={() => setExpanded(isExp ? null : c.full_id)}
              >
                {/* Row 1: name + badges */}
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-1.5 min-w-0 flex-1">
                    {c.is_admin && (
                      <span className="px-1 py-0.5 bg-amber-100 text-amber-700 rounded text-[9px] font-bold shrink-0">ADM</span>
                    )}
                    <div className="min-w-0">
                      <span className="font-medium text-sm text-surface-900 truncate block">
                        {c.name || c.email || '—'}
                      </span>
                      <span className="text-[9px] text-surface-800 font-mono">#{c.display_id || '?'}</span>
                      {c.judge_of?.length > 0 && c.judge_of.map(j => {
                        const bal = j.subscription_until && new Date(j.subscription_until) > new Date()
                          ? `VIP ${new Date(j.subscription_until).toLocaleDateString('ru', { day: '2-digit', month: '2-digit' })}`
                          : `${(j.free_cases_left || 0) + (j.paid_cases_left || 0)} дел`
                        const shortName = (j.name || '?').length > 14 ? (j.name || '?').slice(0, 12) + '..' : (j.name || '?')
                        return (
                          <div key={j.full_id} className="mt-0.5">
                            <span className="whitespace-nowrap text-[9px] px-1.5 py-0.5 bg-blue-50 border border-blue-200 rounded">
                              <b className="text-blue-700">Пом.</b> <span className="text-surface-700">→ {shortName} #{j.display_id}</span> <b className="text-blue-600">· {bal}</b>
                            </span>
                          </div>
                        )
                      })}
                      {c.assistants?.length > 0 && c.assistants.map(a => (
                        <div key={a.full_id} className="mt-0.5">
                          <span className="whitespace-nowrap text-[9px] px-1.5 py-0.5 bg-purple-50 border border-purple-200 rounded">
                            <b className="text-purple-700">Судья</b> <span className="text-surface-700">← {a.name} #{a.display_id}</span>
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                  <div className="flex items-center gap-1.5 shrink-0">
                    <ProviderBadges u={c} />
                    {isExp ? <ChevronUp size={14} className="text-surface-400" /> : <ChevronDown size={14} className="text-surface-400" />}
                  </div>
                </div>

                {/* Row 2: key stats */}
                <div className="flex items-center gap-3 mt-1.5 text-xs text-surface-500 flex-wrap">
                  <BillingBadge c={c} />
                  <BalanceCell c={c} compact />
                  <span>{c.total_cases} дел ({c.completed_cases}✅ {c.error_cases ? c.error_cases + '❌' : ''})</span>
                  {c.cost_rub > 0 && (
                    <span className="text-orange-600">себ.{c.cost_rub.toFixed(0)}₽</span>
                  )}
                  {c.revenue_kopecks > 0 && (
                    <span className="text-emerald-600 font-medium">{c.revenue_rub.toLocaleString('ru')} ₽</span>
                  )}
                  {c.purchase_attempts && c.purchase_attempts.length > 0 && <span className="px-1.5 py-0.5 bg-amber-100 text-amber-700 rounded text-[10px] font-bold">💳{c.purchase_attempts.length}</span>}
                  {c.source && <UtmBadges source={c.source} compact />}
                </div>
              </div>

              {/* Expanded: cases timeline */}
              {isExp && (c.activity_log?.length > 0 || c.cases?.length > 0 || c.purchase_attempts?.length > 0) && (
                <div className="px-3 pb-3 pt-1 border-t border-surface-100">
                  <ActivityTimeline activities={c.activity_log} purchases={c.purchase_attempts} cases={c.cases} />
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

// Full Activity Timeline component - shows all user actions in one list
function ActivityTimeline({ activities, purchases, cases }) {
  if (!activities?.length && !purchases?.length && !cases?.length) return null

  const events = []

  // Only truly internal debug events — never shown
  const HIDDEN = new Set([
    'ab_prices_shown', 'worker_process_only_complete', 'page_billing', 'pay_paywall_shown',
  ])

  // Deduplicate: same type+details key = show once (payment_callback repeats a lot)
  const seenKeys = new Set()
  function dedupKey(type, details) {
    if (!details) return `${type}||`
    const clean = details.replace(/op=[a-f0-9-]+/g, '').replace(/tx=[a-f0-9-]+/g, '').replace(/\d+/g, '#').substring(0, 40)
    return `${type}|${clean}`
  }

  // Add activity events
  ;(activities || []).forEach(a => {
    if (HIDDEN.has(a.action)) return
    const key = dedupKey(a.action, a.details)
    if (seenKeys.has(key)) return
    seenKeys.add(key)
    events.push({
      time: a.created_at,
      timeStr: a.created_time,
      type: a.action,
      details: a.details,
      utm: a.utm_source,
      ip: a.ip_address,
      caseId: a.case_id,
    })
  })

  // Add purchase events (from purchases array)
  ;(purchases || []).forEach(p => {
    events.push({
      time: p.created_at,
      timeStr: p.created_time,
      type: 'purchase',
      details: `${p.type === 'single_case' ? '1 дело' : p.type === 'case_pack_5' ? '5 дел' : 'Подписка'} (${p.amount_rub}₽)`,
      status: p.description?.includes('Оплачено') ? 'paid' : p.has_payment_link ? 'link' : 'click',
    })
  })

  // Add case events (creation + files + status)
  ;(cases || []).forEach(cs => {
    const details = []
    if (cs.files_count > 0) details.push(`${cs.files_count} файл${cs.files_count === 1 ? '' : cs.files_count < 5 ? 'а' : 'ов'}`)
    if (cs.user_instructions) details.push(`\u00AB${cs.user_instructions}\u00BB`)
    events.push({
      time: cs.created_at,
      timeStr: cs.created_time,
      type: 'case_created',
      details: details.join('\n'),
      caseId: cs.id,
      status: cs.status,
      filesCount: cs.files_count,
    })
    if (cs.status === 'completed' && cs.has_generated_text) {
      events.push({
        time: cs.updated_at || cs.created_at,
        timeStr: cs.updated_time || cs.created_time,
        type: 'generate_done',
        details: `${cs.generated_length?.toLocaleString('ru') || '?'} симв.${cs.duration_sec ? ` \u00B7 ${cs.duration_sec}с` : ''}`,
        caseId: cs.id,
        rating: cs.rating,
        review_text: cs.review_text,
      })
    }
    if (cs.status === 'error') {
      events.push({
        time: cs.updated_at || cs.created_at,
        timeStr: cs.updated_time || cs.created_time,
        type: 'error',
        details: 'Ошибка генерации',
        caseId: cs.id,
      })
    }
  })

  events.sort((a, b) => (b.time || '').localeCompare(a.time || ''))

  // Format raw details into readable text
  function fmt(t, d) {
    if (!d) return ''
    if (t === 'payment_confirmed' || t === 'payment_callback' || t === 'payment_checker_found' || t === 'payment_watched') {
      const m = d.match(/(\w+)\s+(\d+)r/)
      if (m) {
        const label = m[1] === 'single_case' ? '1 дело' : m[1] === 'case_pack_5' ? '5 дел' : 'Подписка'
        return `${label} \u00B7 ${m[2]}\u20BD`
      }
    }
    if (t === 'payment_started' || t === 'purchase_attempt') {
      const m = d.match(/(\w+)\s+([\d.]+)r/)
      if (m) {
        const label = m[1] === 'single_case' ? '1 дело' : m[1] === 'case_pack_5' ? '5 дел' : 'Подписка'
        return `${label} \u00B7 ${parseFloat(m[2]).toFixed(0)}\u20BD`
      }
    }
    if (t === 'subscription_renewed') {
      const m = d.match(/until=(.+)/)
      if (m) {
        try { return `до ${new Date(m[1]).toLocaleDateString('ru')}` } catch {}
      }
    }
    if (t === 'worker_generate_complete') {
      const chars = d.match(/chars=(\d+)/)
      const secs = d.match(/elapsed=(\d+)s/)
      return [chars && `${Number(chars[1]).toLocaleString('ru')} симв.`, secs && `${secs[1]}с`].filter(Boolean).join(' \u00B7 ')
    }
    if (t === 'worker_process_complete') {
      const docs = d.match(/docs=(\d+)/)
      if (docs) return `${docs[1]} файл${docs[1] === '1' ? '' : docs[1] < 5 ? 'а' : 'ов'}`
    }
    if (t === 'worker_process_start') {
      const files = d.match(/files=(\d+)/)
      if (files) return `${files[1]} файл${files[1] === '1' ? '' : files[1] < 5 ? 'а' : 'ов'}`
    }
    if (t === 'pay_click') {
      try {
        const j = JSON.parse(d)
        if (j.packageType === 'single_case') return '\u00AB1 дело\u00BB \u00B7 99\u20BD'
        if (j.packageType === 'subscription_monthly') return '\u00ABПодписка\u00BB \u00B7 99\u20BD/мес'
        return j.packageType || ''
      } catch { return d }
    }
    if (t === 'pay_api_start') {
      try {
        const j = JSON.parse(d)
        return j.since_click_ms ? `${j.since_click_ms} мс` : ''
      } catch { return d }
    }
    if (t === 'pay_redirect_start') {
      try {
        const j = JSON.parse(d)
        return j.total_ms ? `${j.total_ms} мс всего` : ''
      } catch { return d }
    }
    if (t === 'email_docx_sent') return d
    if (t === 'download_docx') return d
    if (t === 'refine_start') return d.length > 80 ? d.slice(0, 80) + '\u2026' : d
    if (t === 'worker_error') return d
    if (t === 'worker_summary_rebuilt') return d
    if (t === 'create_case') return d  // multiline — handled in render
    if (t === 'generate') return d
    if (t === 'worker_start') {
      const w = d.match(/worker=(\S+)/)
      const p = d.match(/pipeline=(\w+)/)
      return [p && (p[1] === 'full' ? 'полный цикл' : p[1]), w && w[1]].filter(Boolean).join(' \u00B7 ')
    }
    return d
  }

  const typeCfg = {
    login: { icon: '\uD83D\uDD11', label: 'Вход' },
    purchase: { icon: '\uD83D\uDCB3', label: 'Оплата' },
    payment_started: { icon: '\uD83D\uDCB3', label: 'Платёж создан' },
    payment_confirmed: { icon: '\uD83D\uDCB3', label: 'Оплата зачислена' },
    payment_callback: { icon: '\uD83D\uDCB3', label: 'Повторное зачисление' },
    payment_checker_found: { icon: '\uD83D\uDCB3', label: 'Авто-зачисление' },
    payment_watched: { icon: '\uD83D\uDCB3', label: 'Ожидание оплаты' },
    payment_error: { icon: '\uD83D\uDCB3', label: 'Ошибка оплаты' },
    payment_duplicate: { icon: '\uD83D\uDCB3', label: 'Дубль оплаты' },
    subscription_renewed: { icon: '\uD83D\uDCB3', label: 'Подписка продлена' },
    purchase_attempt: { icon: '\uD83D\uDCB3', label: 'Попытка оплаты' },
    paywall_shown: { icon: '\uD83D\uDCB3', label: 'Показан пейвол' },
    pay_click: { icon: '\uD83D\uDCB3', label: 'Клик по тарифу' },
    pay_api_start: { icon: '', label: '  \u21B3 Запрос в банк' },
    pay_redirect_start: { icon: '', label: '  \u21B3 Открыта оплата' },
    case_created: { label: 'Создано дело' },
    generate_done: { icon: '\u2705', label: 'Готово' },
    generate: { label: 'Генерация запущена' },
    generate_start: { label: 'Генерация запущена' },
    generate_complete: { icon: '\u2705', label: 'Готово' },
    generate_complete_backend: { icon: '\u2705', label: 'Готово (авто)' },
    generate_complete_worker: { icon: '\u2705', label: 'Готово (воркер)' },
    generate_error: { label: 'Ошибка генерации' },
    process_start: { label: 'Обработка запущена' },
    process_paywall_blocked: { label: 'Пейвол — ожидание оплаты' },
    stream_start: { label: 'Трансляция SSE' },
    worker_start: { label: 'Воркер запущен' },
    worker_process_start: { label: 'OCR файлов' },
    worker_process_complete: { label: 'OCR завершён' },
    worker_generate_start: { label: 'Генерация' },
    worker_generate_complete: { icon: '\u2705', label: 'Готово' },
    worker_summary_rebuilt: { label: 'Авто-пересборка контекста' },
    worker_error: { label: 'Ошибка воркера' },
    refine_start: { label: 'Доработка' },
    upload: { label: 'Загрузка файлов' },
    upload_files: { label: 'Загрузка файлов' },
    rate: { label: 'Оценка' },
    review: { label: 'Отзыв' },
    judge_detected: { label: 'Возможно судья' },
    click_generate: { label: 'Нажал \u00ABСгенерировать\u00BB' },
    create_case: { label: 'Новое дело' },
    free_case_used: { label: 'Бесплатное дело' },
    paid_case_used: { label: 'Платное дело' },
    subscription_used: { label: 'По подписке' },
    referral_signup: { label: 'Реферал зарегистрировался' },
    referral_bonus: { label: 'Бонус за реферала' },
    email_docx_sent: { label: 'Отправлен на почту' },
    download_docx: { label: 'Скачан DOCX' },
    ocr_error: { label: 'Ошибка OCR' },
    error: { label: 'Ошибка' },
  }

  return (
    <div className="mb-3 p-3 bg-surface-50 border border-surface-200 rounded-lg">
      <div className="text-[11px] font-medium text-surface-500 uppercase tracking-wide mb-2">Полный лог действий</div>
      <div className="space-y-1 max-h-96 overflow-y-auto">
        {events.map((e, i) => {
          const cfg = typeCfg[e.type] || { label: e.type }
          const det = fmt(e.type, e.details)
          const isMultiline = det && det.includes('\n')
          return (
            <div key={i} className="text-xs py-0.5 border-b border-surface-50 last:border-0">
              <div className="flex items-start gap-2">
                <span className="text-surface-400 font-mono w-20 shrink-0">{e.timeStr}</span>
                {cfg.icon && <span className="shrink-0">{cfg.icon}</span>}
                {!cfg.icon && <span className="w-4 shrink-0" />}
                <span className="font-medium shrink-0 text-surface-700">{cfg.label}</span>
                {!isMultiline && <span className="text-surface-600 truncate">{det}</span>}
                {e.rating > 0 && <span className="text-amber-400 shrink-0">{'\u2605'.repeat(e.rating)}{'\u2606'.repeat(5 - e.rating)}</span>}
                {e.review_text && <span className="text-violet-500 text-[10px] italic max-w-40 truncate" title={e.review_text}>{e.review_text}</span>}
                {e.utm && <span className="text-[9px] bg-surface-200 text-surface-500 px-1 py-0.5 rounded shrink-0 max-w-32 truncate" title={e.utm}>{e.utm}</span>}
                {e.status === 'paid' && <span className="text-[9px] bg-emerald-100 text-emerald-700 px-1 py-0.5 rounded font-bold shrink-0">{'\u2705'}</span>}
                {e.status === 'link' && <span className="text-[9px] bg-blue-100 text-blue-600 px-1 py-0.5 rounded shrink-0">Ссылка</span>}
              </div>
              {isMultiline && <div className="text-surface-500 ml-[7.5rem] break-words whitespace-pre-wrap leading-relaxed">{det.split('\n')[1]}</div>}
            </div>
          )
        })}
      </div>
    </div>
  )
}
