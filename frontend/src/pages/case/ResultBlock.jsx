import React, { useState } from 'react'
import { Loader, Scale, Check, Copy, Download, X, Mail } from 'lucide-react'
import ReviewerBadge from '../../components/ReviewerBadge'
import NormHighlight from '../../components/NormHighlight'
import { useAuth } from '../../hooks/useAuth'
import RatingBar from './RatingBar'
import api from '../../api'

function ReferralBlock() {
  const [copied, setCopied] = React.useState(false)
  const { user } = useAuth()
  const uid = user?.id || ''
  const publicOrigin = typeof window !== 'undefined' ? window.location.origin : 'https://example.com'
  const refUrl = uid ? (`${publicOrigin}/login?ref=${uid.slice(0, 8)}`) : null
  const handleCopy = () => {
    navigator.clipboard.writeText(refUrl).then(() => {
      api.trackReferralCopy().catch(() => {})
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }).catch(() => {})
  }
  if (!refUrl) return null
  return (
    <div className="mt-2 py-2 text-center text-sm text-surface-900">
      <div className="text-sm text-surface-600">{'👥'} Пригласите коллегу — получите по 3 документа</div>
      <button onClick={handleCopy} className="mt-1 inline-flex items-center gap-1 text-[11px] px-3 py-1 rounded-full bg-brand-50 hover:bg-brand-100 text-brand-700 border border-brand-200 transition-colors">
        {copied ? <><Check size={14} className="text-emerald-500" /> Скопировано</> : <><Copy size={14} /> Скопировать ссылку</>}
      </button>
    </div>
  )
}

function EmailSendModal({ caseId, userEmail, onClose }) {
  const [email, setEmail] = useState(userEmail || '')
  const [sending, setSending] = useState(false)
  const [sent, setSent] = useState(false)
  const [error, setError] = useState('')

  const handleSend = async () => {
    if (!email.trim()) return
    setSending(true); setError('')
    try {
      const api = (await import('../../api')).default
      await api.sendDocxEmail(caseId, email.trim())
      setSent(true)
    } catch (e) { setError(e.message || 'Ошибка отправки') }
    finally { setSending(false) }
  }

  if (sent) return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50">
      <div className="bg-white rounded-2xl p-6 max-w-sm w-full text-center">
        <div className="text-4xl mb-3">✅</div>
        <p className="font-semibold mb-1">Отправлено!</p>
        <p className="text-sm text-surface-500 mb-4">Решение отправлено на {email}</p>
        <button onClick={onClose} className="btn-primary px-6 py-2">OK</button>
      </div>
    </div>
  )

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50">
      <div className="bg-white rounded-2xl p-6 max-w-sm w-full">
        <h3 className="font-semibold text-lg mb-4">Отправить документ на email</h3>
        <input type="email" value={email} onChange={e => setEmail(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && handleSend()}
          placeholder="Email" autoFocus
          className="w-full px-4 py-3 border border-surface-300 rounded-lg mb-3 outline-none focus:border-brand-500" />
        {error && <p className="text-red-500 text-sm mb-3">{error}</p>}
        <div className="flex gap-2">
          <button onClick={onClose} className="flex-1 py-2 border border-surface-300 rounded-lg text-surface-600">Отмена</button>
          <button onClick={handleSend} disabled={!email.trim() || sending}
            className="flex-1 py-2 bg-brand-600 text-white rounded-lg disabled:opacity-40">
            {sending ? 'Отправка...' : 'Отправить'}
          </button>
        </div>
      </div>
    </div>
  )
}

function useEmailSend(caseId, userEmail, setShowEmailModal) {
  const [emailSending, setEmailSending] = useState(false)
  const [emailSent, setEmailSent] = useState(false)
  const handleEmailClick = async () => {
    if (userEmail) {
      setEmailSending(true)
      try {
        const api = (await import('../../api')).default
        await api.sendDocxEmail(caseId, userEmail)
        setEmailSent(true)
        setTimeout(() => setEmailSent(false), 3000)
      } catch { setShowEmailModal(true) }
      finally { setEmailSending(false) }
    } else {
      setShowEmailModal(true)
    }
  }
  return { emailSending, emailSent, handleEmailClick }
}

export default function ResultBlock({ isStreaming, isCompleted, isRegenerating, displayText, streamingText, text, error, caseData, validationResult, copied, processedDocs, onExport, onCopy, onRetry, onGenerate, hasChatHistory, showEmailModal, setShowEmailModal, userEmail }) {
  const { emailSending, emailSent, handleEmailClick } = useEmailSend(caseData?.id, userEmail, setShowEmailModal)
  return (
    <div className="mb-6">
      {/* Заголовок */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2.5">
          {isStreaming && !streamingText && !text ? (
            <Loader size={18} className="text-brand-600 animate-spin shrink-0" />
          ) : (
            <Scale size={18} className="text-brand-600 shrink-0" />
          )}
          <h2 className="text-lg font-display font-semibold">
            {isStreaming && !streamingText && !text ? 'ИИ составляет документ...' : 'Документ'}
          </h2>
          {isStreaming && streamingText && (
            <span className="text-xs text-brand-500 font-normal">{streamingText.length.toLocaleString()} симв.</span>
          )}
        </div>

      </div>

      {error && isCompleted && (
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg text-sm mb-3">{error}</div>
      )}

      {/* Карточка ожидания */}
      {isStreaming && !streamingText && !text && (
        <div className="card p-4 border-brand-200 bg-brand-50">
          <div className="flex items-center gap-3">
            <Loader size={20} className="text-brand-600 animate-spin shrink-0" />
            <div className="flex-1 min-w-0">
              <div className="text-sm font-medium text-brand-800">ИИ составляет документ...</div>
              <div className="text-xs text-brand-600 mt-0.5">
                {processedDocs.length > 0
                  ? `На основе ${processedDocs.filter(d => !d.error && !d.skip).length} документов`
                  : 'Анализ материалов и подготовка'}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* AI-ревизор: бейдж */}
      {isCompleted && validationResult && !hasChatHistory && (
        <ReviewerBadge validationResult={validationResult} />
      )}

      {/* Текст решения */}
      {displayText && (
        <div className={`card p-5 sm:p-6 transition-opacity duration-300 ${isRegenerating ? 'opacity-40' : ''}`}>
          <div className="prose prose-sm max-w-none text-surface-800 leading-relaxed whitespace-pre-wrap text-sm">
            <NormHighlight
              text={displayText}
              validationResult={validationResult}
              isStreaming={isStreaming && !!streamingText}
            />
            {isStreaming && streamingText && (
              <span className="inline-block w-2 h-4 bg-brand-500 animate-pulse ml-0.5 -mb-0.5" />
            )}
          </div>
        </div>
      )}



      {/* Счётчик токенов */}
      {isCompleted && caseData?.tokens_used && (
        <div className="mt-1 text-[11px] text-surface-400 text-right">
          Токенов: {((caseData.tokens_used.prompt_tokens || 0) + (caseData.tokens_used.completion_tokens || 0)).toLocaleString()}
        </div>
      )}


      {/* Предупреждение о хранении */}
      {isCompleted && (
        <div className="mt-2 px-2 py-1.5 bg-amber-50/70 border border-amber-100 rounded text-[11px] text-amber-600/80 text-center">
          Готовые дела хранятся 30 дней. Сохраните результаты.
        </div>
      )}

      {/* Кнопки: Скачать + Копировать */}
      {isCompleted && (
        <div className="grid grid-cols-3 gap-2 mt-4">
          <button onClick={onExport}
            className="flex flex-col items-center justify-center gap-1 py-2 rounded-lg text-xs font-medium text-brand-700 bg-brand-50 border border-brand-200 hover:bg-brand-100 transition-colors">
            <Download size={18} />
            <span>Скачать</span>
          </button>
          <button onClick={onCopy}
            className="flex flex-col items-center justify-center gap-1 py-2 rounded-lg text-xs font-medium text-surface-700 bg-surface-50 border border-surface-200 hover:bg-surface-100 transition-colors">
            {copied ? <Check size={18} className="text-emerald-500" /> : <Copy size={18} />}
            <span>{copied ? 'Готово!' : 'Копировать'}</span>
          </button>
          <button onClick={handleEmailClick} disabled={emailSending}
            className="flex flex-col items-center justify-center gap-1 py-2 rounded-lg text-xs font-medium text-surface-700 bg-surface-50 border border-surface-200 hover:bg-surface-100 transition-colors disabled:opacity-50">
            <Mail size={18} />
            <span>{emailSent ? 'Отправлено!' : emailSending ? '...' : 'На email'}</span>
          </button>
        </div>
      )}

      {/* Реферальный блок */}
      {isCompleted && <ReferralBlock />}

      {/* Кнопка скрыть */}
      {isStreaming && (
        <button onClick={onGenerate}
          className="btn w-full py-2.5 mt-3 text-sm text-surface-600 bg-surface-50 border border-surface-200 hover:bg-surface-100">
          <X size={16} />
          Скрыть (генерация продолжится)
        </button>
      )}
    </div>
  )
}
