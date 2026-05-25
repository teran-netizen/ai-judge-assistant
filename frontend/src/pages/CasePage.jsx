import { useRef, useState, useEffect } from 'react'
import { useOutletContext, useParams } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'
import { useJudge } from '../hooks/JudgeContext'
import useCaseLifecycle from '../hooks/useCaseLifecycle'
import { ymGoal } from '../ym'
import api from '../api'
import { Loader, Sparkles, FolderOpen, Send } from 'lucide-react'

import { UpsellModal, PaywallModal } from './case/PaymentModals'
import EmptyPhase from './case/EmptyPhase'
import ProcessingPhase from './case/ProcessingPhase'
import ReadyPhase from './case/ReadyPhase'
import ResultBlock from './case/ResultBlock'
import RatingBar from './case/RatingBar'
import { UserBubble, AssistantBubble, FilesBubble, CaseBubble, ProcessedDocsBubble } from './case/ChatBubbles'
import EmailCollectModal from './case/EmailCollectModal'
import ErrorPhase from './case/ErrorPhase'
import useChunkedUpload from '../hooks/useChunkedUpload'

const ACCEPTED_ALL = '.jpg,.jpeg,.png,.webp,.heic,.heif,.bmp,.tiff,.tif,.pdf,.doc,.docx,.txt,.rtf,.odt'
const ALLOWED_RE = /\.(jpg|jpeg|png|pdf|webp|heic|heif|bmp|tiff|tif|doc|docx|txt|rtf|odt)$/i

export default function CasePage() {
  const { id } = useParams()
  const { user, refreshUser } = useAuth()
  const { refreshCases, activeJudgeId } = useOutletContext()
  const { activeJudge } = useJudge()

  useEffect(() => { if (id) ymGoal('page_case', { case_id: id }) }, [id])

  // Auto-confirm payment when returning from Tochka
  const [paymentJustConfirmed, setPaymentJustConfirmed] = useState(false)
  const pendingPollRef = useRef(null)
  useEffect(() => {
    const hasBalance = (u) => {
      if (!u) return false
      if ((u.paid_cases_left || 0) > 0) return true
      if ((u.free_cases_left || 0) > 0) return true
      if (u.subscription_until && new Date(u.subscription_until) > new Date()) return true
      return false
    }

    const startPendingPoll = () => {
      if (pendingPollRef.current) clearInterval(pendingPollRef.current)
      const startedAt = Date.now()
      pendingPollRef.current = setInterval(async () => {
        if (Date.now() - startedAt > 10 * 60 * 1000) {
          clearInterval(pendingPollRef.current)
          pendingPollRef.current = null
          return
        }
        try {
          await refreshUser()
          if (hasBalance(user)) {
            api.clearPendingPayment()
            clearInterval(pendingPollRef.current)
            pendingPollRef.current = null
          }
        } catch {}
      }, 10000)
    }

    const params = new URLSearchParams(window.location.search)
    if (params.get('payment') === 'success') {
      const opId = params.get('op') || ''
      const txId = params.get('tx') || ''
      api.confirmPayment(opId, txId)
        .then(() => {
          api.clearPendingPayment()
          refreshUser()
          setPaymentJustConfirmed(true)
          window.history.replaceState(null, '', window.location.pathname)
        })
        .catch(() => {
          refreshUser()
          setPaymentJustConfirmed(true)
          window.history.replaceState(null, '', window.location.pathname)
          startPendingPoll()
        })
      return () => {
        if (pendingPollRef.current) clearInterval(pendingPollRef.current)
      }
    }

    const pending = api.getPendingPayment()
    if (pending && !hasBalance(user)) {
      api.confirmPayment(pending.operation_id, pending.transaction_id || '')
        .then(() => {
          api.clearPendingPayment()
          refreshUser()
          setPaymentJustConfirmed(true)
        })
        .catch(() => startPendingPoll())
    }
    return () => {
      if (pendingPollRef.current) clearInterval(pendingPollRef.current)
    }
  }, [])

  const lc = useCaseLifecycle(id, { refreshUser, refreshCases, activeJudgeId })
  const { uploadState, startUpload, cancelUpload } = useChunkedUpload(id)

  const fileInputRef = useRef()

  // Email collection modal
  const [showEmailModal, setShowEmailModal] = useState(false)
  const [pendingDocxEmail, setPendingDocxEmail] = useState(
    () => localStorage.getItem('pending_docx_email_' + id) || null
  )

  // Show email modal when generation starts (DISABLED — Unisender not configured yet)
  // useEffect(() => {
  //   if (lc.phase === 'generating' && lc.genStatus === 'generate') {
  //     const asked = localStorage.getItem('email_asked_' + user?.id)
  //     if (!asked && !user?.email) {
  //       setTimeout(() => setShowEmailModal(true), 3000)
  //     }
  //   }
  // }, [lc.phase, lc.genStatus, user?.id, user?.email])

  // Persist pendingDocxEmail to localStorage
  useEffect(() => {
    if (pendingDocxEmail && lc.caseId) {
      localStorage.setItem('pending_docx_email_' + lc.caseId, pendingDocxEmail)
    }
  }, [pendingDocxEmail, lc.caseId])

  // Send docx after generation completes (if email was collected)
  useEffect(() => {
    const emailToSend = pendingDocxEmail || localStorage.getItem('pending_docx_email_' + lc.caseId)
    if (lc.phase === 'completed' && emailToSend && lc.caseId) {
      api.sendDocxEmail(lc.caseId, emailToSend)
        .then(() => {
          localStorage.removeItem('pending_docx_email_' + lc.caseId)
          setPendingDocxEmail(null)
        })
        .catch(() => {})
    }
  }, [lc.phase, pendingDocxEmail, lc.caseId])

  // Upsell modal for cases billing
  const [showUpsell, setShowUpsell] = useState(false)
  const [showPaywall, setShowPaywall] = useState(false)

  // Listen for backend 402 (paywall-required) dispatched from useCaseLifecycle.
  // Backend refuses /process for no-balance users → open paywall so they can pay.
  useEffect(() => {
    const onPaywall = () => setShowPaywall(true)
    window.addEventListener('paywall-required', onPaywall)
    return () => window.removeEventListener('paywall-required', onPaywall)
  }, [])
  const isCasesBilling = user?.billing_model === 'cases'
  const hasCases = (user?.free_cases_left || 0) + (user?.paid_cases_left || 0) > 0
  const hasSubscription = user?.subscription_until && new Date(user.subscription_until) > new Date()
  const judgeHasCases = (activeJudge?.paid_cases_left || 0) > 0
  const judgeHasSub = activeJudge?.is_vip || (activeJudge?.subscription_until && new Date(activeJudge.subscription_until) > new Date())
  const canGenerate = !isCasesBilling || hasCases || hasSubscription || judgeHasCases || judgeHasSub

  // Paywall strategy: always BEFORE OCR.
  // If user lacks balance → upload files first (so they survive the payment redirect),
  // then show paywall. Otherwise go straight to process (OCR + generate).
  const handleUploadOrPaywall = async () => {
    if (!lc.instructions?.trim()) {
      lc.setError?.('Опишите какой документ нужно составить')
      return
    }
    try { api.trackAction('click_generate', `files=${lc.files.length} uploaded=${lc.uploadedFilesCount} instr=${lc.instructions?.length || 0}`, lc.caseId) } catch {}
    if (isCasesBilling && !canGenerate) {
      try {
        await lc.ensureFilesUploaded()
      } catch (e) {
        lc.setError(e.message)
        return
      }
      try { api.trackAction('paywall_shown', 'pre_ocr', lc.caseId) } catch {}
      setShowPaywall(true)
    } else {
      // generate_start is now tracked inside handleUploadAndProcess after createCase (has caseId)
      lc.handleUploadAndProcess()
    }
  }

  // Auto-start processing after returning from payment (files already uploaded on server)
  useEffect(() => {
    if (paymentJustConfirmed && lc.phase === 'empty' && lc.caseId) {
      setPaymentJustConfirmed(false)
      // Files are on server (uploaded before paywall redirect), trigger process directly
      lc.handleRetryProcess()
    }
  }, [paymentJustConfirmed, lc.phase, lc.caseId])

  // Auto-start when user returns from SBP without redirect (checker credited payment)
  // Case is draft, has files on server, user now has balance → start processing
  const autoStartedRef = useRef(false)
  useEffect(() => {
    if (autoStartedRef.current) return
    if (lc.phase === 'empty' && lc.caseId && lc.caseData?.status === 'draft' && canGenerate && lc.uploadedFilesCount > 0) {
      autoStartedRef.current = true
      lc.handleRetryProcess()
    }
  }, [lc.phase, lc.caseId, lc.caseData?.status, canGenerate, lc.uploadedFilesCount])

  // Show upsell after first completed generation
  useEffect(() => {
    if (isCasesBilling && lc.phase === 'completed' && !hasCases && !hasSubscription) {
      const shown = localStorage.getItem('upsell_shown_' + user?.id)
      if (!shown) {
        setShowUpsell(true)
        localStorage.setItem('upsell_shown_' + user?.id, 'true')
      }
    }
  }, [lc.phase, isCasesBilling, hasCases, hasSubscription, user?.id])
  const addFileInputRef = useRef()
  const textareaRef = useRef()

  // ── File handling ──────────────────────────────────────

  const addFiles = (newFiles) => {
    const valid = []
    const rejected = []
    for (const f of [...newFiles]) {
      const isImage = f.type?.startsWith('image/')
      const nameOk = ALLOWED_RE.test(f.name)
      if (!nameOk && !isImage) {
        rejected.push(`${f.name}: неподдерживаемый формат`)
      } else if (f.size > 20 * 1024 * 1024) {
        rejected.push(`${f.name}: больше 20 МБ`)
      } else {
        valid.push(f)
      }
    }
    if (rejected.length > 0) lc.setError(`Пропущено: ${rejected.join(', ')}`)
    else lc.setError('')
    if (valid.length > 0) {
      lc.setFiles(prev => [...prev, ...valid])
    }
  }

  const removeFile = (i) => lc.setFiles(prev => prev.filter((_, idx) => idx !== i))
  const totalSize = lc.files.reduce((acc, f) => acc + f.size, 0)

  const handleTextareaInput = (e) => {
    lc.setRefineText(e.target.value)
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
      textareaRef.current.style.height = Math.min(textareaRef.current.scrollHeight, 160) + 'px'
    }
  }

  // ── Derived state ──────────────────────────────────────

  // ResultBlock всегда показывает final_text — это текст после AI-ревизора с корректными
  // позициями для NormHighlight. Доработки идут ниже в чат-пузырях.
  const text = lc.caseData?.final_text || lc.caseData?.generated_text || ''
  const isStreaming = lc.phase === 'generating' && lc.genStatus === 'generate'
  const isCompleted = lc.phase === 'completed'
  const displayText = lc.streamingText || text
  const showResult = (isStreaming && (!!lc.streamingText || !!text)) || (isCompleted && !!text)
  const isRegenerating = isStreaming && !!text && !lc.streamingText

  // ── Loading ────────────────────────────────────────────

  if (lc.phase === 'loading') {
    return (
      <div className="flex justify-center items-center flex-1">
        <div className="w-8 h-8 border-[3px] border-brand-200 border-t-brand-600 rounded-full animate-spin" />
      </div>
    )
  }

  // ── Render ─────────────────────────────────────────────

  return (
    <div className="flex flex-col flex-1 min-h-0">
      {showUpsell && <UpsellModal onClose={() => setShowUpsell(false)} />}
      {showPaywall && <PaywallModal onClose={() => setShowPaywall(false)} promo={user?.promo_price} returnUrl={lc.caseId ? `${window.location.origin}/cases/${lc.caseId}?payment=success` : ''} />}
      {showEmailModal && (
        <EmailCollectModal
          caseId={lc.caseId}
          onClose={() => {
            setShowEmailModal(false)
            localStorage.setItem('email_asked_' + user?.id, 'true')
          }}
          onSuccess={() => {
            setShowEmailModal(false)
            localStorage.setItem('email_asked_' + user?.id, 'true')
            refreshUser()
          }}
          onEmailCollected={(email) => setPendingDocxEmail(email)}
        />
      )}
      <div ref={lc.scrollRef} className="flex-1 overflow-y-auto overflow-x-hidden">
        <div className="max-w-2xl mx-auto px-4 py-6">

          {/* === ФАЗА: Пустой экран (новое дело) === */}
          {lc.phase === 'empty' && (
            <EmptyPhase
              files={lc.files}
              instructions={lc.instructions}
              error={lc.error}
              fileInputRef={fileInputRef}
              totalSize={totalSize}
              addFiles={addFiles}
              removeFile={removeFile}
              setInstructions={lc.setInstructions}
              onUpload={handleUploadOrPaywall}
              onDeleteDraft={async () => {
                if (!lc.caseId) return
                if (!confirm('Удалить черновик и все загруженные файлы?')) return
                try {
                  await api.deleteCase(lc.caseId)
                  refreshCases?.()
                  window.location.href = '/cases/new'
                } catch (e) {
                  lc.setError?.(e.message || 'Не удалось удалить')
                }
              }}
              caseId={lc.caseId}
              uploadedFilesCount={lc.uploadedFilesCount}
              isUploading={lc.isUploading}
              uploadPercent={lc.uploadPercent}
            />
          )}

          {/* === ПУЗЫРЬ: Загруженные файлы (после отправки) === */}
          {lc.phase !== 'empty' && lc.phase !== 'loading' && lc.files.length > 0 && (
            <FilesBubble files={lc.files} totalSize={totalSize} instructions={lc.instructions} />
          )}

          {/* === Пузырь для открытого из сайдбара дела === */}
          {lc.phase !== 'empty' && lc.phase !== 'loading' && lc.files.length === 0 && lc.caseData && (
            <CaseBubble caseData={lc.caseData} />
          )}

          {/* === ФАЗА: Обработка документов === */}
          {lc.phase === 'processing' && (
            <ProcessingPhase
              genStatus={lc.genStatus}
              processProgress={lc.processProgress}
              processingFile={lc.processingFile}
              processedDocs={lc.processedDocs}
              streamReconnect={lc.streamReconnect}
            />
          )}

          {/* === ФАЗА: Готово к генерации === */}
          {lc.phase === 'ready' && (
            <ReadyPhase
              processedDocs={lc.processedDocs}
              error={lc.error}
              onRemoveDoc={lc.handleRemoveDoc}
              onUploadMore={lc.handleUploadMore}
              onGenerate={lc.handleGenerate}
            />
          )}

          {/* === Загрузка файлов (прогресс-бар) === */}
          {lc.phase === 'generating' && lc.genStatus === 'upload' && (
            <div className="animate-in mb-6">
              <div className="card p-4 border-brand-200 bg-brand-50">
                <div className="flex items-center gap-3">
                  <Loader size={20} className="text-brand-600 animate-spin shrink-0" />
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium text-brand-800">Загрузка файлов... {lc.uploadPercent}%</div>
                    <div className="text-xs text-red-600 mt-1">Не закрывайте страницу до окончания загрузки</div>
                    <div className="w-full h-1.5 bg-brand-100 rounded-full overflow-hidden mt-1.5">
                      <div className="h-full bg-brand-500 rounded-full transition-all duration-300" style={{ width: `${lc.uploadPercent}%` }} />
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* === Блок обработанных документов (чат-стиль) === */}
          {lc.processedDocs.length > 0 && !['processing', 'ready', 'empty', 'loading'].includes(lc.phase) && (
            <ProcessedDocsBubble processedDocs={lc.processedDocs} totalFilesCount={lc.uploadedFilesCount} />
          )}

          {/* === Единый блок результата (генерация + завершено) === */}
          {(showResult || (lc.phase === 'generating' && lc.genStatus === 'generate')) && (
            <ResultBlock
              isStreaming={isStreaming}
              isCompleted={isCompleted}
              isRegenerating={isRegenerating}
              displayText={displayText}
              streamingText={lc.streamingText}
              text={text}
              error={lc.error}
              caseData={lc.caseData}
              validationResult={lc.validationResult}
              copied={lc.copied}
              processedDocs={lc.processedDocs}
              onExport={lc.handleExportDocx}
              onCopy={lc.handleCopy}
              onRetry={lc.handleRetry}
              onGenerate={lc.handleGenerate}
              hasChatHistory={lc.chatHistory.length > 0}
              showEmailModal={showEmailModal}
              setShowEmailModal={setShowEmailModal}
              userEmail={user?.email}
            />
          )}

          {/* === Чат-история доработок === */}
          {lc.chatHistory.length > 0 && isCompleted && (
            <div className="space-y-4 mb-6">
              {lc.chatHistory.map((msg, i) => (
                msg.role === 'user' ? (
                  <UserBubble key={`chat-${i}`} message={msg} />
                ) : (
                  <AssistantBubble
                    key={`chat-${i}`}
                    message={msg}
                    isStreaming={false}
                    caseId={lc.caseId}
                  />
                )
              ))}

              {/* Оценка после доработки */}
              {!lc.refining && lc.phase === 'completed' && (
                <div className="mt-2 mb-4">
                  <RatingBar caseId={lc.caseId} initialRating={lc.caseData?.rating || 0} />
                </div>
              )}

              {/* Текущий стриминг AI-ответа */}
              {lc.refining && (
                <AssistantBubble
                  message={{ content: lc.refineStreamingText, ts: null }}
                  isStreaming={true}
                  caseId={lc.caseId}
                />
              )}

            </div>
          )}

          {/* === ФАЗА: Ошибка === */}
          {lc.phase === 'error' && (
            <ErrorPhase
              error={lc.error}
              caseId={lc.caseId}
              processedDocs={lc.processedDocs}
              onRetry={lc.handleRetry}
              onRetryProcess={lc.handleRetryProcess}
              onUploadMore={lc.handleUploadMore}
            />
          )}

        </div>
      </div>

      {/* === Sticky поле доработки внизу === */}
      {lc.phase === 'completed' && text && (
        <div className="px-4 py-3">
          <div className="max-w-2xl mx-auto">
            {lc.refineError && (
              <div className="bg-red-50 border border-red-200 text-red-700 px-3 py-2 rounded-lg text-sm mb-2">
                {lc.refineError}
              </div>
            )}
            <div className="relative card border border-surface-200 focus-within:border-brand-400 transition-colors">
              <input
                ref={addFileInputRef}
                type="file"
                multiple
                accept={ACCEPTED_ALL}
                className="hidden"
                onChange={e => { lc.handleAddFilesFromCompleted(e.target.files); e.target.value = '' }}
              />
              <button
                onClick={() => addFileInputRef.current?.click()}
                className="absolute left-3 top-3 p-1.5 rounded-lg text-surface-400 hover:text-brand-600 hover:bg-brand-50 transition-colors"
                title="Загрузить документы"
              >
                <FolderOpen size={18} />
              </button>
              <textarea
                ref={textareaRef}
                value={lc.refineText}
                onChange={handleTextareaInput}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault()
                    lc.handleRefine()
                  }
                }}
                placeholder="Добавьте фотографии, документы или комментарий и нажмите на кнопку, чтобы доработать решение. Или задайте вопрос нейросети."
                rows={4}
                disabled={lc.refining}
                className="w-full pl-11 pr-12 py-3 bg-transparent text-sm resize-none outline-none placeholder:text-surface-400 disabled:opacity-50"
              />
              <button
                onClick={lc.handleRefine}
                disabled={!lc.refineText.trim() || lc.refining}
                className="absolute right-3 top-3 p-1.5 rounded-lg text-brand-600 hover:bg-brand-50 disabled:opacity-30 disabled:hover:bg-transparent transition-colors"
              >
                {lc.refining ? <Loader size={18} className="animate-spin" /> : <Send size={18} />}
              </button>
            </div>
            {lc.refining && (
              <div className="flex items-center gap-2 mt-2 text-xs text-brand-600">
                <Sparkles size={13} />
                ИИ дорабатывает решение...
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
