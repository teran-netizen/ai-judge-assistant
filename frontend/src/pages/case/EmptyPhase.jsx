import { Upload, X, FileImage, FileText, Check, Camera, FolderOpen, Scale, MessageSquare, Loader } from 'lucide-react'

const ACCEPTED_ALL = '.jpg,.jpeg,.png,.webp,.heic,.heif,.bmp,.tiff,.tif,.pdf,.doc,.docx,.txt,.rtf,.odt'

const isDocument = (name) => /\.(pdf|doc|docx|txt|rtf|odt)$/i.test(name)
const formatSize = (bytes) => {
  if (bytes < 1024) return `${bytes} Б`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} КБ`
  return `${(bytes / 1024 / 1024).toFixed(1)} МБ`
}

export default function EmptyPhase({ files, instructions, error, fileInputRef, totalSize, addFiles, removeFile, setInstructions, onUpload, onDeleteDraft, uploadedFilesCount, isUploading, uploadPercent, caseId }) {
  return (
    <div className="animate-in">
      <div className="flex flex-col items-center justify-center ">
        <h1 className="text-2xl font-display font-bold mb-1 text-center flex items-center justify-center gap-2"><Scale size={24} className="text-brand-500" />Новый документ</h1>
        <p className="text-surface-500 text-sm mb-8 text-center">Сфотографируйте или загрузите документы и нажмите на кнопку «Сгенерировать». Нейросеть подготовит юридический документ. Среднее время ожидания 2–7 минут.</p>

        {/* Desktop: drop zone */}
        <div
          className="hidden sm:block w-full card border-2 border-dashed border-surface-200 hover:border-brand-400 transition-colors p-8 text-center cursor-pointer mb-4"
          onClick={() => fileInputRef.current?.click()}
          onDragOver={e => { e.preventDefault(); e.currentTarget.classList.add('border-brand-500', 'bg-brand-50') }}
          onDragLeave={e => { e.currentTarget.classList.remove('border-brand-500', 'bg-brand-50') }}
          onDrop={e => { e.preventDefault(); e.currentTarget.classList.remove('border-brand-500', 'bg-brand-50'); addFiles(e.dataTransfer.files) }}
        >
          <Upload size={32} className="text-surface-400 mx-auto mb-3" />
          <p className="text-sm font-medium">Перетащите файлы или нажмите для выбора</p>
          <p className="text-xs text-surface-400 mt-1">Фото, PDF, DOC, DOCX, TXT — до 20 МБ каждый</p>
          <p className="text-xs text-surface-400 mt-1">Можно загружать до 100 файлов за раз. Для загрузки большего количества нажмите «Добавить ещё»</p>
        </div>

        {/* Mobile: camera + files */}
        <div className="sm:hidden grid grid-cols-2 gap-3 mb-4 w-full">
          <label htmlFor="camera-input"
            className="flex flex-col items-center gap-2 p-5 rounded-xl border-2 border-dashed border-surface-200 active:border-brand-500 active:bg-brand-50 transition-colors cursor-pointer">
            <Camera size={28} className="text-brand-600" />
            <span className="text-sm font-medium">Камера</span>
            <span className="text-xs text-surface-400">Сфотографировать</span>
          </label>
          <label htmlFor="file-input"
            className="flex flex-col items-center gap-2 p-5 rounded-xl border-2 border-dashed border-surface-200 active:border-brand-500 active:bg-brand-50 transition-colors cursor-pointer">
            <FolderOpen size={28} className="text-brand-600" />
            <span className="text-sm font-medium">Файлы</span>
            <span className="text-xs text-surface-400">Фото, PDF, DOC</span>
          </label>
        </div>
        <p className="sm:hidden text-xs text-surface-400 text-center -mt-2 mb-2">Можно загружать до 100 файлов за раз. Нажмите ещё раз для дозагрузки</p>

        {/* Hidden file inputs */}
        <input id="camera-input" type="file" accept="image/*" capture="environment" className="hidden"
          onChange={e => { addFiles(e.target.files); e.target.value = '' }} />
        <input id="file-input" ref={fileInputRef} type="file" multiple accept={ACCEPTED_ALL} className="hidden"
          onChange={e => { addFiles(e.target.files); e.target.value = '' }} />

        {/* File list */}
        {files.length > 0 && (
          <div className="w-full mb-6">
            <div className="flex items-center justify-between text-sm font-medium text-surface-700 mb-2">
              <span>Файлов: {files.length}</span>
              <span className="text-surface-400 text-xs">{formatSize(totalSize)}</span>
            </div>
            <div className="grid grid-cols-3 sm:grid-cols-4 gap-2 max-h-60 overflow-y-auto">
              {files.map((f, i) => (
                <div key={`${f.name}-${f.size}-${i}`}
                  className="relative flex items-center gap-2 bg-surface-50 rounded-lg px-3 py-2 text-sm group animate-in"
                  style={{ animationDelay: `${i * 40}ms` }}>
                  {isDocument(f.name)
                    ? <FileText size={16} className="text-blue-500 shrink-0" />
                    : <FileImage size={16} className="text-surface-400 shrink-0" />}
                  <span className="truncate flex-1 text-xs">{f.name}</span>
                  <Check size={13} className="text-emerald-500 shrink-0" />
                  <button onClick={() => removeFile(i)} className="text-surface-400 hover:text-red-500 sm:opacity-0 sm:group-hover:opacity-100 transition-opacity">
                    <X size={14} />
                  </button>
                </div>
              ))}
            </div>
            <div className="sm:hidden flex gap-2 mt-2">
              <label htmlFor="camera-input" className="flex-1 text-xs text-center text-brand-600 py-2 rounded-lg border border-brand-200 active:bg-brand-50 cursor-pointer">
                + Ещё фото
              </label>
              <label htmlFor="file-input" className="flex-1 text-xs text-center text-brand-600 py-2 rounded-lg border border-brand-200 active:bg-brand-50 cursor-pointer">
                + Ещё файлы
              </label>
            </div>
          </div>
        )}

        {/* Instructions */}
        <div className="w-full mb-6">
          <label className="text-sm font-medium text-surface-700 mb-1.5 flex items-center gap-1.5">
            <MessageSquare size={14} className="text-surface-400" />
            Указания для ИИ
            <span className="text-surface-400 font-normal">(опишите какой документ нужен)</span>
          </label>
          <textarea
            value={instructions}
            onChange={e => setInstructions(e.target.value)}
            placeholder="Опишите документ или вопрос. Например: Напиши мотивированное решение суда, распиши подробно нормы ГК и пленумы. Или: Составь исковое заявление о взыскании долга. Или: Проанализируй договор — какие есть риски и правовые последствия?"
            rows={6}
            className="input resize-y min-h-[160px] w-full"
          />
        </div>

        {/* v2: Upload progress */}
        {isUploading && (
          <div className="w-full mb-4 animate-in">
            <div className="card p-4 border-brand-200 bg-brand-50">
              <div className="flex items-center gap-3">
                <Loader size={20} className="text-brand-600 animate-spin shrink-0" />
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium text-brand-800">Загрузка файлов... {uploadPercent}%</div>
                  <div className="text-xs text-red-600 mt-1">Не закрывайте страницу до окончания загрузки</div>
                  <div className="w-full h-1.5 bg-brand-100 rounded-full overflow-hidden mt-1.5">
                    <div className="h-full bg-brand-500 rounded-full transition-all duration-300" style={{ width: `${uploadPercent}%` }} />
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* v2: Uploaded files counter */}
        {uploadedFilesCount > 0 && !isUploading && (
          <div className="w-full mb-4 animate-in">
            <div className="card p-3 border-emerald-200 bg-emerald-50 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Check size={18} className="text-emerald-600 shrink-0" />
                <span className="text-sm font-medium text-emerald-800">
                  Загружено: {uploadedFilesCount} документов
                </span>
              </div>
              {caseId && onDeleteDraft && (
                <button onClick={onDeleteDraft}
                  className="text-xs text-red-500 hover:text-red-700 px-2 py-1 rounded hover:bg-red-50 transition-colors">
                  Удалить
                </button>
              )}
            </div>
          </div>
        )}

        {error && (
          <div className="w-full bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg text-sm mb-4">
            <div className="whitespace-pre-line">{error}</div>
          </div>
        )}

        <button onClick={onUpload} disabled={isUploading} className="btn-primary w-full py-3 text-base">
          {isUploading ? 'Загрузка...' : 'Сгенерировать'}
        </button>
      </div>
    </div>
  )
}
