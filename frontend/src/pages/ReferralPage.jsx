import { useState, useEffect } from 'react'
import { useAuth } from '../hooks/useAuth'
import { Copy, Check, Users, CreditCard, Share2, TrendingUp, Send, UserCheck, Gift, Clock } from 'lucide-react'
import api from '../api'

const TG_ICON = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
    <path d="M12 0C5.373 0 0 5.373 0 12s5.373 12 12 12 12-5.373 12-12S18.627 0 12 0zm5.894 8.221-1.97 9.28c-.145.658-.537.818-1.084.508l-3-2.21-1.447 1.394c-.16.16-.295.295-.605.295l.213-3.053 5.56-5.023c.242-.213-.054-.333-.373-.12l-6.871 4.326-2.962-.924c-.643-.204-.657-.643.136-.953l11.57-4.461c.537-.194 1.006.131.833.941z"/>
  </svg>
)
const WA_ICON = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
    <path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347zM12 0C5.373 0 0 5.373 0 12c0 2.123.554 4.117 1.528 5.845L.057 23.5l5.797-1.522A11.95 11.95 0 0 0 12 24c6.627 0 12-5.373 12-12S18.627 0 12 0zm0 21.818a9.797 9.797 0 0 1-5.003-1.373l-.359-.214-3.72.977.993-3.628-.234-.373A9.772 9.772 0 0 1 2.182 12C2.182 6.57 6.57 2.182 12 2.182S21.818 6.57 21.818 12 17.43 21.818 12 21.818z"/>
  </svg>
)
const VK_ICON = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
    <path d="M15.684 0H8.316C1.592 0 0 1.592 0 8.316v7.368C0 22.408 1.592 24 8.316 24h7.368C22.408 24 24 22.408 24 15.684V8.316C24 1.592 22.408 0 15.684 0zm3.692 17.123h-1.744c-.66 0-.864-.525-2.05-1.727-1.033-1-1.49-1.135-1.744-1.135-.356 0-.458.102-.458.593v1.575c0 .424-.135.678-1.253.678-1.846 0-3.896-1.118-5.335-3.202C4.624 10.857 4.03 8.57 4.03 8.096c0-.254.102-.491.593-.491h1.744c.44 0 .61.203.78.677.847 2.456 2.27 4.606 2.862 4.606.22 0 .322-.102.322-.66V9.721c-.068-1.186-.695-1.287-.695-1.71 0-.204.17-.407.44-.407h2.744c.373 0 .508.203.508.643v3.473c0 .372.17.508.271.508.22 0 .407-.136.813-.542 1.253-1.406 2.15-3.574 2.15-3.574.119-.254.339-.491.78-.491h1.744c.525 0 .644.27.525.643-.22 1.017-2.354 4.031-2.354 4.031-.186.305-.254.44 0 .78.186.254.796.779 1.203 1.253.745.847 1.32 1.558 1.473 2.05.17.49-.085.745-.576.745z"/>
  </svg>
)
const EMAIL_ICON = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <rect x="2" y="4" width="20" height="16" rx="2"/>
    <path d="m2 7 10 7 10-7"/>
  </svg>
)
const MAX_ICON = () => (



  <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
    <defs>
      <linearGradient id="maxGrad" x1="0" y1="0" x2="24" y2="24" gradientUnits="userSpaceOnUse">
        <stop offset="0%" stopColor="#6366f1"/>
        <stop offset="50%" stopColor="#8b5cf6"/>
        <stop offset="100%" stopColor="#06b6d4"/>
      </linearGradient>
    </defs>
    <path d="M12 2C6.48 2 2 5.82 2 10.5c0 2.83 1.74 5.33 4.4 6.87L5 22l4.3-2.15c.88.2 1.78.3 2.7.3 5.52 0 10-3.82 10-8.5S17.52 2 12 2z" fill="url(#maxGrad)"/>
  </svg>
)

const SHARE_CHANNELS = [
  { label: 'Telegram', color: '#2AABEE', Icon: TG_ICON,
    getUrl: (url, text) => `https://t.me/share/url?url=${encodeURIComponent(url)}&text=${encodeURIComponent(text)}` },
  { label: 'WhatsApp', color: '#25D366', Icon: WA_ICON,
    getUrl: (url, text) => `https://wa.me/?text=${encodeURIComponent(text + ' ' + url)}` },
  { label: 'VK', color: '#4680C2', Icon: VK_ICON,
    getUrl: (url, text) => `https://vk.com/share.php?url=${encodeURIComponent(url)}&title=${encodeURIComponent(text)}` },
  { label: 'Max', color: 'linear-gradient(135deg, #6366f1, #8b5cf6, #06b6d4)', Icon: MAX_ICON,
    getUrl: (url, text) => `https://connect.mail.ru/share?url=${encodeURIComponent(url)}&title=${encodeURIComponent(text)}` },
  { label: 'Email', color: '#6B7280', Icon: EMAIL_ICON,
    getUrl: (url, text) => `mailto:?subject=${encodeURIComponent(text)}&body=${encodeURIComponent(url)}` },
]

export default function ReferralPage() {
  const { user } = useAuth()
  const [stats, setStats] = useState(null)
  const [copied, setCopied] = useState(false)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    try { api.trackAction("page_referral") } catch {}
    api.getReferralStats().then(setStats).catch(() => {}).finally(() => setLoading(false))
  }, [])

  const refCode = stats?.ref_code || (user?.id ? String(user.id).replace(/-/g, '').slice(0, 8) : '')
  const publicOrigin = typeof window !== 'undefined' ? window.location.origin : 'https://example.com'
  const refUrl = stats?.ref_url || (refCode ? `${publicOrigin}/login?ref=${refCode}` : '')
  const shareText = 'ИИ Помощник Судьи — проект решения суда за 5 минут. Попробуйте по моей ссылке:'

  const handleCopy = async () => {
    let ok = false
    if (navigator.clipboard && navigator.clipboard.writeText) {
      try { await navigator.clipboard.writeText(refUrl); ok = true } catch {}
    }
    if (!ok) {
      const ta = document.createElement('textarea')
      ta.value = refUrl
      ta.style.cssText = 'position:fixed;top:0;left:0;width:2em;height:2em;padding:0;border:none;outline:none;opacity:0'
      document.body.appendChild(ta)
      ta.focus()
      ta.setSelectionRange(0, ta.value.length)
      try { document.execCommand('copy'); ok = true } catch {}
      document.body.removeChild(ta)
    }
    if (ok) {
      setCopied(true)
      api.trackReferralCopy().catch(() => {})
      setTimeout(() => setCopied(false), 2000)
    }
  }

  const handleNativeShare = async () => {
    if (navigator.share) {
      try {
        await navigator.share({ title: 'ИИ Помощник Судьи', text: shareText, url: refUrl })
        api.trackReferralCopy().catch(() => {})
      } catch {}
    }
  }

  const cards = [
    { label: 'Зарегистрировалось', value: stats?.signups || 0, icon: Users, color: 'text-blue-600' },
    { label: 'Оплатили', value: stats?.conversions || 0, icon: CreditCard, color: 'text-emerald-600' },
    { label: 'Бонусных дел', value: stats?.bonus_cases_earned || 0, icon: TrendingUp, color: 'text-violet-600' },
  ]

  return (
    <div className="max-w-2xl mx-auto p-4 sm:p-6">
      <div className="mb-6">
        <h1 className="text-xl font-display font-bold flex items-center gap-2">
          <Share2 size={22} className="text-brand-600" />
          Пригласите коллегу
        </h1>
        <p className="text-surface-500 text-sm mt-1">
          Поделитесь ссылкой — вы оба получите по 3 бесплатных дела после первой оплаты приглашённого
        </p>
      </div>

      {/* Referral link */}
      <div className="card p-5 mb-4 border-brand-200 bg-gradient-to-br from-brand-50 to-white">
        <div className="text-xs text-surface-500 mb-2 font-medium">Ваша ссылка</div>
        <div className="bg-white border border-surface-200 rounded-lg px-3 py-2 text-sm font-mono text-surface-700 break-all mb-3 select-all">
          {refUrl}
        </div>
        <div className="flex gap-2">
          <button
            onClick={handleCopy}
            className="btn-primary flex-1 py-2.5 flex items-center justify-center gap-1.5 text-sm"
          >
            {copied ? <><Check size={16} /> Скопировано</> : <><Copy size={16} /> Копировать</>}
          </button>
          {'share' in navigator && (
            <button
              onClick={handleNativeShare}
              title="Поделиться"
              className="py-2.5 px-4 flex items-center justify-center gap-1.5 text-sm border border-surface-200 rounded-lg hover:bg-surface-50 transition-colors"
            >
              <Send size={16} />
            </button>
          )}
        </div>
      </div>

      {/* Share buttons */}
      <div className="card p-4 mb-6">
        <div className="text-xs text-surface-500 mb-3 font-medium">Поделиться в мессенджере</div>
        <div className="flex flex-wrap gap-2">
          {SHARE_CHANNELS.map(({ label, color, Icon, getUrl }) => (
            <a
              key={label}
              href={getUrl(refUrl, shareText)}
              target="_blank"
              rel="noopener noreferrer"
              onClick={() => (() => { try { api.trackAction('referral_share_' + label.toLowerCase()) } catch {} })()}
              className="flex items-center gap-2 px-3 py-2 rounded-lg text-white text-sm font-medium transition-opacity hover:opacity-85"
              style={{ background: color }}
            >
              <Icon />
              {label}
            </a>
          ))}
        </div>
      </div>

      {/* How it works */}
      <div className="card p-5 mb-6">
        <div className="text-sm font-semibold mb-3">Как это работает</div>
        <div className="space-y-3 text-sm text-surface-600">
          <div className="flex items-start gap-3">
            <div className="w-6 h-6 rounded-full bg-brand-100 text-brand-700 flex items-center justify-center text-xs font-bold shrink-0">1</div>
            <div>Отправьте ссылку коллеге</div>
          </div>
          <div className="flex items-start gap-3">
            <div className="w-6 h-6 rounded-full bg-brand-100 text-brand-700 flex items-center justify-center text-xs font-bold shrink-0">2</div>
            <div>Коллега регистрируется по вашей ссылке</div>
          </div>
          <div className="flex items-start gap-3">
            <div className="w-6 h-6 rounded-full bg-brand-100 text-brand-700 flex items-center justify-center text-xs font-bold shrink-0">3</div>
            <div>После первой оплаты — вы оба получаете по <span className="font-bold text-brand-700">3 бесплатных дела</span></div>
          </div>
        </div>
      </div>

      {/* Stats */}
      {!loading && (
        <>
          <div className="grid grid-cols-3 gap-3 mb-4">
            {cards.map(c => (
              <div key={c.label} className="card p-4 text-center">
                <c.icon size={20} className={`mx-auto mb-1.5 ${c.color}`} />
                <div className="text-2xl font-bold">{c.value}</div>
                <div className="text-xs text-surface-500 mt-0.5 leading-tight">{c.label}</div>
              </div>
            ))}
          </div>

          {/* Referred users list */}
          {stats?.referred?.length > 0 ? (
            <div className="card p-4">
              <div className="text-sm font-semibold mb-3 flex items-center gap-2">
                <UserCheck size={16} className="text-brand-600" />
                Ваши рефералы
              </div>
              <div className="space-y-2">
                {stats.referred.map((r, i) => (
                  <div key={i} className="flex items-center justify-between py-2 border-b border-surface-50 last:border-0">
                    <div className="flex items-center gap-2.5">
                      <div className="w-7 h-7 rounded-full bg-brand-100 flex items-center justify-center text-xs font-bold text-brand-700">
                        {r.name?.[0]?.toUpperCase() || '?'}
                      </div>
                      <div>
                        <div className="text-sm font-medium">{r.name}</div>
                        <div className="text-[11px] text-surface-400 flex items-center gap-1">
                          <Clock size={10} />
                          {r.registered_at ? new Date(r.registered_at).toLocaleDateString('ru', { day: 'numeric', month: 'short' }) : ''}
                        </div>
                      </div>
                    </div>
                    {r.status === 'bonus_paid' ? (
                      <span className="flex items-center gap-1 text-[11px] font-medium text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded-full">
                        <Gift size={11} />
                        Бонус получен
                      </span>
                    ) : (
                      <span className="text-[11px] text-surface-400 bg-surface-100 px-2 py-0.5 rounded-full">
                        Зарегистрирован
                      </span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div className="card p-5 text-center text-surface-400">
              <Users size={28} className="mx-auto mb-2 text-surface-300" />
              <div className="text-sm">Пока никто не зарегистрировался по вашей ссылке</div>
              <div className="text-xs mt-1">Поделитесь ссылкой с коллегами выше</div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
