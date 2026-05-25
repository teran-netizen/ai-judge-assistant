import { Loader, CheckCircle2, Clock, XCircle } from 'lucide-react'

export default function ProcessingPhase({ genStatus, processProgress, processingFile, processedDocs, streamReconnect }) {
  const pct = processProgress.pct || 0
  const stage = processProgress.stage || ''

  return (
    <div className="animate-in mb-6">
      <div className="card p-4 border-brand-200 bg-brand-50 mb-4">
        <div className="flex items-center gap-3">
          <Loader size={20} className="text-brand-600 animate-spin shrink-0" />
          <div className="flex-1 min-w-0">
            <div className="flex items-center justify-between mb-0.5">
              <div className="text-sm font-medium text-brand-800">
                {stage || genStatus || 'Обработка документов...'}
              </div>
              {pct > 0 && (
                <div className="text-sm font-semibold text-brand-600 ml-2 tabular-nums">{pct}%</div>
              )}
            </div>
            {processingFile && !genStatus && (
              <div className="text-xs text-brand-600 mt-0.5">📄 {processingFile}</div>
            )}
            {genStatus && stage && genStatus !== stage && (
              <div className="text-xs text-brand-600 mt-0.5">{genStatus}</div>
            )}
            {streamReconnect?.state === 'reconnecting' && (
              <div className="text-xs text-amber-700 mt-0.5">
                Соединение прервано, переподключаемся (попытка {streamReconnect.attempt}
                {streamReconnect.maxRetries ? ` из ${streamReconnect.maxRetries}` : ''})...
              </div>
            )}
            {streamReconnect?.state === 'connected' && (
              <div className="text-xs text-emerald-700 mt-0.5">Соединение восстановлено</div>
            )}
            {processProgress.index > 0 && processProgress.total > 0 && (
              <div className="text-xs text-brand-600 mt-0.5">✅ Извлечено: {processProgress.index} из {processProgress.total}</div>
            )}
            <div className="w-full h-2 bg-brand-100 rounded-full overflow-hidden mt-1.5">
              <div
                className="h-full bg-brand-500 rounded-full transition-all duration-500 ease-out"
                style={{ width: `${pct}%` }}
              />
            </div>
          </div>
        </div>
      </div>

      {processedDocs.length > 0 && (() => {
        const maxShow = 15
        const showAll = processedDocs.length <= maxShow
        const visible = showAll ? processedDocs : processedDocs.slice(-maxShow)
        const hidden = processedDocs.length - visible.length
        return (
        <div className="space-y-1.5">
          {hidden > 0 && (
            <div className="text-xs text-surface-400 py-1">… и ещё {hidden} файлов обработано</div>
          )}
          {visible.map((doc, i) => (
            <div key={i} className="flex items-center gap-2 text-sm animate-in" style={{ animationDelay: `${i * 60}ms` }}>
              {doc.error ? (
                <XCircle size={15} className="text-red-500 shrink-0" />
              ) : doc.skip ? (
                <Clock size={15} className="text-surface-400 shrink-0" />
              ) : (
                <CheckCircle2 size={15} className="text-emerald-500 shrink-0" />
              )}
              <span className="text-surface-500 text-xs truncate">{doc.filename}</span>
              {!doc.error && !doc.skip && (
                <span className="text-surface-700 text-xs truncate">→ {doc.summary_line}</span>
              )}
              {doc.error && (
                <span className="text-red-500 text-xs truncate">Файл не распознался</span>
              )}
              {doc.skip && !doc.error && (
                <span className="text-surface-400 text-xs truncate">{doc.summary_line}</span>
              )}
            </div>
          ))}
        </div>
        )})()}
    </div>
  )
}
