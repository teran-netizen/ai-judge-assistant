import React, { useState, useEffect } from 'react'
import {
  BarChart3, Users, MessageCircle, XCircle, TrendingUp, Share2, Ticket, RefreshCw,
} from 'lucide-react'
import DashboardTab from './admin/DashboardTab'
import ClientsTab from './admin/ClientsTab'
import FeedbacksTab from './admin/FeedbacksTab'
import AnalyticsTab from './admin/AnalyticsTab'
import ReferralsTab from './admin/ReferralsTab'
import PromoCodesTab from './admin/PromoCodesTab'

const tabs = [
  { id: 'dashboard', label: 'Дашборд', icon: BarChart3 },
  { id: 'clients', label: 'Клиенты', icon: Users },
  { id: 'feedbacks', label: 'Фидбек', icon: MessageCircle },
  { id: 'analytics', label: 'Аналитика', icon: TrendingUp },
  { id: 'referrals', label: 'Рефералы', icon: Share2 },
  { id: 'promos', label: 'Промокоды', icon: Ticket },
]

export default function AdminPage() {
  const [tab, setTab] = useState('dashboard')
  // refreshKey: increments only on manual "Обновить" click.
  // Passed as React `key` to each tab → forces remount → useEffect re-fires
  // → endpoint is re-fetched. Auto-refresh was removed (см. коммит-history):
  // full tab remount every 30s lost scroll/filters/modals — user-reported
  // annoyance. User now controls refresh timing via the button.
  const [refreshKey, setRefreshKey] = useState(0)
  const [lastRefresh, setLastRefresh] = useState(Date.now())

  const manualRefresh = () => {
    setRefreshKey((k) => k + 1)
    setLastRefresh(Date.now())
  }

  const secondsAgo = Math.floor((Date.now() - lastRefresh) / 1000)

  return (
    <div className="flex-1 overflow-y-auto" style={{ scrollbarGutter: 'stable' }}>
    <div className="max-w-6xl mx-auto px-3 sm:px-6 py-4 sm:py-8">
    <div className="animate-in">
      <div className="flex items-center justify-between mb-4 sm:mb-6">
        <h1 className="text-xl sm:text-2xl font-display font-bold">Админ-панель</h1>
        <button
          onClick={manualRefresh}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs sm:text-sm text-surface-500 hover:text-surface-900 hover:bg-surface-100 transition-colors"
          title={`Обновлено ${secondsAgo}с назад. Нажмите для обновления.`}
        >
          <RefreshCw size={14} />
          <span className="hidden sm:inline">Обновить</span>
        </button>
      </div>

      {/* Tabs — mobile: full-width buttons */}
      <div className="flex gap-1 mb-4 sm:mb-6 bg-surface-100 p-1 rounded-lg overflow-x-auto">
        {tabs.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            onClick={() => setTab(id)}
            className={`flex items-center gap-1.5 px-3 sm:px-4 py-2 rounded-md text-sm font-medium transition-colors whitespace-nowrap flex-1 justify-center sm:flex-none ${
              tab === id
                ? 'bg-white text-surface-900 shadow-sm'
                : 'text-surface-500 hover:text-surface-700'
            }`}
          >
            <Icon size={16} />
            {label}
          </button>
        ))}
      </div>

      {tab === 'dashboard' && <DashboardTab key={refreshKey} />}
      {tab === 'clients' && <ClientsTab key={refreshKey} />}
      {tab === 'feedbacks' && <FeedbacksTab key={refreshKey} />}
      {tab === 'analytics' && <AnalyticsTab key={refreshKey} />}
      {tab === 'referrals' && <ReferralsTab key={refreshKey} />}
      {tab === 'promos' && <PromoCodesTab key={refreshKey} />}

    </div>
    </div>
    </div>
  )
}

/* ───────── Shared utilities (exported for sub-components) ───────── */

export function StatusFilter({ options, labels, value, onChange }) {
  return (
    <div className="flex gap-1 bg-surface-100 p-1 rounded-lg overflow-x-auto">
      {options.map(opt => (
        <button
          key={opt}
          onClick={() => onChange(opt)}
          className={`px-2.5 sm:px-3 py-1.5 rounded-md text-xs font-medium transition-colors whitespace-nowrap ${
            value === opt
              ? 'bg-white text-surface-900 shadow-sm'
              : 'text-surface-500 hover:text-surface-700'
          }`}
        >
          {labels[opt] || opt}
        </button>
      ))}
    </div>
  )
}

export function Spinner() {
  return (
    <div className="flex justify-center py-16">
      <div className="w-8 h-8 border-[3px] border-brand-200 border-t-brand-600 rounded-full animate-spin" />
    </div>
  )
}

export function ErrorMsg({ text }) {
  return (
    <div className="card p-8 text-center">
      <XCircle size={32} className="text-red-400 mx-auto mb-3" />
      <p className="text-sm text-surface-600">{text}</p>
    </div>
  )
}

export function EmptyState({ text }) {
  return (
    <div className="card p-8 text-center mt-4">
      <p className="text-sm text-surface-500">{text}</p>
    </div>
  )
}
