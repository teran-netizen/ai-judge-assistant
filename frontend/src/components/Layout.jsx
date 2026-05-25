import { Outlet, NavLink, useNavigate, useLocation } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'
import { useJudge } from '../hooks/JudgeContext'
import api from '../api'
import {
  CreditCard, Share2, User, LogOut, Menu, X,
  Shield, Plus, FileText, CheckCircle, AlertCircle, Loader, Scale,
  Pencil, Trash2, MessageCircle,
} from 'lucide-react'
import { useState, useEffect, useCallback, useRef } from 'react'

const nav = [
  { to: '/referral', icon: Share2, label: 'Пригласить коллегу' },
  { to: '/profile', icon: User, label: 'Профиль' },
]

const statusIcon = {
  draft: { Icon: FileText, cls: 'text-surface-500' },
  processing: { Icon: Loader, cls: 'text-amber-500 animate-spin' },
  completed: { Icon: CheckCircle, cls: 'text-emerald-500' },
  error: { Icon: AlertCircle, cls: 'text-red-500' },
}

export default function Layout() {
  const { user, logout } = useAuth()
  const { activeJudgeId, activeJudge } = useJudge()
  const [mobileOpen, setMobileOpen] = useState(false)
  const [cases, setCases] = useState([])
  const location = useLocation()
  const navigate = useNavigate()

  const refreshCases = useCallback(() => {
    api.getCases(0, 100, activeJudgeId || null).then(setCases).catch(console.error)
  }, [activeJudgeId])

  useEffect(() => {
    refreshCases()
  }, [refreshCases])

  // Refresh sidebar when navigating back from case pages
  useEffect(() => {
    refreshCases()
  }, [location.pathname, refreshCases])

  // Polling: обновлять сайдбар каждые 5 сек пока есть processing-дела
  useEffect(() => {
    if (!cases.some(c => c.status === 'processing')) return
    const interval = setInterval(refreshCases, 5000)
    return () => clearInterval(interval)
  }, [cases, refreshCases])

  const handleDeleteCase = async (caseId) => {
    const isActive = location.pathname === `/cases/${caseId}`
    try {
      await api.deleteCase(caseId)
      refreshCases()
      if (isActive) navigate('/')
    } catch (e) {
      alert(e.message)
    }
  }

  const handleRenameCase = async (caseId, newTitle) => {
    try {
      await api.renameCase(caseId, newTitle)
      refreshCases()
    } catch (e) {
      alert(e.message)
    }
  }

  return (
    <div className="flex h-dvh overflow-hidden">
      {/* Sidebar desktop */}
      <aside className="hidden lg:flex flex-col w-[280px] bg-surface-950 text-white shrink-0">
        <SidebarContent
          user={user} logout={logout} cases={cases}
          onDelete={handleDeleteCase} onRename={handleRenameCase}
          activeJudgeId={activeJudgeId} activeJudge={activeJudge}
        />
      </aside>

      {/* Mobile overlay */}
      {mobileOpen && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div className="absolute inset-0 bg-black/50" onClick={() => setMobileOpen(false)} />
          <aside className="relative flex flex-col w-72 h-full bg-surface-950 text-white animate-slide">
            <button onClick={() => setMobileOpen(false)} className="absolute top-4 right-4 text-surface-400 hover:text-white">
              <X size={20} />
            </button>
            <SidebarContent
              user={user} logout={logout} cases={cases}
              onNav={() => setMobileOpen(false)}
              onDelete={handleDeleteCase} onRename={handleRenameCase}
              activeJudgeId={activeJudgeId} activeJudge={activeJudge}
            />
          </aside>
        </div>
      )}

      {/* Main */}
      <main className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {/* Top bar mobile */}
        <header className="lg:hidden flex items-center gap-3 px-4 py-3 bg-white border-b border-surface-100">
          <button onClick={() => setMobileOpen(true)} className="text-surface-600">
            <Menu size={22} />
          </button>
          <div className="flex items-center gap-2">
            <span className="text-[22px] font-extrabold text-brand-600 tracking-tight">AI</span>
            <span className="font-display font-semibold text-lg">Помощник Судьи</span>
          </div>
        </header>

        <div className="flex-1 flex flex-col min-h-0">
          <Outlet context={{ refreshCases, activeJudgeId }} />
        </div>
      </main>
    </div>
  )
}

function SidebarContent({ user, logout, cases, onNav, onDelete, onRename, activeJudgeId, activeJudge }) {
  const navigate = useNavigate()
  const location = useLocation()
  const [renamingId, setRenamingId] = useState(null)
  const [renameValue, setRenameValue] = useState('')
  const [deletingCase, setDeletingCase] = useState(null)
  const renameInputRef = useRef(null)

  const caseTitle = (c) => c.title || `Дело от ${new Date(c.created_at).toLocaleDateString('ru')}`

  // Focus rename input
  useEffect(() => {
    if (renamingId && renameInputRef.current) {
      renameInputRef.current.focus()
      renameInputRef.current.select()
    }
  }, [renamingId])

  const startRename = (c) => {
    setRenamingId(c.id)
    setRenameValue(caseTitle(c))
  }

  const commitRename = () => {
    if (renamingId && renameValue.trim()) {
      onRename?.(renamingId, renameValue.trim())
    }
    setRenamingId(null)
    setRenameValue('')
  }

  const cancelRename = () => {
    setRenamingId(null)
    setRenameValue('')
  }

  const confirmDelete = (c) => setDeletingCase(c)
  const cancelDelete = () => setDeletingCase(null)
  const execDelete = () => {
    if (deletingCase) onDelete?.(deletingCase.id)
    setDeletingCase(null)
  }

  return (
    <>
      {/* Zone 1: Logo + New Case */}
      <div className="px-4 py-5 border-b border-white/[0.08] shrink-0">
        <div className="flex items-center gap-2 mb-4">
          <Scale size={18} className="text-brand-400" />
          <span className="text-sm font-semibold text-surface-300">Помощник Судьи</span>
        </div>
        <button
          onClick={() => { navigate('/cases/new'); onNav?.() }}
          className="flex items-center justify-center gap-2 w-full py-2.5 rounded-lg bg-brand-700 hover:bg-brand-600 text-white text-sm font-medium transition-colors"
        >
          <Plus size={18} />
          Новый документ
        </button>
      </div>

      {/* Zone 2: Cases list */}
      <div className="flex-1 overflow-y-auto px-2 py-2">
        <div className="px-3 py-2 text-[11px] text-surface-600 font-medium uppercase tracking-wider">
          Мои дела
        </div>

        {(() => {
          // Показываем завершённые + обрабатываемые дела (processing = жёлтая иконка)
          const visible = cases.filter(c => c.status === 'completed' || c.status === 'error' || c.status === 'processing' || c.status === 'draft')
          return visible.length === 0 ? (
          <div className="px-3 py-4 text-xs text-surface-600 text-center">
            Дел пока нет
          </div>
        ) : (
          <div className="space-y-0.5">
            {visible.map((c) => {
              const st = statusIcon[c.status] || statusIcon.draft
              const isActive = location.pathname === `/cases/${c.id}`
              const isRenaming = renamingId === c.id

              if (isRenaming) {
                return (
                  <div key={c.id} className="flex items-center gap-2 px-3 py-1.5">
                    <st.Icon size={14} className={`shrink-0 ${st.cls}`} />
                    <input
                      ref={renameInputRef}
                      value={renameValue}
                      onChange={e => setRenameValue(e.target.value)}
                      onKeyDown={e => {
                        if (e.key === 'Enter') commitRename()
                        if (e.key === 'Escape') cancelRename()
                      }}
                      onBlur={commitRename}
                      className="flex-1 min-w-0 bg-white/10 text-white text-sm px-2 py-1 rounded border border-white/20 outline-none focus:border-brand-400"
                    />
                  </div>
                )
              }

              return (
                <div
                  key={c.id}
                  className={`group relative flex items-center gap-2.5 w-full px-3 py-2.5 rounded-lg text-sm text-left transition-colors ${
                    isActive
                      ? 'bg-white/10 text-white font-medium'
                      : 'text-surface-400 hover:bg-white/[0.06]'
                  }`}
                >
                  <button
                    onClick={() => { navigate(`/cases/${c.id}`); onNav?.() }}
                    className="flex items-center gap-2.5 flex-1 min-w-0"
                  >
                    <st.Icon size={14} className={`shrink-0 ${st.cls}`} />
                    <span className="truncate flex-1">{caseTitle(c)}</span>
                  </button>

                  <button
                    onClick={(e) => { e.stopPropagation(); startRename(c) }}
                    className="shrink-0 p-1 rounded text-surface-500 hover:text-white hover:bg-white/10 transition-colors"
                  >
                    <Pencil size={13} />
                  </button>
                  {!activeJudgeId && (
                    <button
                      onClick={(e) => { e.stopPropagation(); confirmDelete(c) }}
                      className="shrink-0 p-1 rounded text-surface-500 hover:text-red-400 hover:bg-red-500/10 transition-colors"
                    >
                      <Trash2 size={13} />
                    </button>
                  )}
                </div>
              )
            })}
          </div>
        )
        })()}
      </div>

      {/* Zone 3: Balance + Nav + Logout */}
      <div className="shrink-0 border-t border-white/[0.08]">
        <SidebarBalance user={user} />
        <div className="px-2 py-1">
          {/* Balance row */}
          {user && (() => {
            // For assistants: show judge's balance
            const billingSource = activeJudge || user
            const sub = billingSource.subscription_until && new Date(billingSource.subscription_until) > new Date()
            const total = sub ? '∞' : (() => {
              const n = (billingSource.free_cases_left || 0) + (billingSource.paid_cases_left || 0)
              return n + ' ' + (n === 1 ? 'дело' : n < 5 ? 'дела' : 'дел')
            })()
            return (
              <div className="flex items-center justify-between px-3 py-2 mb-1">
                <div className="flex items-center gap-2.5 text-[13px] text-surface-300">
                  <CreditCard size={18} className="text-surface-500 shrink-0" />
                  <span>Баланс: <span className="font-semibold text-white">{total}</span></span>
                </div>
                {!activeJudgeId && (
                  <NavLink
                    to="/billing"
                    onClick={onNav}
                    className="text-[11px] bg-brand-700 hover:bg-brand-600 text-white px-2.5 py-1 rounded-md font-medium transition-colors shrink-0"
                  >
                    Пополнить
                  </NavLink>
                )}
              </div>
            )
          })()}
          {nav.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              onClick={onNav}
              className={({ isActive }) =>
                `flex items-center gap-2.5 px-3 py-2 rounded-lg text-[13px] transition-colors ${
                  isActive
                    ? 'bg-brand-600/15 text-brand-300 font-medium'
                    : 'text-surface-400 hover:text-white'
                }`
              }
            >
              <Icon size={18} />
              {label}
            </NavLink>
          ))}
          {user?.is_admin && (
            <NavLink
              to="/admin"
              onClick={onNav}
              className={({ isActive }) =>
                `flex items-center gap-2.5 px-3 py-2 rounded-lg text-[13px] transition-colors ${
                  isActive
                    ? 'bg-brand-600/15 text-brand-300 font-medium'
                    : 'text-surface-400 hover:text-white'
                }`
              }
            >
              <Shield size={18} />
              Админка
            </NavLink>
          )}
        </div>
        <div className="px-4 pb-1 pt-1 flex items-center gap-3 text-[11px] text-surface-600">
          <a href={`${import.meta.env.VITE_API_URL || ''}/docs/oferta`} target="_blank" rel="noopener" className="hover:text-surface-400 transition-colors">Оферта</a>
          <span className="text-surface-700">·</span>
          <a href={`${import.meta.env.VITE_API_URL || ''}/docs/privacy`} target="_blank" rel="noopener" className="hover:text-surface-400 transition-colors">Конфиденциальность</a>
        </div>
        <div className="px-4 pb-3 pt-1">
          <a href="https://t.me/terehov_a_n" target="_blank" rel="noopener" onClick={() => { try { api.trackAction("click_support", "sidebar") } catch {} }} className="flex items-center gap-2 text-[13px] text-surface-600 hover:text-brand-600 transition-colors mb-1">
            <MessageCircle size={15} />
            Поддержка
          </a>
          <button onClick={logout} className="flex items-center gap-2 text-[13px] text-surface-600 hover:text-red-400 transition-colors">
            <LogOut size={15} />
            Выйти
          </button>
        </div>
      </div>
      {/* Delete confirmation modal */}
      {deletingCase && (
        <div className="fixed inset-0 z-[100] bg-black/50 flex items-center justify-center p-4" onClick={cancelDelete}>
          <div className="bg-white rounded-xl shadow-2xl max-w-sm w-full p-6" onClick={e => e.stopPropagation()}>
            <h3 className="text-lg font-semibold text-surface-900 mb-2">Удалить дело?</h3>
            <p className="text-sm text-surface-500 mb-5 break-words">{caseTitle(deletingCase)}</p>
            <div className="flex gap-3 justify-end">
              <button onClick={cancelDelete} className="px-4 py-2 text-sm font-medium text-surface-600 bg-surface-100 hover:bg-surface-200 rounded-lg transition-colors">
                Отмена
              </button>
              <button onClick={execDelete} className="px-4 py-2 text-sm font-medium text-white bg-red-500 hover:bg-red-600 rounded-lg transition-colors">
                Удалить
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

function SidebarBalance({ user }) {
  if (!user) return null
  return (
    <div className="px-4 py-2 text-[11px] text-white/40">
      ID: {user.display_id || '...'}
    </div>
  )
}
