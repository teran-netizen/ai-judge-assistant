import { useState, useEffect } from 'react'

/**
 * Прогресс-плашка «Пишем решение…».
 *
 * Счётчик документов берётся с приоритетом:
 *   1) docsCount     — живые SSE-события doc_done (если генерация идёт впервые)
 *   2) caseData.files_recognized / files_count — если SSE не шлёт (reload во
 *      время генерации, context-only regeneration, retry на completed case)
 *   3) uploadedFilesCount — fallback для draft-фазы
 *
 * Раньше показывалось «Анализ 0 документов завершён» когда SSE события не
 * пришли (юзер перезагрузил страницу, генерация по уже готовому контексту,
 * retry на уже обработанном деле) — вводило в заблуждение. Теперь берём
 * сохранённый счёт из БД.
 */
function pluralDocs(n) {
  const mod10 = n % 10
  const mod100 = n % 100
  if (mod10 === 1 && mod100 !== 11) return 'документа'
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return 'документов'
  return 'документов'
}

export default function GeneratingProgress({ docsCount = 0, caseData, uploadedFilesCount = 0, streamReconnect }) {
  const [elapsed, setElapsed] = useState(0)

  useEffect(() => {
    const timer = setInterval(() => setElapsed(e => e + 1), 1000)
    return () => clearInterval(timer)
  }, [])

  // Приоритет источников: живой SSE > БД > количество загруженных файлов.
  const effectiveDocs = docsCount > 0
    ? docsCount
    : (caseData?.files_recognized || caseData?.files_count || uploadedFilesCount || 0)

  const estimatedTotal = Math.min(600, effectiveDocs * 15 + 120)
  const pct = Math.min(95, (elapsed / estimatedTotal) * 100)
  const remaining = Math.max(0, Math.ceil((estimatedTotal - elapsed) / 60))

  const formatTime = (s) => {
    const m = Math.floor(s / 60)
    const sec = s % 60
    return m > 0 ? `${m}:${sec.toString().padStart(2, '0')}` : `${sec} сек`
  }

  // Первая строка: если реально знаем число документов — пишем его.
  // Иначе (context-only generation, либо деградация источников) — нейтральный текст.
  const docsLine = effectiveDocs > 0
    ? `Анализ ${effectiveDocs} ${pluralDocs(effectiveDocs)} завершён`
    : 'Формируем черновик решения...'

  return (
    <div className="animate-in mb-6">
      <div className="card p-6 border-brand-200 bg-gradient-to-br from-brand-50 to-white">
        <div className="text-center mb-4">
          <div className="text-3xl mb-2">⚖️</div>
          <div className="text-lg font-display font-bold text-surface-900">Пишем решение...</div>
        </div>

        <div className="space-y-3">
          <div className="flex items-center justify-between text-sm text-surface-600">
            <span>{docsLine}</span>
            <span className="font-mono text-surface-400">{formatTime(elapsed)}</span>
          </div>

          <div className="w-full h-2 bg-surface-100 rounded-full overflow-hidden">
            <div
              className="h-full bg-gradient-to-r from-brand-400 to-brand-600 rounded-full transition-all duration-1000 ease-linear"
              style={{ width: `${pct}%` }}
            />
          </div>

          <div className="text-center text-sm text-surface-500">
            {remaining > 0
              ? `Примерно ${remaining} мин. осталось`
              : 'Почти готово...'
            }
          </div>

          {streamReconnect?.state === 'reconnecting' && (
            <div className="text-center text-xs text-amber-700">
              Соединение прервано, восстанавливаем (попытка {streamReconnect.attempt}
              {streamReconnect.maxRetries ? ` из ${streamReconnect.maxRetries}` : ''})...
            </div>
          )}
          {streamReconnect?.state === 'connected' && (
            <div className="text-center text-xs text-emerald-700">Соединение восстановлено</div>
          )}
          <div className="text-center text-xs text-surface-400 mt-2">
            Генерация идёт на сервере — можете свернуть страницу, решение сохранится автоматически
          </div>
          <div className="text-center text-xs text-surface-400 mt-1">
            После генерации решения оригиналы файлов удаляются
          </div>
        </div>
      </div>
    </div>
  )
}
