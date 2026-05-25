import { useState, useMemo, useCallback } from 'react'
import { X, ExternalLink, Loader2 } from 'lucide-react'
import { getStatus, refTypeLabel } from './normStatus'
import useNormData from './useNormData'

/**
 * NormHighlight: рендерит текст решения с inline-подсветкой юридических ссылок.
 *
 * Каждая ссылка подсвечивается цветом по статусу из validation_result.
 * Клик по ссылке открывает попап с деталями нормы.
 *
 * Props:
 *   text - текст решения (string)
 *   validationResult - объект из case.validation_result
 *   isStreaming - true если текст ещё стримится (отключаем подсветку)
 */
export default function NormHighlight({ text, validationResult, isStreaming }) {
  const [popup, setPopup] = useState(null)

  const hasRefs = !isStreaming && !!validationResult?.references?.length

  const segments = useMemo(() => {
    if (!hasRefs) return null
    return buildSegments(text, validationResult.references)
  }, [text, hasRefs, validationResult?.references])

  const handleRefClick = useCallback((e, ref) => {
    e.stopPropagation()
    setPopup(prev => (prev?.ref === ref ? null : { ref }))
  }, [])

  const closePopup = useCallback(() => setPopup(null), [])

  if (!text) return null
  if (!segments) return <>{text}</>

  return (
    <span onClick={closePopup}>
      {segments.map((seg, i) => {
        if (seg.type === 'text') {
          return <span key={i}>{seg.value}</span>
        }

        const ref = seg.ref
        const status = getStatus(ref.status)

        return (
          <span key={i} className="relative inline">
            <span
              className={`${status.bgClass} cursor-pointer transition-colors rounded-sm px-0.5 -mx-0.5`}
              onClick={(e) => handleRefClick(e, ref)}
              title={status.title}
            >
              {seg.value}
            </span>

            {popup?.ref === ref && (
              <NormPopup ref_={ref} onClose={closePopup} />
            )}
          </span>
        )
      })}
    </span>
  )
}

// ── NormPopup ──────────────────────────────────────────────────

function NormPopup({ ref_, onClose }) {
  const status = getStatus(ref_.status)
  const StatusIcon = status.icon

  const { data: normData, loading } = useNormData(ref_.norm_id)
  const [expanded, setExpanded] = useState(false)

  const normText = normData?.text || ''
  const sourceUrl = normData?.source_url || ''
  const shortText = normText.length > 300 ? normText.slice(0, 300) + '…' : normText

  return (
    <span
      className="absolute z-50 left-0 top-full mt-1 w-80 bg-white border border-surface-200 rounded-xl shadow-lg p-3 text-left"
      onClick={e => e.stopPropagation()}
      style={{ transform: 'translateX(-10%)', maxHeight: '70vh', overflowY: 'auto' }}
    >
      {/* Header */}
      <span className="flex items-start justify-between gap-2 mb-2">
        <span className="flex items-center gap-1.5">
          <StatusIcon size={14} className={status.textColor} />
          <span className={`text-xs font-medium ${status.textColor}`}>{status.label}</span>
        </span>
        <button
          onClick={onClose}
          className="p-0.5 rounded hover:bg-surface-100 text-surface-400"
        >
          <X size={12} />
        </button>
      </span>

      {/* Reference info */}
      <span className="block text-xs text-surface-700 font-medium mb-1">{ref_.raw}</span>
      <span className="block text-xs text-surface-400 mb-1">Тип: {refTypeLabel(ref_.type)}</span>

      {/* Outdated warning */}
      {ref_.status === 'outdated' && (
        <span className="block text-xs text-orange-700 mt-1.5 p-2 bg-orange-50 border border-orange-100 rounded-lg">
          <span className="font-medium">Норма утратила силу</span>
          {ref_.inactive_reason && (
            <span className="block mt-0.5 text-orange-600">{ref_.inactive_reason}</span>
          )}
        </span>
      )}

      {/* Document title */}
      {(ref_.doc_title || normData?.doc_title) && (
        <span className="block text-xs text-surface-600 mt-1.5 p-2 bg-surface-50 rounded-lg">
          {normData?.doc_title || ref_.doc_title}
        </span>
      )}

      {/* Norm text from DB */}
      {loading && (
        <span className="flex items-center gap-1.5 mt-2 text-xs text-surface-400">
          <Loader2 size={12} className="animate-spin" />
          Загрузка текста нормы…
        </span>
      )}
      {normText && (
        <span className="block mt-2">
          <span className="block text-xs font-medium text-surface-500 mb-1">Текст нормы:</span>
          <span className="block text-xs text-surface-700 p-2 bg-emerald-50 border border-emerald-100 rounded-lg leading-relaxed whitespace-pre-wrap">
            {expanded ? normText : shortText}
          </span>
          {normText.length > 300 && (
            <button
              onClick={() => setExpanded(!expanded)}
              className="text-xs text-brand-600 hover:text-brand-700 mt-1"
            >
              {expanded ? 'Свернуть' : 'Показать полностью'}
            </button>
          )}
        </span>
      )}

      {/* Source link */}
      {sourceUrl && (
        <a
          href={sourceUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-1 mt-2 text-xs text-brand-600 hover:text-brand-700 hover:underline"
        >
          <ExternalLink size={11} />
          Открыть источник
        </a>
      )}

      {/* Correction details */}
      {ref_.correction && ref_.correction.action !== 'confirm' && (
        <span className="block mt-2 p-2 bg-amber-50 border border-amber-100 rounded-lg">
          {ref_.correction.action === 'remove' ? (
            <span className="block text-xs text-red-600">Удалено AI-ревизором</span>
          ) : (
            <>
              <span className="block text-xs text-amber-700 font-medium mb-1">Исправлено AI-ревизором:</span>
              {ref_.correction.original_text && (
                <span className="block text-xs text-surface-500 line-through">{ref_.correction.original_text.slice(0, 120)}</span>
              )}
              {ref_.correction.corrected_text && (
                <span className="block text-xs text-emerald-700 mt-0.5">{ref_.correction.corrected_text.slice(0, 120)}</span>
              )}
            </>
          )}
          {ref_.correction.reason && (
            <span className="block text-xs text-surface-500 mt-1 italic">{ref_.correction.reason}</span>
          )}
        </span>
      )}
    </span>
  )
}

// ── Trim highlight range for codex refs ──────────────────────

/**
 * For full-form codex refs like "статьи 807 Гражданского кодекса РФ",
 * returns the shorter range covering just the article part ("статьи 807").
 * For short-form "ст. 395 ГК РФ" — keeps as-is (already compact).
 */
function trimCodexHighlight(ref, pos, end, text) {
  if (ref.type !== 'codex') return { pos, end }
  const raw = text.slice(pos, end)
  // Match: optional п./ч./подп. + ст./статья + article number(s)
  const m = raw.match(
    /^((?:п\.?\s*\d+(?:\.\d+)?\s+)?(?:ч\.?\s*\d+\s+)?(?:подп\.?\s*\d+\s+)?(?:ст\.?\s*|стать[а-яёА-ЯЁ]*\s+)\d+(?:\.\d+)?(?:\s*[,\u2013\-]\s*\d+(?:\.\d+)?)*)/
  )
  if (m && m[1].length < raw.length) {
    return { pos, end: pos + m[1].length }
  }
  return { pos, end }
}

// ── Text segmentation ────────────────────────────────────────

function buildSegments(text, references) {
  if (!references?.length) return [{ type: 'text', value: text }]

  const sorted = [...references]
    .filter(r => r.position != null && r.end_position != null && r.position < text.length)
    .sort((a, b) => a.position - b.position)

  // Remove overlaps, fix stale positions
  const clean = []
  let lastEnd = 0
  for (const ref of sorted) {
    // Removed refs — text was deleted, nothing to highlight
    if (ref.status === 'removed') continue

    let pos = ref.position
    let end = ref.end_position
    const raw = ref.raw || ''

    // Verify: text at stored position must match ref.raw
    const actual = text.slice(pos, end)
    if (actual !== raw && raw) {
      // Position shifted after AI corrections — search nearby (±300 chars)
      const searchStart = Math.max(0, pos - 300)
      const searchEnd = Math.min(text.length, pos + 300 + raw.length)
      const idx = text.indexOf(raw, searchStart)
      if (idx !== -1 && idx < searchEnd) {
        pos = idx
        end = idx + raw.length
      } else {
        continue // Can't find reference text — skip
      }
    }

    // For codex refs, trim highlight to just article number (not full codex name)
    const trimmed = trimCodexHighlight(ref, pos, end, text)
    pos = trimmed.pos
    end = trimmed.end

    if (pos >= lastEnd && end <= text.length) {
      clean.push({ ...ref, position: pos, end_position: end })
      lastEnd = end
    }
  }

  if (clean.length === 0) return [{ type: 'text', value: text }]

  const segments = []
  let cursor = 0

  for (const ref of clean) {
    if (ref.position > cursor) {
      segments.push({ type: 'text', value: text.slice(cursor, ref.position) })
    }
    segments.push({ type: 'ref', value: text.slice(ref.position, ref.end_position), ref })
    cursor = ref.end_position
  }

  if (cursor < text.length) {
    segments.push({ type: 'text', value: text.slice(cursor) })
  }

  return segments
}
