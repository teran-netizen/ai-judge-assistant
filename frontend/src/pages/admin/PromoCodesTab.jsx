import { useState, useEffect } from 'react'
import { Ticket, Users, Calendar, ChevronDown, ChevronUp, CheckCircle } from 'lucide-react'
import api from '../../api'

export default function PromoCodesTab() {
  const [data, setData] = useState(null)
  const [expanded, setExpanded] = useState(null)

  useEffect(() => {
    api.getAdminInviteStats().then(setData).catch(() => {})
  }, [])

  if (!data) return <div className="p-6 text-center text-surface-400">Загрузка...</div>

  return (
    <div className="p-4 space-y-4">
      {data.map(inv => {
        const isExp = expanded === inv.code
        const pct = inv.max_activations > 0 ? Math.round(inv.activated_count / inv.max_activations * 100) : 0
        return (
          <div key={inv.code} className="card overflow-hidden">
            <div
              className="p-4 flex items-center gap-3 cursor-pointer hover:bg-surface-50"
              onClick={() => setExpanded(isExp ? null : inv.code)}
            >
              <Ticket size={20} className={inv.is_active ? 'text-brand-600' : 'text-surface-300'} />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="font-mono font-bold text-sm">{inv.code}</span>
                  {!inv.is_active && <span className="text-[10px] px-1.5 py-0.5 rounded bg-red-100 text-red-600">неактивен</span>}
                  {inv.expires_at && <span className="text-[10px] text-surface-400">до {inv.expires_at.slice(0, 10)}</span>}
                </div>
                {inv.label && <div className="text-xs text-surface-500 mt-0.5">{inv.label}</div>}
              </div>
              <div className="text-right shrink-0">
                <div className="text-sm font-bold">{inv.activated_count} <span className="text-surface-400 font-normal">/ {inv.max_activations}</span></div>
                <div className="text-[10px] text-surface-400">+{inv.bonus_free_cases} дел</div>
              </div>
              <div className="w-16">
                <div className="w-full h-1.5 bg-surface-100 rounded-full overflow-hidden">
                  <div className="h-full bg-brand-500 rounded-full" style={{ width: `${Math.min(100, pct)}%` }} />
                </div>
                <div className="text-[10px] text-surface-400 text-center mt-0.5">{pct}%</div>
              </div>
              {isExp ? <ChevronUp size={16} className="text-surface-400" /> : <ChevronDown size={16} className="text-surface-400" />}
            </div>

            {isExp && (
              <div className="border-t border-surface-100 bg-surface-50 p-4">
                {inv.activations.length === 0 ? (
                  <div className="text-sm text-surface-400 text-center py-2">Пока никто не активировал</div>
                ) : (
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-[11px] text-surface-500">
                        <th className="text-left pb-2">Юзер</th>
                        <th className="text-left pb-2">Бонус</th>
                        <th className="text-left pb-2">Дата</th>
                      </tr>
                    </thead>
                    <tbody>
                      {inv.activations.map((a, i) => (
                        <tr key={i} className="border-t border-surface-100">
                          <td className="py-1.5">
                            <span className="text-surface-400 text-xs">#{a.user_display_id}</span>{' '}
                            <span className="font-medium">{a.user_name}</span>
                          </td>
                          <td className="py-1.5 text-emerald-600">+{a.bonus_free_cases} дел</td>
                          <td className="py-1.5 text-surface-500 text-xs">{a.activated_at ? a.activated_at.slice(0, 16).replace('T', ' ') : '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            )}
          </div>
        )
      })}
      {data.length === 0 && <div className="text-center text-surface-400 py-8">Промокодов пока нет</div>}
    </div>
  )
}
