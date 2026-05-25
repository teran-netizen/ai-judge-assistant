/**
 * Конфигурация статусов юридических ссылок.
 * Единый источник правды для NormHighlight, ReviewerBadge, и попапов.
 */
import { ShieldCheck, ShieldAlert, Wrench, Clock } from 'lucide-react'

export const NORM_STATUSES = {
  verified: {
    icon: ShieldCheck,
    label: 'Проверено',
    title: 'Проверено в БД',
    textColor: 'text-emerald-600',
    bgClass: 'bg-emerald-100/60 hover:bg-emerald-100',
    badgeClass: 'text-emerald-700 bg-emerald-50',
    cardClass: 'bg-emerald-50 border-emerald-100',
  },
  fixed: {
    icon: Wrench,
    label: 'Исправлено',
    title: 'Исправлено AI-ревизором',
    textColor: 'text-amber-600',
    bgClass: 'bg-amber-100/60 hover:bg-amber-100',
    badgeClass: 'text-amber-700 bg-amber-50',
    cardClass: 'bg-amber-50 border-amber-100',
  },
  removed: {
    icon: ShieldAlert,
    label: 'Удалено',
    title: 'Удалено (галлюцинация)',
    textColor: 'text-red-600',
    bgClass: 'bg-red-100/60 hover:bg-red-100 line-through',
    badgeClass: 'text-red-700 bg-red-50',
    cardClass: 'bg-red-50 border-red-100',
  },
  outdated: {
    icon: Clock,
    label: 'Утратила силу',
    title: 'Норма утратила силу',
    textColor: 'text-orange-600',
    bgClass: 'bg-orange-100/60 hover:bg-orange-100',
    badgeClass: 'text-orange-700 bg-orange-50',
    cardClass: 'bg-orange-50 border-orange-100',
  },
  unverified: {
    icon: ShieldAlert,
    label: 'Не в БД',
    title: 'Не найдено в БД',
    textColor: 'text-surface-500',
    bgClass: 'bg-surface-100/60 hover:bg-surface-200',
    badgeClass: 'text-surface-600 bg-surface-50',
    cardClass: 'bg-surface-50 border-surface-200',
  },
}

const DEFAULT_STATUS = {
  icon: ShieldAlert,
  label: 'Неизвестно',
  title: 'Не проверено',
  textColor: 'text-surface-500',
  bgClass: 'bg-surface-50 hover:bg-surface-100',
  badgeClass: 'text-surface-600 bg-surface-50',
  cardClass: 'bg-surface-50 border-surface-200',
}

export function getStatus(status) {
  return NORM_STATUSES[status] || DEFAULT_STATUS
}

export const REF_TYPE_LABELS = {
  codex: 'Кодекс',
  plenum: 'Пленум ВС РФ',
  vs_decision: 'Решение ВС РФ',
  fz: 'Федеральный закон',
  practice_review: 'Обзор практики',
}

export function refTypeLabel(type) {
  return REF_TYPE_LABELS[type] || type || 'Неизвестно'
}

export function pluralRefs(n) {
  const mod10 = n % 10
  const mod100 = n % 100
  if (mod10 === 1 && mod100 !== 11) return 'ссылка'
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return 'ссылки'
  return 'ссылок'
}
