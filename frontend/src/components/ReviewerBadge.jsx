import { useState } from 'react'
import { ShieldCheck, ShieldAlert, Wrench, Clock, ChevronDown, ChevronUp, ExternalLink, Loader2 } from 'lucide-react'
import { getStatus, pluralRefs } from './normStatus'
import useNormData from './useNormData'

/**
 * AI-ревизор: бейдж-панель со статистикой проверки юридических ссылок.
 *
 * Props:
 *   validationResult - объект из case.validation_result (JSONB)
 *     { references: [...], stats: { total_refs, confirmed, fixed, removed, error }, version: 1 }
 *   onReferenceClick - callback(ref) при клике на ссылку в панели деталей
 */
export default function ReviewerBadge({ validationResult, onReferenceClick }) {
  const [expanded, setExpanded] = useState(false)

  if (!validationResult?.stats) return null

  const { stats, references = [] } = validationResult

  // Поддержка двух форматов stats:
  // 1. AI-ревизор (generate): { total_refs, confirmed, fixed, removed, error }
  // 2. Простая валидация (refine): { total, found, not_found }
  const total_refs = stats.total_refs ?? stats.total ?? 0
  const confirmed = stats.confirmed ?? stats.found ?? 0
  const fixed = stats.fixed ?? 0
  const removed = stats.removed ?? 0
  const errorCount = stats.error ?? stats.not_found ?? 0

  if (total_refs === 0) return null

  const verified = confirmed + fixed
  const notFound = removed + errorCount

  // Группируем ссылки по статусу
  const fixedRefs = references.filter(r => r.status === 'fixed')
  const removedRefs = references.filter(r => r.status === 'removed')
  const outdatedRefs = references.filter(r => r.status === 'outdated')
  const unverifiedRefs = references.filter(r => r.status === 'unverified' || r.status === 'unknown')
  const verifiedRefs = references.filter(r => r.status === 'verified')

  const hasDetails = references.length > 0

  return (
    <div className="mb-3 animate-in">
      {/* Compact panel */}
      <div
        className="card border border-surface-200 cursor-pointer hover:border-brand-300 active:border-brand-400 transition-colors"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="px-3 sm:px-4 py-3 flex items-start gap-2 sm:gap-3">
          <ShieldCheck size={18} className="text-brand-600 shrink-0 mt-0.5" />
          <div className="flex-1 min-w-0">
            <div className="text-xs font-medium text-surface-600">
              AI-РЕВИЗОР: {total_refs} {pluralRefs(total_refs)} проверено
            </div>
            <div className="flex flex-wrap items-center gap-1.5 sm:gap-2 mt-1.5">
              <StatusBadge count={verified} status="verified" label="ок" labelFull="проверено" />
              <StatusBadge count={fixed} status="fixed" label="испр." labelFull="исправлено" />
              <StatusBadge count={outdatedRefs.length} status="outdated" label="устар." labelFull="утратили силу" />
              <StatusBadge count={notFound} status="removed" label="н/д" labelFull="не найдено" />
            </div>
          </div>
          {hasDetails && (
            <div className="shrink-0 text-surface-400 mt-0.5">
              {expanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
            </div>
          )}
        </div>
      </div>

      {/* Expanded details */}
      {expanded && hasDetails && (
        <div className="card border border-surface-200 mt-1 px-3 sm:px-4 py-3 space-y-3 max-h-[60vh] overflow-y-auto">
          <RefSection
            refs={fixedRefs}
            title="Исправления AI"
            renderItem={(ref, i) => (
              <FixedRefCard key={i} ref_={ref} onReferenceClick={onReferenceClick} />
            )}
          />
          <RefSection
            refs={removedRefs}
            title="Удалено"
            renderItem={(ref, i) => (
              <RefCard key={i} ref_={ref} status="removed" strikethrough>
                {ref.correction?.reason && (
                  <div className="text-surface-500 mt-1 italic">{ref.correction.reason}</div>
                )}
              </RefCard>
            )}
          />
          <RefSection
            refs={outdatedRefs}
            title="Утратили силу"
            renderItem={(ref, i) => (
              <RefCard key={i} ref_={ref} status="outdated" onClick={() => onReferenceClick?.(ref)}>
                {ref.inactive_reason && (
                  <div className="text-orange-600 mt-0.5">{ref.inactive_reason}</div>
                )}
              </RefCard>
            )}
          />
          <RefSection
            refs={unverifiedRefs}
            title="Не найдено в БД"
            renderItem={(ref, i) => (
              <RefCard key={i} ref_={ref} status="unverified" icon={ExternalLink}>
                <div className="text-surface-400 mt-0.5">
                  {ref.db_status === 'not_found' ? 'Отсутствует в БД, но AI считает реальной' : 'Статус неизвестен'}
                </div>
              </RefCard>
            )}
          />
          <RefSection
            refs={verifiedRefs}
            title="Проверено в БД"
            renderItem={(ref, i) => (
              <RefCard key={i} ref_={ref} status="verified" onClick={() => onReferenceClick?.(ref)}>
                {ref.doc_title && (
                  <div className="text-surface-500 mt-0.5 truncate">{ref.doc_title}</div>
                )}
              </RefCard>
            )}
          />
        </div>
      )}
    </div>
  )
}

// ── Sub-components ────────────────────────────────────────────

/** Компактный бейдж статуса (в header-панели). */
function StatusBadge({ count, status, label, labelFull }) {
  if (!count) return null
  const s = getStatus(status)
  const Icon = s.icon
  return (
    <span className={`inline-flex items-center gap-1 text-xs px-1.5 sm:px-2 py-0.5 rounded-full ${s.badgeClass}`}>
      <Icon size={11} />
      <span className="sm:hidden">{count} {label}</span>
      <span className="hidden sm:inline">{count} {labelFull || label}</span>
    </span>
  )
}

/** Секция со списком ссылок (заголовок + карточки). */
function RefSection({ refs, title, renderItem }) {
  if (!refs.length) return null
  return (
    <div>
      <div className="text-xs font-medium text-surface-500 mb-2">
        {title} ({refs.length}):
      </div>
      {refs.map(renderItem)}
    </div>
  )
}

/** Базовая карточка ссылки (removed, outdated, unverified). */
function RefCard({ ref_, status, strikethrough, onClick, icon, children }) {
  const s = getStatus(status)
  const Icon = icon || s.icon
  return (
    <div
      className={`mb-2 p-2.5 border rounded-lg text-xs ${s.cardClass} ${onClick ? 'cursor-pointer hover:opacity-80 transition-colors' : ''}`}
      onClick={onClick}
    >
      <div className="flex items-start gap-2">
        <Icon size={13} className={`${s.textColor} shrink-0 mt-0.5`} />
        <div className="min-w-0">
          <div className={`font-medium ${s.textColor} ${strikethrough ? 'line-through' : ''}`}>
            {ref_.raw}
          </div>
          {children}
        </div>
      </div>
    </div>
  )
}

/** Карточка исправленной ссылки с подгрузкой текста нормы из БД. */
function FixedRefCard({ ref_, onReferenceClick }) {
  const { data: normData, loading } = useNormData(ref_.norm_id)
  const [showNorm, setShowNorm] = useState(false)

  const corr = ref_.correction
  if (!corr) return null

  const normText = normData?.text || ''
  const shortNorm = normText.length > 200 ? normText.slice(0, 200) + '…' : normText

  return (
    <div
      className="mb-2 p-3 bg-amber-50 border border-amber-100 rounded-lg text-xs cursor-pointer hover:bg-amber-100/80 transition-colors"
      onClick={() => onReferenceClick?.(ref_)}
    >
      <div className="flex items-start gap-2">
        <Wrench size={13} className="text-amber-600 shrink-0 mt-0.5" />
        <div className="min-w-0 flex-1">
          {/* Было */}
          <div className="flex items-baseline gap-1.5">
            <ShieldAlert size={11} className="text-red-400 shrink-0 relative top-[1px]" />
            <span className="text-red-600 line-through opacity-70">
              {corr.original_text?.slice(0, 120)}
            </span>
          </div>

          {/* Стало */}
          <div className="flex items-baseline gap-1.5 mt-1">
            <ShieldCheck size={11} className="text-emerald-500 shrink-0 relative top-[1px]" />
            <span className="text-emerald-700 font-medium">
              {corr.corrected_text?.slice(0, 120)}
            </span>
          </div>

          {/* Причина */}
          {corr.reason && (
            <div className="text-surface-500 mt-1.5 italic leading-relaxed">
              {corr.reason}
            </div>
          )}

          {/* Текст правильной нормы из БД */}
          {loading && (
            <div className="flex items-center gap-1.5 mt-2 text-surface-400">
              <Loader2 size={11} className="animate-spin" />
              Загрузка текста нормы…
            </div>
          )}
          {normText && (
            <div className="mt-2">
              <button
                onClick={(e) => { e.stopPropagation(); setShowNorm(!showNorm) }}
                className="text-brand-600 hover:text-brand-700 font-medium flex items-center gap-1"
              >
                <ShieldCheck size={11} />
                {showNorm ? 'Скрыть текст нормы' : 'Показать текст правильной нормы'}
              </button>
              {showNorm && (
                <div className="mt-1.5 p-2 bg-emerald-50 border border-emerald-100 rounded-lg text-surface-700 leading-relaxed whitespace-pre-wrap">
                  {ref_.doc_title && (
                    <div className="text-surface-500 font-medium mb-1">{ref_.doc_title}</div>
                  )}
                  {shortNorm}
                  {normText.length > 200 && normData?.source_url && (
                    <a
                      href={normData.source_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      onClick={(e) => e.stopPropagation()}
                      className="flex items-center gap-1 text-brand-600 hover:text-brand-700 mt-1"
                    >
                      <ExternalLink size={10} />
                      Полный текст
                    </a>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
