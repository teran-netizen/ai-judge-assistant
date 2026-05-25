import React from 'react'
import { FileText } from 'lucide-react'

/* Full case timeline with files, instructions, generation status, timing */
export default function CasesTimeline({ cases }) {
  const statusConfig = {
    completed: { label: 'ГОТОВО', cls: 'bg-emerald-100 text-emerald-700' },
    error: { label: 'ОШИБКА', cls: 'bg-red-100 text-red-700' },
    processing: { label: 'ОБРАБОТКА', cls: 'bg-amber-100 text-amber-700' },
    draft: { label: 'ЧЕРНОВИК', cls: 'bg-surface-200 text-surface-600' },
  }

  return (
    <div className="space-y-3">
      <div className="text-[11px] font-medium text-surface-500 uppercase tracking-wide">Дела пользователя</div>
      {cases.map(cs => {
        const st = statusConfig[cs.status] || statusConfig.draft
        const fileNames = (cs.files || []).map(f => f.name).join(', ')
        return (
          <div key={cs.id} className="border border-surface-200 rounded-lg p-3 text-xs space-y-1.5">
            {/* Header: title + status badge */}
            <div className="flex items-start justify-between gap-2">
              <div className="flex items-center gap-1.5 min-w-0">
                <FileText size={13} className="text-surface-400 shrink-0" />
                <span className="font-medium text-surface-800 truncate">
                  {cs.user_instructions
                    ? `"${cs.user_instructions.slice(0, 60)}${cs.user_instructions.length > 60 ? '...' : ''}"`
                    : cs.title || 'Без названия'}
                </span>
              </div>
              <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold shrink-0 ${st.cls}`}>
                {st.label}
              </span>
            </div>

            {/* Timeline events */}
            <div className="pl-5 space-y-0.5 text-surface-600">
              {/* Created */}
              {cs.created_time && (
                <div>{cs.created_time} — Создано</div>
              )}

              {/* Files uploaded */}
              {cs.files_count > 0 && (
                <div>
                  {cs.files?.[0]?.uploaded_at || cs.created_time} — Загружено {cs.files_count} файл{cs.files_count === 1 ? '' : cs.files_count < 5 ? 'а' : 'ов'}
                  {fileNames && <span className="text-surface-400">: {fileNames.length > 80 ? fileNames.slice(0, 77) + '...' : fileNames}</span>}
                </div>
              )}

              {/* Generation result */}
              {cs.status === 'completed' && cs.has_generated_text && (
                <div className="text-emerald-600">
                  {cs.updated_time || ''} — ✅ Готово
                  {cs.generated_length > 0 && ` (${cs.generated_length.toLocaleString('ru')} сим.`}
                  {cs.duration_sec != null && `, ${cs.duration_sec} сек`}
                  {cs.generated_length > 0 && ')'}
                </div>
              )}

              {cs.status === 'error' && (
                <div className="text-red-600">❌ Ошибка генерации</div>
              )}

              {cs.status === 'draft' && cs.files_count > 0 && (
                <div className="text-surface-400">❌ Генерация не запускалась</div>
              )}

              {cs.status === 'draft' && cs.files_count === 0 && (
                <div className="text-surface-400">Пустое дело</div>
              )}

              {cs.status === 'processing' && (
                <div className="text-amber-600">⏳ В процессе...</div>
              )}

              {/* Tokens */}
              {cs.tokens && (cs.tokens.prompt > 0 || cs.tokens.completion > 0) && (
                <div className="text-surface-400">
                  Токены: {cs.tokens.prompt.toLocaleString('ru')} in / {cs.tokens.completion.toLocaleString('ru')} out
                </div>
              )}
            </div>

            {/* Summary preview */}
            {cs.summary && (
              <div className="pl-5 mt-1 text-[11px] text-surface-500 italic leading-relaxed">
                {cs.summary}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
