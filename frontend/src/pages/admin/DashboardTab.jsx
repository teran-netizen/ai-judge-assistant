import React, { useEffect, useState } from 'react'
import {
  Users, FileText, CreditCard, MessageCircle, Ticket, Gift, Clock, AlertTriangle, Activity, TrendingUp, Zap, Timer, Calendar, Percent, CheckCircle, XCircle, AlertOctagon, RefreshCw,
} from 'lucide-react'
import api from '../../api'
import { Spinner, ErrorMsg } from '../AdminPage'

export default function DashboardTab() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')

  const fetchData = (from, to) => {
    setLoading(true)
    const params = new URLSearchParams()
    if (from) params.set('date_from', from)
    if (to) params.set('date_to', to)
    const qs = params.toString()
    const url = '/api/admin/dashboard' + (qs ? '?' + qs : '')
    fetch(url, { credentials: 'include' })
      .then(r => r.json())
      .then(setData)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }

  useEffect(() => { fetchData('', '') }, [])

  const handleFilter = () => fetchData(dateFrom, dateTo)
  const handleReset = () => { setDateFrom(''); setDateTo(''); fetchData('', '') }

  if (loading && !data) return <Spinner />
  if (error) return <ErrorMsg text={error} />

  const fmtRub = (v) => `${(v || 0).toLocaleString('ru', { maximumFractionDigits: 0 })} ₽`

  const cards = [
    { label: 'Пользователей', value: data.total_users, icon: Users, color: 'text-blue-600 bg-blue-50' },
    { label: 'Платящих (30д)', value: data.paying_users_30d, icon: Users, color: 'text-emerald-600 bg-emerald-50' },
    { label: 'Всего дел', value: data.total_cases, icon: FileText, color: 'text-violet-600 bg-violet-50' },
    { label: 'Выручка', value: fmtRub(data.total_revenue_rub), icon: CreditCard, color: 'text-amber-600 bg-amber-50' },
    { label: 'Налог+эквайринг 10%', value: fmtRub(data.tax_acquiring_rub), icon: Percent, color: 'text-red-600 bg-red-50' },
    { label: 'Выручка нетто', value: fmtRub(data.net_revenue_rub), icon: CreditCard, color: 'text-emerald-600 bg-emerald-50' },
    { label: 'Себестоимость', value: fmtRub(data.total_cost_rub), icon: CreditCard, color: 'text-orange-600 bg-orange-50' },
    { label: 'Маржа', value: fmtRub(data.margin_rub), icon: TrendingUp, color: (data.margin_rub || 0) > 0 ? 'text-emerald-600 bg-emerald-50' : 'text-red-600 bg-red-50' },
    { label: 'Новый фидбек', value: data.pending_feedbacks, icon: MessageCircle, color: data.pending_feedbacks > 0 ? 'text-red-600 bg-red-50' : 'text-surface-500 bg-surface-100' },
    { label: 'Активных инвайтов', value: data.active_invites, icon: Ticket, color: 'text-teal-600 bg-teal-50' },
    { label: 'Активаций инвайтов', value: data.total_invite_activations, icon: Gift, color: 'text-pink-600 bg-pink-50' },
  ]

  const cards24h = [
    { label: 'Оплат (успешно/попыток)', value: `${data.payments_24h || 0} из ${data.payment_attempts_24h || 0}`, icon: CreditCard, color: 'text-emerald-600 bg-emerald-50', detail: (data.payment_attempts_24h || 0) > 0 ? `${Math.round((data.payments_24h || 0) / (data.payment_attempts_24h || 1) * 100)}% конверсия` : null },
    { label: 'Выручка', value: fmtRub(data.revenue_24h_rub), icon: TrendingUp, color: 'text-emerald-600 bg-emerald-50' },
    { label: 'Дел сгенерировано', value: data.completed_cases_24h || 0, icon: FileText, color: 'text-blue-600 bg-blue-50' },
    { label: 'Ошибок', value: data.errors_24h || 0, icon: AlertTriangle, color: (data.errors_24h || 0) > 0 ? 'text-red-600 bg-red-50' : 'text-emerald-600 bg-emerald-50' },
    { label: 'Зависших', value: data.stuck_cases || 0, icon: Activity, color: (data.stuck_cases || 0) > 0 ? 'text-red-600 bg-red-50' : 'text-emerald-600 bg-emerald-50' },
    { label: 'Новых юзеров', value: data.new_users_24h || 0, icon: Users, color: 'text-violet-600 bg-violet-50' },
    { label: '< 10 мин', value: data.fast_cases_24h || 0, icon: Zap, color: 'text-emerald-600 bg-emerald-50' },
    { label: '> 10 мин', value: data.slow_cases_24h || 0, icon: Timer, color: (data.slow_cases_24h || 0) > 0 ? 'text-amber-600 bg-amber-50' : 'text-surface-500 bg-surface-100' },
  ]

  return (
    <div className="space-y-6">
      {/* Date filter */}
      <div className="flex flex-wrap items-center gap-2 bg-surface-50 rounded-lg p-3">
        <Calendar size={16} className="text-surface-400" />
        <input type="date" value={dateFrom} onChange={e => setDateFrom(e.target.value)} className="input py-1 px-2 text-sm w-36" />
        <span className="text-surface-400 text-sm">&mdash;</span>
        <input type="date" value={dateTo} onChange={e => setDateTo(e.target.value)} className="input py-1 px-2 text-sm w-36" />
        <button onClick={handleFilter} className="btn-primary py-1 px-3 text-sm">Показать</button>
        {(dateFrom || dateTo) && <button onClick={handleReset} className="text-sm text-surface-500 hover:text-surface-700">Сбросить</button>}
        {data.date_from && <span className="text-xs text-surface-400 ml-2">Фильтр: {data.date_from} &mdash; {data.date_to || 'сегодня'}</span>}
      </div>

      <div>
        <h3 className="text-sm font-semibold text-surface-600 mb-2 flex items-center gap-1.5"><Clock size={14} /> За сегодня (НСК)</h3>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2 sm:gap-3">
          {cards24h.map(({ label, value, icon: Icon, color, detail }) => (
            <div key={label} className="card p-3 sm:p-4 border-l-2 border-brand-400">
              <div className={`w-8 h-8 sm:w-9 sm:h-9 rounded-lg flex items-center justify-center mb-2 sm:mb-3 ${color}`}>
                <Icon size={16} />
              </div>
              <div className="text-lg sm:text-2xl font-bold">{value}</div>
              <div className="text-[11px] sm:text-xs text-surface-500 mt-0.5 sm:mt-1">{label}</div>
              {detail && <div className="text-[10px] text-surface-400 mt-0.5">{detail}</div>}
            </div>
          ))}
        </div>
      </div>

      <div>
        <h3 className="text-sm font-semibold text-surface-600 mb-2">{dateFrom || dateTo ? 'За период' : 'Всего'}</h3>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2 sm:gap-3">
          {cards.map(({ label, value, icon: Icon, color }) => (
            <div key={label} className="card p-3 sm:p-4">
              <div className={`w-8 h-8 sm:w-9 sm:h-9 rounded-lg flex items-center justify-center mb-2 sm:mb-3 ${color}`}>
                <Icon size={16} />
              </div>
              <div className="text-lg sm:text-2xl font-bold">{value}</div>
              <div className="text-[11px] sm:text-xs text-surface-500 mt-0.5 sm:mt-1">{label}</div>
            </div>
          ))}
        </div>
      </div>

      {/* System check */}
      <SystemCheck />
    </div>
  )
}

function SystemCheck() {
  const [checks, setChecks] = useState(null)
  const [loading, setLoading] = useState(false)

  const runCheck = () => {
    setLoading(true)
    setChecks(null)
    fetch('/api/admin/system-check', { credentials: 'include' })
      .then(r => r.json())
      .then(setChecks)
      .catch(() => setChecks({ status: 'error', checks: [{ name: 'API', status: 'error', detail: 'Не удалось подключиться' }] }))
      .finally(() => setLoading(false))
  }

  const icon = (s) => s === 'ok' ? <CheckCircle size={16} className="text-emerald-500" /> : s === 'warning' ? <AlertTriangle size={16} className="text-amber-500" /> : <XCircle size={16} className="text-red-500" />

  return (
    <div>
      <div className="flex items-center gap-3 mb-3">
        <h3 className="text-sm font-semibold text-surface-600">Проверка системы</h3>
        <button onClick={runCheck} disabled={loading} className="btn-primary py-1 px-3 text-xs flex items-center gap-1.5">
          <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
          {loading ? 'Проверяю...' : 'Проверить'}
        </button>
      </div>
      {checks && (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2">
          {checks.checks.map(c => (
            <div key={c.name} className={`card p-3 flex items-start gap-2 ${c.status === 'error' ? 'border-red-200 bg-red-50' : c.status === 'warning' ? 'border-amber-200 bg-amber-50' : ''}`}>
              {icon(c.status)}
              <div>
                <div className="text-xs font-medium">{c.name}</div>
                {c.detail && <div className="text-[10px] text-surface-400 mt-0.5">{c.detail}</div>}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
