import { useState, useEffect } from 'react'
import { Users, CreditCard, Share2, TrendingUp, ArrowUpDown, ChevronDown, ChevronRight } from 'lucide-react'
import api from '../../api'

export default function ReferralsTab() {
  const [data, setData] = useState(null)
  const [sortKey, setSortKey] = useState('signups')
  const [sortDir, setSortDir] = useState('desc')
  const [expanded, setExpanded] = useState(null)
  const [referredCache, setReferredCache] = useState({})

  useEffect(() => {
    api.getAdminReferralStats().then(setData).catch(() => {})
  }, [])

  const toggleExpand = async (referrerId) => {
    if (expanded === referrerId) {
      setExpanded(null)
      return
    }
    setExpanded(referrerId)
    if (!referredCache[referrerId]) {
      try {
        const result = await api.getAdminReferredUsers(referrerId)
        setReferredCache(prev => ({ ...prev, [referrerId]: result.referred || [] }))
      } catch {
        setReferredCache(prev => ({ ...prev, [referrerId]: [] }))
      }
    }
  }

  const statusLabels = {
    registered: 'Зарегистрирован',
    converted: 'Оплатил',
    bonus_paid: 'Бонус начислен',
  }
  const statusColors = {
    registered: 'text-surface-500',
    converted: 'text-amber-600',
    bonus_paid: 'text-emerald-600',
  }

  if (!data) return <div className="p-6 text-center text-surface-400">Загрузка...</div>

  const t = data.totals
  const cards = [
    { label: 'Регистраций', value: t.total_signups, sub: `${t.signups_24h} за 24ч`, icon: Users, color: 'text-blue-600 bg-blue-50' },
    { label: 'Конверсий', value: t.total_conversions, sub: `${t.conversions_24h} за 24ч`, icon: CreditCard, color: 'text-emerald-600 bg-emerald-50' },
    { label: 'Копирований', value: t.total_link_copies, icon: Share2, color: 'text-amber-600 bg-amber-50' },
    { label: 'Конверсия', value: `${t.conversion_rate}%`, icon: TrendingUp, color: 'text-violet-600 bg-violet-50' },
  ]

  const toggleSort = (key) => {
    if (sortKey === key) setSortDir(d => d === 'desc' ? 'asc' : 'desc')
    else { setSortKey(key); setSortDir('desc') }
  }

  const sorted = [...(data.leaderboard || [])].sort((a, b) => {
    const m = sortDir === 'desc' ? -1 : 1
    return (a[sortKey] - b[sortKey]) * m
  })

  const SortHeader = ({ k, children }) => (
    <th className="px-3 py-2 text-left text-[11px] font-medium text-surface-500 cursor-pointer hover:text-surface-700 select-none" onClick={() => toggleSort(k)}>
      <span className="flex items-center gap-1">{children} {sortKey === k && <ArrowUpDown size={12} />}</span>
    </th>
  )

  return (
    <div className="p-4">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
        {cards.map(c => (
          <div key={c.label} className="card p-4">
            <div className="flex items-center gap-2 mb-1">
              <div className={`p-1.5 rounded-lg ${c.color}`}><c.icon size={16} /></div>
              <span className="text-xs text-surface-500">{c.label}</span>
            </div>
            <div className="text-xl font-bold">{c.value}</div>
            {c.sub && <div className="text-[11px] text-surface-400">{c.sub}</div>}
          </div>
        ))}
      </div>

      <div className="card overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-surface-50 border-b border-surface-100">
            <tr>
              <th className="px-3 py-2 text-left text-[11px] font-medium text-surface-500 w-8" />
              <th className="px-3 py-2 text-left text-[11px] font-medium text-surface-500 w-8">#</th>
              <th className="px-3 py-2 text-left text-[11px] font-medium text-surface-500">Юзер</th>
              <SortHeader k="signups">Регистрации</SortHeader>
              <SortHeader k="conversions">Оплатили</SortHeader>
              <SortHeader k="bonus_cases">Бонус дел</SortHeader>
              <SortHeader k="link_copies">Копирований</SortHeader>
              <SortHeader k="conversion_rate">Конверсия</SortHeader>
            </tr>
          </thead>
          <tbody>
            {sorted.map((r, i) => {
              const isExpanded = expanded === r.referrer_id
              const referred = referredCache[r.referrer_id]
              return (
                <>
                  <tr key={r.referrer_id} className="border-b border-surface-50 hover:bg-surface-50 cursor-pointer" onClick={() => toggleExpand(r.referrer_id)}>
                    <td className="px-3 py-2 text-surface-400">
                      {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                    </td>
                    <td className="px-3 py-2 text-surface-400 text-xs">{i + 1}</td>
                    <td className="px-3 py-2">
                      <div className="font-medium text-sm">{r.name}</div>
                      <div className="text-[11px] text-surface-400">#{r.display_id} {r.email}</div>
                    </td>
                    <td className="px-3 py-2 font-medium">{r.signups}</td>
                    <td className="px-3 py-2 font-medium text-emerald-600">{r.conversions}</td>
                    <td className="px-3 py-2 text-violet-600">{r.bonus_cases}</td>
                    <td className="px-3 py-2 text-surface-500">{r.link_copies}</td>
                    <td className="px-3 py-2">
                      <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${r.conversion_rate >= 30 ? 'bg-emerald-100 text-emerald-700' : r.conversion_rate > 0 ? 'bg-amber-100 text-amber-700' : 'bg-surface-100 text-surface-500'}`}>
                        {r.conversion_rate}%
                      </span>
                    </td>
                  </tr>
                  {isExpanded && (
                    <tr key={`${r.referrer_id}-expanded`} className="border-b border-surface-50 bg-surface-50">
                      <td colSpan={8} className="px-3 py-2">
                        {!referred ? (
                          <span className="text-xs text-surface-400">Загрузка...</span>
                        ) : referred.length === 0 ? (
                          <span className="text-xs text-surface-400">Нет приведённых пользователей</span>
                        ) : (
                          <table className="w-full text-xs">
                            <thead>
                              <tr className="border-b border-surface-100">
                                <th className="text-left py-1 text-surface-500 font-medium">Имя</th>
                                <th className="text-left py-1 text-surface-500 font-medium">Email</th>
                                <th className="text-left py-1 text-surface-500 font-medium">Статус</th>
                                <th className="text-left py-1 text-surface-500 font-medium">Дата</th>
                              </tr>
                            </thead>
                            <tbody>
                              {referred.map(ref => (
                                <tr key={ref.user_id} className="border-b border-surface-100/50">
                                  <td className="py-1">{ref.name || '\u2014'}</td>
                                  <td className="py-1 text-surface-500">{ref.email || '\u2014'}</td>
                                  <td className={`py-1 ${statusColors[ref.status] || 'text-surface-500'}`}>{statusLabels[ref.status] || ref.status}</td>
                                  <td className="py-1 text-surface-400">{ref.registered_at ? new Date(ref.registered_at).toLocaleDateString('ru') : '\u2014'}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        )}
                      </td>
                    </tr>
                  )}
                </>
              )
            })}
            {sorted.length === 0 && (
              <tr><td colSpan={8} className="px-3 py-8 text-center text-surface-400">Пока нет рефералов</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
