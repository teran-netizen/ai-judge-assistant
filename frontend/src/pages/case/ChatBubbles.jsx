import { useState } from 'react'
import { Upload, FileImage, FileText, Loader, Sparkles, Check, Scale, CheckCircle2, Copy, Download } from 'lucide-react'
import ReviewerBadge from '../../components/ReviewerBadge'
import NormHighlight from '../../components/NormHighlight'
import RatingBar from './RatingBar'
import api from '../../api'

const isDocument = (name) => /\.(pdf|doc|docx|txt|rtf|odt)$/i.test(name)
const formatSize = (bytes) => {
  if (bytes < 1024) return `${bytes} Б`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} КБ`
  return `${(bytes / 1024 / 1024).toFixed(1)} МБ`
}

export function UserBubble({ message }) {
  return (
    <div className="flex justify-end animate-in">
      <div className="max-w-[85%] bg-brand-50 border border-brand-200 rounded-2xl rounded-tr-md px-4 py-3">
        <p className="text-sm text-surface-800 whitespace-pre-wrap">{message.content}</p>
        {message.files?.length > 0 && (
          <div className="mt-2 flex gap-1 flex-wrap">
            {message.files.map((f, i) => (
              <span key={i} className="text-xs bg-brand-100 px-2 py-0.5 rounded">📎 {f}</span>
            ))}
          </div>
        )}
        {message.ts && (
          <p className="text-[10px] text-surface-400 mt-1">
            {new Date(message.ts).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })}
          </p>
        )}
      </div>
    </div>
  )
}

export function AssistantBubble({ message, isStreaming, caseId }) {
  const [copied, setCopied] = useState(false)
  const [downloading, setDownloading] = useState(false)
  const text = message.content || ''

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      setCopied(false)
    }
  }

  const handleDownload = async () => {
    if (!caseId || downloading) return
    setDownloading(true)
    try {
      // Сохраняем текст как final_text, затем скачиваем DOCX
      await api.saveFinal(caseId, text)
      const url = (import.meta.env.VITE_API_URL || '') + '/api/cases/' + caseId + '/export/docx'
      const a = document.createElement('a')
      a.href = url
      a.download = ''
      a.target = '_blank'
      a.rel = 'noopener'
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
    } catch {
      // silently ignore
    } finally {
      setDownloading(false)
    }
  }

  return (
    <div className="flex justify-start animate-in">
      <div className="max-w-full w-full">
        {/* Заголовок */}
        <div className="flex items-center gap-2 mb-1">
          <Sparkles size={14} className="text-brand-500" />
          <span className="text-xs font-medium text-brand-600">AI-доработка</span>
          {message.tokens_used && (
            <span className="text-[10px] text-surface-400">~{message.tokens_used} токенов</span>
          )}
          {/* Кнопки: Скачать DOCX + Копировать (только после завершения) */}
          {!isStreaming && text && (
            <div className="ml-auto flex items-center gap-1">
              <button onClick={handleDownload} disabled={downloading}
                className="flex items-center gap-1 text-xs text-surface-400 hover:text-brand-600 py-1 px-2 rounded-lg hover:bg-brand-50 transition-colors disabled:opacity-50">
                {downloading ? <Loader size={13} className="animate-spin" /> : <Download size={13} />}
                Word
              </button>
              <button onClick={handleCopy}
                className="flex items-center gap-1 text-xs text-surface-400 hover:text-brand-600 py-1 px-2 rounded-lg hover:bg-brand-50 transition-colors">
                {copied ? <Check size={13} className="text-emerald-500" /> : <Copy size={13} />}
                {copied ? 'Скопировано' : 'Копировать'}
              </button>
            </div>
          )}
        </div>

        {/* Бейджи валидации или спиннер ожидания */}
        {!isStreaming && message.validation_result && (
          <ReviewerBadge validationResult={message.validation_result} />
        )}
        {!isStreaming && text && !message.validation_result && (
          <div className="flex items-center gap-2 py-2 text-xs text-surface-500">
            <Loader size={13} className="animate-spin text-brand-500" />
            Идёт валидация правовых норм AI-ревизором...
          </div>
        )}

        {/* Карточка с текстом */}
        <div className="card border border-surface-200 p-4 sm:p-5">
          <div className="prose prose-sm max-w-none text-surface-800 whitespace-pre-wrap leading-relaxed text-sm">
            {!isStreaming && message.validation_result ? (
              <NormHighlight text={text} validationResult={message.validation_result} />
            ) : (
              text
            )}
            {isStreaming && text && (
              <span className="inline-block w-2 h-4 bg-brand-500 animate-pulse ml-0.5 -mb-0.5" />
            )}
          </div>
          {isStreaming && !text && (
            <div className="flex items-center gap-2 text-sm text-surface-400">
              <Loader size={14} className="animate-spin" />
              ИИ дорабатывает документ...
            </div>
          )}
        </div>

        {/* Рейтинг — перенесён в CasePage */}
        {false && (
          <RatingBar caseId={caseId} initialRating={0} />
        )}

        {/* Время */}
        {message.ts && (
          <p className="text-[10px] text-surface-400 mt-1">
            {new Date(message.ts).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })}
          </p>
        )}
      </div>
    </div>
  )
}

export function FilesBubble({ files, totalSize, instructions }) {
  return (
    <div className="animate-in mb-6">
      <div className="bg-brand-50 border border-brand-100 rounded-xl p-4">
        <div className="flex items-center gap-2 text-sm font-medium text-brand-800 mb-2">
          <Upload size={15} />
          Загружено файлов: {files.length}
          <span className="text-brand-500 text-xs font-normal">({formatSize(totalSize)})</span>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {files.slice(0, 8).map((f, i) => (
            <span key={i} className="inline-flex items-center gap-1 bg-white/70 rounded px-2 py-0.5 text-xs text-brand-700">
              {isDocument(f.name) ? <FileText size={12} /> : <FileImage size={12} />}
              {f.name.length > 20 ? f.name.slice(0, 17) + '...' : f.name}
            </span>
          ))}
          {files.length > 8 && <span className="text-xs text-brand-500">+{files.length - 8} ещё</span>}
        </div>
        {instructions && (
          <div className="mt-2 pt-2 border-t border-brand-100 text-sm text-brand-700">
            <span className="text-brand-500 text-xs">Указания: </span>{instructions}
          </div>
        )}
      </div>
    </div>
  )
}

export function CaseBubble({ caseData }) {
  return (
    <div className="animate-in mb-6">
      <div className="bg-brand-50 border border-brand-100 rounded-xl p-4">
        <div className="flex items-center gap-2 text-sm font-medium text-brand-800">
          <Scale size={15} />
          {caseData.title || 'Дело'}
        </div>
        {caseData.user_instructions && (
          <div className="mt-2 pt-2 border-t border-brand-100 text-sm text-brand-700">
            <span className="text-brand-500 text-xs">Указания: </span>{caseData.user_instructions}
          </div>
        )}
      </div>
    </div>
  )
}

export function ProcessedDocsBubble({ processedDocs, totalFilesCount }) {
  const validDocs = processedDocs.filter(d => !d.error && !d.skip)
  const errorDocs = processedDocs.filter(d => d.error)
  const totalDocs = totalFilesCount || processedDocs.filter(d => !d.skip).length
  return (
    <div className="mb-4">
      <div className="bg-surface-50 border border-surface-100 rounded-xl p-4">
        <div className="flex items-center gap-2 text-sm font-medium text-surface-700 mb-3">
          <CheckCircle2 size={15} className={errorDocs.length > 0 ? "text-amber-500 shrink-0" : "text-emerald-500 shrink-0"} />
          {"Распознано"} {validDocs.length} {"из"} {totalDocs} {"документов"}
        </div>
        <div className="space-y-2">
          {validDocs.map((doc, i) => (
            <div key={i} className="flex items-start gap-2 text-xs">
              <FileText size={12} className="text-emerald-400 shrink-0 mt-0.5" />
              <div className="min-w-0">
                <div className="text-surface-700 break-words">{doc.summary_line}</div>
                <div className="text-surface-400 break-words">{doc.filename}</div>
              </div>
            </div>
          ))}
          {errorDocs.length > 0 && (
            <>
              <div className="border-t border-surface-200 my-2" />
              <div className="text-xs font-medium text-red-500 mb-1">{"Не удалось распознать"} ({errorDocs.length}):</div>
              {errorDocs.map((doc, i) => (
                <div key={"err-"+i} className="flex items-start gap-2 text-xs">
                  <FileText size={12} className="text-red-400 shrink-0 mt-0.5" />
                  <div className="min-w-0">
                    <div className="text-red-500 break-words">{doc.filename || "Неизвестный файл"}</div>
                  </div>
                </div>
              ))}
            </>
          )}
        </div>
      </div>
    </div>
  )
}
