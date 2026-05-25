import { Sparkles, CheckCircle2, XCircle, Trash2, Plus, Scale } from 'lucide-react'

export default function ReadyPhase({ processedDocs, error, onRemoveDoc, onUploadMore, onGenerate }) {
  const validDocs = processedDocs.filter(d => !d.error && !d.skip)
  return (
    <div className="animate-in mb-6">
      <div className="flex items-center gap-2.5 mb-3">
        <Scale size={18} className="text-brand-600 shrink-0" />
        <h2 className="text-lg font-display font-semibold">Материалы дела</h2>
        <span className="text-sm text-surface-400">({validDocs.length})</span>
      </div>

      <div className="card divide-y divide-surface-100">
        {validDocs.map((doc) => (
          <div key={doc.doc_index} className="flex items-center gap-3 px-4 py-3 group">
            <CheckCircle2 size={16} className="text-emerald-500 shrink-0" />
            <div className="flex-1 min-w-0">
              <div className="text-sm font-medium text-surface-800 truncate">{doc.summary_line || doc.filename}</div>
              <div className="text-xs text-surface-400 truncate">{doc.filename}</div>
            </div>
            <button onClick={() => onRemoveDoc(doc.doc_index)}
              className="text-surface-300 hover:text-red-500 sm:opacity-0 sm:group-hover:opacity-100 transition-all p-1" title="Удалить документ">
              <Trash2 size={15} />
            </button>
          </div>
        ))}
      </div>

      {processedDocs.filter(d => d.error).length > 0 && (
        <div className="mt-3">
          <div className="text-xs font-medium text-red-500 mb-1.5">❌ Не распознано ({processedDocs.filter(d => d.error).length}):</div>
          <div className="card border-red-200 bg-red-50 divide-y divide-red-100">
            {processedDocs.filter(d => d.error).map((doc, i) => (
              <div key={i} className="flex items-center gap-2 px-3 py-2">
                <XCircle size={14} className="text-red-400 shrink-0" />
                <span className="text-xs text-red-600 truncate">{doc.filename}</span>
                <span className="text-[10px] text-red-400 ml-auto shrink-0">Файл не распознался</span>
              </div>
            ))}
          </div>
        </div>
      )}
      {processedDocs.filter(d => d.skip).length > 0 && (
        <div className="mt-2 text-xs text-surface-400">
          Пропущено (дубликаты): {processedDocs.filter(d => d.skip).length}
        </div>
      )}

      {error && (
        <div className="mt-3 bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg text-sm">{error}</div>
      )}

      <div className="flex gap-3 mt-4">
        <button onClick={onUploadMore}
          className="btn flex-1 py-2.5 text-sm text-surface-600 bg-surface-50 border border-surface-200 hover:bg-surface-100">
          <Plus size={16} />
          Загрузить ещё
        </button>
        <button onClick={onGenerate} disabled={validDocs.length === 0} className="btn-primary flex-1 py-2.5 text-sm">
          <Sparkles size={16} />
          Доработать
        </button>
      </div>
    </div>
  )
}
