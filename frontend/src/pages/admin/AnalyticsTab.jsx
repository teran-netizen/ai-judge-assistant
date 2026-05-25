import React, { useEffect, useState } from 'react'
import api from '../../api'
import { Spinner, ErrorMsg } from '../AdminPage'

const PERIODS = [
  { label: '24ч', days: 1 },
  { label: '7 дн', days: 7 },
  { label: '14 дн', days: 14 },
  { label: '30 дн', days: 30 },
]

export default function AnalyticsTab() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [period, setPeriod] = useState(14)

  useEffect(() => {
    setLoading(true)
    api.getAdminAnalytics(period)
      .then(setData)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [period])

  if (loading) return <Spinner />
  if (error) return <ErrorMsg text={error} />

  const { funnel, retention, top_terms, hourly, unit_economics: ue, top_refiners, channels } = data

  const maxHourlyCases = Math.max(...hourly.map(h => h.cases), 1)

  // Calculate totals from funnel
  const funnelTotals = funnel.reduce((acc, d) => ({
    reg: acc.reg + d.registrations,
    uploads: acc.uploads + d.uploads,
    completed: acc.completed + d.completed,
    errors: acc.errors + d.errors,
    payments: acc.payments + d.payments,
    revenue: acc.revenue + d.revenue,
    cost: acc.cost + d.cost,
    profit: acc.profit + d.profit,
  }), { reg: 0, uploads: 0, completed: 0, errors: 0, payments: 0, revenue: 0, cost: 0, profit: 0 })

  const pct = (a, b) => b > 0 ? `${Math.round(a / b * 100)}%` : '—'

  return (
    <div className="space-y-6">

      {/* Period selector */}
      <div className="flex items-center gap-2">
        {PERIODS.map(p => (
          <button key={p.days} onClick={() => setPeriod(p.days)}
            className={`text-xs px-3 py-1.5 rounded-full border transition-colors ${
              period === p.days ? 'bg-brand-600 text-white border-brand-600' : 'bg-white text-surface-600 border-surface-200 hover:border-brand-300'
            }`}>
            {p.label}
          </button>
        ))}
      </div>

      {/* Unit economics — 2 rows x 4 cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        <UEcard value={ue.total_users?.toLocaleString('ru')} label="Всего юзеров" />
        <UEcard value={ue.total_completed?.toLocaleString('ru')} label="Генераций" sub={`${ue.conversion_to_completed}% к рег.`} />
        <UEcard value={`${ue.total_revenue?.toLocaleString('ru')} ₽`} label="Выручка" color="text-emerald-600" />
        <UEcard value={ue.total_payments} label="Оплат" sub={`${ue.conversion_to_payment}% к рег.`} />
        <UEcard value={`${ue.total_cost?.toLocaleString('ru')} ₽`} label="Себестоимость" color="text-orange-600" />
        <UEcard value={`${ue.total_profit?.toLocaleString('ru')} ₽`} label="Маржа" color={ue.total_profit > 0 ? 'text-emerald-600' : 'text-red-600'} sub={`${ue.margin_pct}%`} />
        <UEcard value={`${funnelTotals.revenue.toLocaleString('ru')} ₽`} label="Выручка (период)" color="text-emerald-600" />
        <UEcard value={`${funnelTotals.profit.toLocaleString('ru')} ₽`} label="Маржа (период)" color={funnelTotals.profit > 0 ? 'text-emerald-600' : 'text-red-600'} />
      </div>

      {/* Funnel by days */}
      <div className="card p-4 overflow-x-auto">
        <div className="text-sm font-medium text-surface-700 mb-3">Воронка по дням</div>
        <div className="text-xs text-surface-400 mb-2">
          Рег → Загрузка ({pct(funnelTotals.uploads, funnelTotals.reg)}) →
          Генерация ({pct(funnelTotals.completed, funnelTotals.reg)}) →
          Оплата ({pct(funnelTotals.payments, funnelTotals.reg)})
        </div>
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-surface-200 text-surface-500">
              <th className="pb-2 text-left">Дата</th>
              <th className="pb-2 text-right">Рег.</th>
              <th className="pb-2 text-right">Загр.</th>
              <th className="pb-2 text-right">Ген.</th>
              <th className="pb-2 text-right">Ош.</th>
              <th className="pb-2 text-right">Оплат</th>
              <th className="pb-2 text-right">Выр.</th>
              <th className="pb-2 text-right">Себ.</th>
              <th className="pb-2 text-right">Маржа</th>
            </tr>
          </thead>
          <tbody>
            {funnel.filter(d => d.registrations > 0 || d.completed > 0 || d.payments > 0).map(d => (
              <tr key={d.date} className="border-b border-surface-50 hover:bg-surface-50">
                <td className="py-1.5 font-mono">{d.date.slice(5)}</td>
                <td className="py-1.5 text-right font-bold">{d.registrations}</td>
                <td className="py-1.5 text-right">{d.uploads || '—'}</td>
                <td className="py-1.5 text-right text-emerald-600 font-medium">{d.completed || '—'}</td>
                <td className="py-1.5 text-right text-red-500">{d.errors || '—'}</td>
                <td className="py-1.5 text-right font-bold text-brand-600">{d.payments || '—'}</td>
                <td className="py-1.5 text-right text-emerald-700">{d.revenue ? d.revenue.toLocaleString('ru') + ' ₽' : '—'}</td>
                <td className="py-1.5 text-right text-orange-600">{d.cost ? d.cost.toLocaleString('ru') + ' ₽' : '—'}</td>
                <td className={`py-1.5 text-right font-medium ${d.profit > 0 ? 'text-emerald-600' : d.profit < 0 ? 'text-red-500' : 'text-surface-400'}`}>{d.profit ? d.profit.toLocaleString('ru') + ' ₽' : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Top refiners */}
      {top_refiners?.length > 0 && (
        <div className="card p-4">
          <div className="text-sm font-medium text-surface-700 mb-3">Топ по доработкам (за {period} дн)</div>
          <div className="space-y-1.5">
            {top_refiners.map((r, i) => (
              <div key={i} className="flex items-center gap-3 text-xs py-1 border-b border-surface-50 last:border-0">
                <span className="text-surface-400 w-5">{i + 1}.</span>
                <span className="flex-1 truncate">{r.name}</span>
                <span className="font-bold text-brand-600">{r.refine_count} дораб.</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Channel breakdown */}
      {channels?.length > 0 && (
        <div className="card p-4">
          <div className="text-sm font-medium text-surface-700 mb-3">Каналы трафика (за {period} дн)</div>
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-surface-200 text-surface-500">
                <th className="pb-2 text-left">Канал</th>
                <th className="pb-2 text-right">Рег.</th>
                <th className="pb-2 text-right">Ген.</th>
                <th className="pb-2 text-right">Оплат</th>
                <th className="pb-2 text-right">Выручка</th>
                <th className="pb-2 text-right">Конв.</th>
                <th className="pb-2 text-right">Выр/рег</th>
              </tr>
            </thead>
            <tbody>
              {channels.filter(ch => ch.registrations > 0).map(ch => {
                const labelMap = {
                  'yandex/cpc': 'Яндекс.Директ',
                  'yandex/organic': 'Яндекс SEO',
                  'google/cpc': 'Google Ads',
                  'google/organic': 'Google SEO',
                  'vk/referral': 'VK',
                  'organic/seo': 'SEO / прямые',
                  'direct/none': 'Прямой',
                }
                const label = labelMap[ch.channel] || ch.channel
                const conv = ch.registrations > 0 ? Math.round(ch.payments / ch.registrations * 100) : 0
                const revenuePerReg = ch.registrations > 0 ? Math.round(ch.revenue / ch.registrations) : 0
                const totalRevenue = funnel.reduce((s, d) => s + d.revenue, 0)
                const share = totalRevenue > 0 ? Math.round(ch.revenue / totalRevenue * 100) : 0
                return (
                  <tr key={ch.channel} className="border-b border-surface-50 hover:bg-surface-50">
                    <td className="py-1.5">{label}
                      <span className="text-surface-400 ml-1">{share > 0 ? `(${share}%)` : ''}</span>
                    </td>
                    <td className="py-1.5 text-right font-bold">{ch.registrations}</td>
                    <td className="py-1.5 text-right text-emerald-600">{ch.completed || '—'}</td>
                    <td className="py-1.5 text-right font-bold text-brand-600">{ch.payments || '—'}</td>
                    <td className="py-1.5 text-right text-emerald-700">{ch.revenue ? ch.revenue.toLocaleString('ru') + ' ₽' : '—'}</td>
                    <td className="py-1.5 text-right">{conv > 0 ? <span className="text-emerald-600">{conv}%</span> : '—'}</td>
                    <td className="py-1.5 text-right text-surface-500">{revenuePerReg > 0 ? revenuePerReg + ' ₽' : '—'}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Retention */}
      <div className="card p-4">
        <div className="text-sm font-medium text-surface-700 mb-3">Retention (когорты)</div>
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-surface-200 text-surface-500">
              <th className="pb-2 text-left">Когорта</th>
              <th className="pb-2 text-right">Размер</th>
              <th className="pb-2 text-right">D1</th>
              <th className="pb-2 text-right">D2</th>
              <th className="pb-2 text-right">D3</th>
            </tr>
          </thead>
          <tbody>
            {retention.filter(r => r.size > 0).map(r => (
              <tr key={r.date} className="border-b border-surface-50">
                <td className="py-1.5 font-mono">{r.date.slice(5)}</td>
                <td className="py-1.5 text-right font-bold">{r.size}</td>
                <td className="py-1.5 text-right">
                  {r.d1 > 0 ? <span className="text-emerald-600 font-medium">{r.d1} ({Math.round(r.d1/r.size*100)}%)</span> : '—'}
                </td>
                <td className="py-1.5 text-right">
                  {r.d2 > 0 ? <span className="text-emerald-600 font-medium">{r.d2} ({Math.round(r.d2/r.size*100)}%)</span> : '—'}
                </td>
                <td className="py-1.5 text-right">
                  {r.d3 > 0 ? <span className="text-emerald-600 font-medium">{r.d3} ({Math.round(r.d3/r.size*100)}%)</span> : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Hourly activity */}
      <div className="card p-4">
        <div className="text-sm font-medium text-surface-700 mb-3">Активность по часам (UTC)</div>
        <div className="flex items-end gap-0.5 h-24">
          {hourly.map(h => (
            <div key={h.hour} className="flex-1 flex flex-col items-center gap-0.5">
              <div
                className="w-full bg-brand-500 rounded-t"
                style={{ height: `${Math.max(2, (h.cases / maxHourlyCases) * 80)}px` }}
                title={`${h.hour}:00 — ${h.cases} дел`}
              />
              <span className="text-[9px] text-surface-400">{h.hour}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Top search terms — with revenue */}
      <div className="card p-4">
        <div className="text-sm font-medium text-surface-700 mb-3">Источники трафика (по UTM term, за {period} дн)</div>
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-surface-200 text-surface-500">
              <th className="pb-2 text-left w-6">#</th>
              <th className="pb-2 text-left">Запрос / страница</th>
              <th className="pb-2 text-right">Рег.</th>
              <th className="pb-2 text-right">Ген.</th>
              <th className="pb-2 text-right">Оплат</th>
              <th className="pb-2 text-right">Выручка</th>
              <th className="pb-2 text-right">Конв.</th>
            </tr>
          </thead>
          <tbody>
            {top_terms.filter(t => t.registrations > 0).map((t, i) => (
              <tr key={i} className="border-b border-surface-50 hover:bg-surface-50">
                <td className="py-1.5 text-surface-400">{i + 1}</td>
                <td className="py-1.5 font-mono truncate max-w-[200px]" title={t.term}>
                  {t.term === '(no term)' ? '(без UTM метки)' : t.term === '(без запроса)' ? '(без запроса)' : decodeURIComponent((t.term || '').replace(/\+/g, ' '))}
                </td>
                <td className="py-1.5 text-right font-bold">{t.registrations}</td>
                <td className="py-1.5 text-right text-emerald-600">{t.completed || '—'}</td>
                <td className="py-1.5 text-right font-bold text-brand-600">{t.payments || '—'}</td>
                <td className="py-1.5 text-right text-emerald-700">{t.revenue ? t.revenue.toLocaleString('ru') + ' ₽' : '—'}</td>
                <td className="py-1.5 text-right">
                  {t.registrations > 0 && t.payments > 0
                    ? <span className="text-emerald-600">{Math.round(t.payments / t.registrations * 100)}%</span>
                    : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

    </div>
  )
}

function UEcard({ value, label, sub, color }) {
  return (
    <div className="card p-3">
      <div className={`text-2xl font-bold ${color || ''}`}>{value}</div>
      <div className="text-xs text-surface-500">{label}</div>
      {sub && <div className="text-[10px] text-surface-400">{sub}</div>}
    </div>
  )
}
