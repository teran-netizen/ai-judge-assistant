import { AlertCircle, Sparkles, RefreshCw, Plus } from 'lucide-react'

export default function ErrorPhase({ error, caseId, processedDocs, onRetry, onRetryProcess, onUploadMore }) {
  const validCount = processedDocs.filter(d => !d.error && !d.skip).length
  return (
    <div className="animate-in mb-6">
      <div className="card p-5 border-red-200 bg-red-50">
        <div className="flex items-start gap-3">
          <AlertCircle size={20} className="text-red-500 shrink-0 mt-0.5" />
          <div>
            <h3 className="text-sm font-semibold text-red-800 mb-1">Ошибка</h3>
            {error?.includes('|billing_limit') ? (
              <div>
                <p className="text-red-600 text-sm mb-2">{error.split('|')[0]}</p>
                <a href="/billing" className="inline-flex items-center gap-1.5 text-sm font-medium text-brand-600 hover:text-brand-700">
                  Перейти к оплате &rarr;
                </a>
              </div>
            ) : (
              <p className="text-red-600 text-sm">{error || 'Произошла ошибка при обработке.'}</p>
            )}
            <a href="https://t.me/terehov_a_n" target="_blank" rel="noopener" onClick={() => { try { api.trackAction("click_support", "error_page") } catch {} }} className="inline-flex items-center gap-1.5 text-xs text-surface-500 hover:text-brand-600 mt-2">
              {'💬'} Написать в поддержку
            </a>
          </div>
        </div>
      </div>
      {caseId && (
        <div className="flex flex-col gap-2 mt-3">
          {validCount > 0 && (
            <button onClick={onRetry} className="btn-primary w-full py-2.5 text-sm">
              <Sparkles size={16} />
              Доработать ({validCount} док.)
            </button>
          )}
          <button onClick={onRetryProcess} className="btn w-full py-2.5 text-sm text-surface-600 bg-surface-50 border border-surface-200 hover:bg-surface-100">
            <RefreshCw size={16} />
            Переобработать документы
          </button>
          <button onClick={onUploadMore} className="btn w-full py-2.5 text-sm text-surface-400 hover:text-surface-600">
            <Plus size={16} />
            Загрузить другие файлы
          </button>
        </div>
      )}
    </div>
  )
}
