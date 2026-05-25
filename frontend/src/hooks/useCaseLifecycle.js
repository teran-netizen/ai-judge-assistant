/**
 * useCaseLifecycle — вся логика жизненного цикла дела:
 * загрузка, обработка файлов, стриминг генерации, SSE, валидация.
 *
 * Извлечён из CasePage.jsx для уменьшения god-component.
 */
import { useState, useRef, useEffect, useCallback } from 'react'
import api from '../api'
import { useAuth } from './useAuth'
import { useJudge } from './JudgeContext'
import { ymGoal } from '../ym'

// Wake Lock: keep screen on during upload/processing
async function acquireWakeLock() {
  try {
    if ('wakeLock' in navigator) return await navigator.wakeLock.request('screen')
  } catch { /* ignore */ }
  return null
}

export default function useCaseLifecycle(id, { refreshUser, refreshCases, activeJudgeId: passedJudgeId }) {
  const { user: _authUser } = useAuth()
  const { activeJudgeId: ctxJudgeId } = useJudge()
  const activeJudgeId = passedJudgeId || ctxJudgeId
  // Фаза: empty → uploading → processing → ready → generating → completed / error
  const [phase, setPhase] = useState(id ? 'loading' : 'empty')

  // Загрузка
  const [files, setFiles] = useState([])
  const [instructions, setInstructions] = useState('')
  const [genStatus, setGenStatus] = useState('')
  const [uploadPercent, setUploadPercent] = useState(0)
  const [isUploading, setIsUploading] = useState(false)
  const [error, setError] = useState('')
  const abortRef = useRef(null)

  // Аккумулятор: обработанные документы
  const [processedDocs, setProcessedDocs] = useState([])
  const [processingFile, setProcessingFile] = useState(null)
  const [processProgress, setProcessProgress] = useState({ index: 0, total: 0, pct: 0, stage: '' })

  // Стриминг
  const [streamingText, setStreamingText] = useState('')
  const streamRef = useRef(null)
  const processRef = useRef(null)
  const streamingTextRef = useRef('')
  const replayDedupRef = useRef({ active: false, cursor: 0, snapshot: '' })

  // Дело
  const [caseId, setCaseId] = useState(id || null)
  const [caseData, setCaseData] = useState(null)

  // Копирование
  const [copied, setCopied] = useState(false)

  // AI-ревизор (валидация норм)
  const [validationResult, setValidationResult] = useState(null)
  const [streamReconnect, setStreamReconnect] = useState({ state: 'idle', attempt: 0, delayMs: 0, maxRetries: 0 })
  const streamReconnectStateRef = useRef('idle')
  const reconnectHintTimerRef = useRef(null)

  // Доработка
  const [refineText, setRefineText] = useState('')
  const [refining, setRefining] = useState(false)
  const [refineError, setRefineError] = useState('')

  // Чат-история доработок
  const [chatHistory, setChatHistory] = useState([])
  const [refineStreamingText, setRefineStreamingText] = useState('')
  const refineStreamRef = useRef(null)

  // Скролл
  const scrollRef = useRef(null)

  // Polling ref для валидации
  const validationPollRef = useRef(null)

  const scrollToBottom = useCallback(() => {
    setTimeout(() => scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' }), 100)
  }, [])

  useEffect(() => {
    streamingTextRef.current = streamingText || ''
  }, [streamingText])

  // ── Validation polling (fallback) ──────────────────────

  const _pollValidation = useCallback((targetCaseId) => {
    if (validationPollRef.current) return
    let attempts = 0
    validationPollRef.current = setInterval(async () => {
      attempts++
      if (attempts > 24) {
        clearInterval(validationPollRef.current)
        validationPollRef.current = null
        return
      }
      try {
        const data = await api.getValidation(targetCaseId)
        if (data.has_validation && data.validation_result) {
          setValidationResult(data.validation_result)
          const caseUpdate = await api.getCase(targetCaseId)
          setCaseData(caseUpdate)
          clearInterval(validationPollRef.current)
          validationPollRef.current = null
        }
      } catch { /* ignore */ }
    }, 5000)
  }, [])

  // ── SSE: единый stream (process + generate прогресс) ──

  const connectStream = useCallback((targetCaseId, { onProgressCb } = {}) => {
    streamRef.current?.close()
    streamRef.current = null
    if (reconnectHintTimerRef.current) {
      clearTimeout(reconnectHintTimerRef.current)
      reconnectHintTimerRef.current = null
    }
    setStreamReconnect({ state: 'connecting', attempt: 0, delayMs: 0, maxRetries: 0 })

    // Fallback: if no data received within 5s, check if case already completed
    let receivedData = false
    const fallbackTimer = setTimeout(async () => {
      if (!receivedData) {
        try {
          const c = await api.getCase(targetCaseId)
          if (c.status === 'completed' && (c.final_text || c.generated_text)) {
            streamRef.current?.close()
            streamRef.current = null
            setCaseData(c)
            setStreamingText('')
            setPhase('completed')
            if (c.validation_result) setValidationResult(c.validation_result)
            refreshCases?.()
            return
          }
        } catch { /* ignore */ }
      }
    }, 5000)

    const es = api.streamCase(targetCaseId, {
      onChunk: (text) => {
        receivedData = true
        setStreamingText(prev => {
          const chunk = typeof text === 'string' ? text : String(text ?? '')
          if (!chunk) return prev

          const replay = replayDedupRef.current
          if (replay.active && replay.snapshot) {
            const expected = replay.snapshot.slice(replay.cursor, replay.cursor + chunk.length)
            if (expected === chunk) {
              replay.cursor += chunk.length
              if (replay.cursor >= replay.snapshot.length) {
                replay.active = false
              }
              return prev
            }
            replay.active = false
          }

          // Boundary overlap dedupe: protects from partial resend around reconnect edge.
          let overlap = 0
          const maxOverlap = Math.min(prev.length, chunk.length)
          for (let i = maxOverlap; i > 0; i -= 1) {
            if (prev.endsWith(chunk.slice(0, i))) {
              overlap = i
              break
            }
          }
          return prev + chunk.slice(overlap)
        })
        if (scrollRef.current) {
          const el = scrollRef.current
          const isNearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 200
          if (isNearBottom) {
            setTimeout(() => el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' }), 50)
          }
        }
      },
      onFull: (text) => {
        setStreamingText(text)
      },
      onDone: async () => {
        clearTimeout(fallbackTimer)
        replayDedupRef.current = { active: false, cursor: 0, snapshot: '' }
        setStreamReconnect({ state: 'done', attempt: 0, delayMs: 0, maxRetries: 0 })
        try {
          ymGoal('generate_success', { case_id: targetCaseId })
          api.trackAction('generate_complete', 'success', targetCaseId)
          await refreshUser()
          refreshCases?.()
          const data = await api.getCase(targetCaseId)
          setCaseData(data)
          setStreamingText('')
          setPhase('completed')
          setValidationResult(null)
          scrollToBottom()
        } catch {
          setPhase('completed')
        }
      },
      onValidation: async (validationData) => {
        streamRef.current = null
        replayDedupRef.current = { active: false, cursor: 0, snapshot: '' }
        setStreamReconnect({ state: 'done', attempt: 0, delayMs: 0, maxRetries: 0 })
        try {
          const data = await api.getCase(targetCaseId)
          setCaseData(data)
          setValidationResult(data.validation_result || validationData)
        } catch {
          setValidationResult(validationData)
        }
      },
      onProgress: (data) => {
        receivedData = true
        onProgressCb?.(data)
      },
      onError: (msg) => {
        streamRef.current = null
        replayDedupRef.current = { active: false, cursor: 0, snapshot: '' }
        setStreamReconnect((prev) => ({ ...prev, state: 'failed' }))
        console.warn('[SSE] stream error, starting poll fallback:', msg?.slice(0, 100))
        let generateFallbackRequested = false
        const pollInterval = setInterval(async () => {
          try {
            const c = await api.getCase(targetCaseId)
            if (c.status === 'completed' && (c.final_text || c.generated_text)) {
              clearInterval(pollInterval)
              clearTimeout(fallbackTimer)
              setCaseData(c)
              setStreamingText('')
              setPhase('completed')
              if (c.validation_result) setValidationResult(c.validation_result)
              setChatHistory(c.chat_history || [])
              refreshCases?.()
            } else if (c.status === 'error' || c.status === 'failed') {
              clearInterval(pollInterval)
              clearTimeout(fallbackTimer)
              setPhase('error')
              setError(c.error || msg || 'Ошибка генерации')
              refreshCases?.()
            } else if (
              !generateFallbackRequested &&
              c.status === 'processing' &&
              (c.stage === 'context_ready' || c.stage === 'awaiting_generate')
            ) {
              // Context is ready but SSE died before batch_done.
              // Trigger generate directly — poll fallback recovers the handoff.
              generateFallbackRequested = true
              console.log('[SSE] poll fallback detected context_ready, triggering generate')
              api.generate(targetCaseId).then(() => {
                connectStream(targetCaseId)
                refreshCases?.()
              }).catch(err => {
                console.warn('[SSE] poll fallback generate failed:', err?.message)
                generateFallbackRequested = false  // allow retry on next poll tick
              })
            }
          } catch { /* network error, keep polling */ }
        }, 15000)
        setTimeout(() => {
          clearInterval(pollInterval)
        }, 20 * 60 * 1000)
      },
      onConnectionState: (state) => {
        if (!state || typeof state !== 'object') return
        streamReconnectStateRef.current = state.state
        if (state.state === 'reconnecting') {
          const snapshot = streamingTextRef.current || ''
          replayDedupRef.current = {
            active: snapshot.length > 0,
            cursor: 0,
            snapshot,
          }
          if (reconnectHintTimerRef.current) {
            clearTimeout(reconnectHintTimerRef.current)
            reconnectHintTimerRef.current = null
          }
          setStreamReconnect({
            state: 'reconnecting',
            attempt: state.attempt || 1,
            delayMs: state.delayMs || 0,
            maxRetries: state.maxRetries || 0,
          })
          return
        }
        if (state.state === 'connected') {
          // Показываем "восстановлено" только если до этого был реальный обрыв
          const wasReconnecting = streamReconnectStateRef.current === 'reconnecting'
          setStreamReconnect({
            state: wasReconnecting ? 'connected' : 'idle',
            attempt: 0,
            delayMs: 0,
            maxRetries: state.maxRetries || 0,
          })
          if (reconnectHintTimerRef.current) clearTimeout(reconnectHintTimerRef.current)
          if (wasReconnecting) {
            reconnectHintTimerRef.current = setTimeout(() => {
              setStreamReconnect({ state: 'idle', attempt: 0, delayMs: 0, maxRetries: 0 })
              reconnectHintTimerRef.current = null
            }, 2000)
          }
          return
        }
        if (state.state === 'failed') {
          replayDedupRef.current = { active: false, cursor: 0, snapshot: '' }
          setStreamReconnect({
            state: 'failed',
            attempt: state.attempt || 0,
            delayMs: 0,
            maxRetries: state.maxRetries || 0,
          })
          return
        }
        if (state.state === 'closed' || state.state === 'done') {
          replayDedupRef.current = { active: false, cursor: 0, snapshot: '' }
          setStreamReconnect({ state: 'idle', attempt: 0, delayMs: 0, maxRetries: 0 })
        }
      },
    })

    streamRef.current = es
  }, [refreshUser, refreshCases, scrollToBottom])

  // ── Trigger generation ─────────────────────────────────

  const triggerGenerate = useCallback((targetCaseId) => {
    const hadText = !!(caseData?.final_text || caseData?.generated_text)
    replayDedupRef.current = { active: false, cursor: 0, snapshot: '' }
    setStreamingText('')
    setPhase('generating')
    setGenStatus('generate')
    setError('')
    scrollToBottom()
    ymGoal('generate_start', { case_id: targetCaseId })

    // POST /generate FIRST, then open stream AFTER success — prevents
    // race where stream connects while case is still context_ready and
    // backend emits batch_done (closing stream) before generation starts.
    api.generate(targetCaseId).then(() => {
      connectStream(targetCaseId)
      refreshCases?.()
    }).catch(e => {
      if (e.name !== 'AbortError') {
        setGenStatus('')
        // 402: billing limit reached
        if (e.status === 402 && _authUser?.billing_model === 'cases') {
          setError('Бесплатное дело использовано. Перейдите в раздел «Оплата» чтобы продолжить.|billing_limit')
        } else {
          setError(e.message)
        }
        if (hadText) {
          setPhase('completed')
        } else {
          setPhase('error')
        }
      }
    })
  }, [caseData, connectStream, refreshCases, scrollToBottom])

  // ── Process files: POST enqueue + подписка на /stream ──

  const connectProcess = useCallback((targetCaseId, autoGenerate = false) => {
    // Колбэк для прогресс-событий из единого /stream
    let batchDoneHandled = false
    const handleProgress = (data) => {
      switch (data.type) {
        case 'processing':
          setProcessingFile(data.filename)
          setProcessProgress(prev => ({ ...prev, total: data.total, pct: data.progress_pct ?? prev.pct, stage: data.stage_label || prev.stage }))
          break
        case 'ocr_progress':
          setProcessingFile(null)
          setGenStatus(`📷 Распознавание ${data.total_images} страниц...`)
          break
        case 'ocr_done':
          setGenStatus(data.ocr_elapsed
            ? `📷 OCR: ${data.ocr_images} стр за ${data.ocr_elapsed}с — извлечение данных...`
            : 'Извлечение данных из документов...'
          )
          break
        case 'doc_done':
          if (data.completed != null) {
            setProcessProgress(prev => ({ ...prev, index: data.completed, pct: data.progress_pct ?? prev.pct, stage: data.stage_label || prev.stage }))
          }
          setProcessedDocs(prev => [...prev, {
            doc_index: prev.length,
            doc_type: data.doc_type,
            filename: data.filename,
            summary_line: data.summary_line,
          }])
          break
        case 'doc_error':
          if (data.completed != null) {
            setProcessProgress(prev => ({ ...prev, index: data.completed, pct: data.progress_pct ?? prev.pct, stage: data.stage_label || prev.stage }))
          }
          setProcessedDocs(prev => [...prev, {
            doc_index: prev.length,
            doc_type: 'error',
            filename: data.filename,
            summary_line: data.error || 'Ошибка',
            error: true,
          }])
          break
        case 'doc_skip':
          if (data.completed != null) {
            setProcessProgress(prev => ({ ...prev, index: data.completed, pct: data.progress_pct ?? prev.pct, stage: data.stage_label || prev.stage }))
          }
          setProcessedDocs(prev => [...prev, {
            doc_index: prev.length,
            doc_type: 'skip',
            filename: data.filename,
            summary_line: data.reason || 'Пропущен',
            skip: true,
          }])
          break
        case 'compiling_summary':
          setProcessingFile(null)
          setGenStatus('Формирование документа...')
          break
        case 'batch_done':
          if (batchDoneHandled) break
          batchDoneHandled = true
          setProcessingFile(null)
          setGenStatus('')
          if (!autoGenerate) {
            setPhase('ready')
          } else {
            // Плавный переход в генерацию — batch_done terminally closed
            // the process stream, so open a fresh stream AFTER api.generate.
            replayDedupRef.current = { active: false, cursor: 0, snapshot: '' }
            setStreamingText('')
            setPhase('generating')
            setGenStatus('generate')
            setError('')
            ymGoal('generate_start', { case_id: targetCaseId })
            api.generate(targetCaseId).then(() => {
              connectStream(targetCaseId)
              refreshCases?.()
            }).catch(e => {
              setError(e.message)
              streamRef.current?.close()
            })
          }
          scrollToBottom()
          break
        default:
          break
      }
    }

    // POST /process → enqueue worker, затем подписываемся на /stream
    api.processFiles(targetCaseId).then((res) => {
      if (res?.status === 'ready') {
        setProcessingFile(null)
        setGenStatus('')
        if (autoGenerate) {
          triggerGenerate(targetCaseId)
        } else {
          setPhase('ready')
        }
        return
      }
      // Подключаем SSE стрим для получения прогресса
      connectStream(targetCaseId, { onProgressCb: handleProgress })
    }).catch(e => {
      if (e.name === 'AbortError') return
      // 402 from /process = paywall guard (user has no balance).
      // Fire event so CasePage opens PaywallModal; do not retry SSE.
      if (e.status === 402) {
        setPhase('empty')
        setProcessingFile(null)
        setGenStatus('')
        try { window.dispatchEvent(new CustomEvent('paywall-required', { detail: { caseId: targetCaseId } })) } catch {}
        try { api.trackAction && api.trackAction('paywall_shown', 'backend_402', targetCaseId) } catch {}
        return
      }
      // Fallback: process errored, try SSE (worker may have started earlier)
      connectStream(targetCaseId, { onProgressCb: handleProgress })
    })
  }, [connectStream, triggerGenerate, scrollToBottom])

  // ── Refine validation polling ─────────────────────────
  const refineValidationPollRef = useRef(null)

  const _pollRefineValidation = useCallback((targetCaseId, assistantIdx) => {
    if (refineValidationPollRef.current) clearInterval(refineValidationPollRef.current)
    let attempts = 0
    // Задержка 2с перед первым запросом — даём бэкенду начать валидацию
    const startPoll = () => {
      refineValidationPollRef.current = setInterval(async () => {
        attempts++
        if (attempts > 30) { // 60с max (30 × 2с)
          clearInterval(refineValidationPollRef.current)
          refineValidationPollRef.current = null
          return
        }
        try {
          const fresh = await api.getCase(targetCaseId)
          const hist = fresh.chat_history || []
          if (hist[assistantIdx]?.validation_result) {
            setCaseData(fresh)
            setChatHistory(hist)
            // Обновляем и основной validation_result
            if (fresh.validation_result) setValidationResult(fresh.validation_result)
            clearInterval(refineValidationPollRef.current)
            refineValidationPollRef.current = null
          }
        } catch { /* ignore */ }
      }, 2000)
    }
    setTimeout(startPoll, 2000)
  }, [])

  // ── Cleanup on unmount ─────────────────────────────────

  useEffect(() => {
    return () => {
      streamRef.current?.close()
      streamRef.current = null
      processRef.current?.close()
      processRef.current = null
      refineStreamRef.current?.abort?.()
      refineStreamRef.current = null
      if (validationPollRef.current) {
        clearInterval(validationPollRef.current)
        validationPollRef.current = null
      }
      if (refineValidationPollRef.current) {
        clearInterval(refineValidationPollRef.current)
        refineValidationPollRef.current = null
      }
      if (reconnectHintTimerRef.current) {
        clearTimeout(reconnectHintTimerRef.current)
        reconnectHintTimerRef.current = null
      }
    }
  }, [])

  // ── Visibility change: reconnect when user returns to tab ──
  useEffect(() => {
    const handleVisibility = async () => {
      if (document.visibilityState !== 'visible') return
      if (!caseId) return
      if (phase !== 'generating' && phase !== 'processing') return

      // User returned to tab while generating — check if done
      try {
        const c = await api.getCase(caseId)
        if (c.status === 'completed' && (c.final_text || c.generated_text)) {
          streamRef.current?.close()
          streamRef.current = null
          setCaseData(c)
          setStreamingText('')
          setPhase('completed')
          if (c.validation_result) setValidationResult(c.validation_result)
          setChatHistory(c.chat_history || [])
          refreshCases?.()
        } else if (c.status === 'processing' && !streamRef.current) {
          // Context is ready but user hasn't clicked Generate — trigger it now
          if ((c.stage === 'context_ready' || c.stage === 'awaiting_generate') && c.generated_text == null) {
            api.generate(caseId).then(() => {
              connectStream(caseId)
              refreshCases?.()
            }).catch(err => {
              console.warn('[visibility] auto-generate failed:', err?.message)
            })
          } else {
            // Still processing/generating but stream disconnected — reconnect
            connectStream(caseId)
          }
        }
      } catch { /* ignore */ }
    }
    document.addEventListener('visibilitychange', handleVisibility)
    return () => document.removeEventListener('visibilitychange', handleVisibility)
  }, [caseId, phase, connectStream, refreshCases])

  // ── Load case on route change ──────────────────────────

  useEffect(() => {
    if (!id) {
      // Новое дело — сбросить всё
      setPhase('empty')
      setFiles([])
      setGenStatus('Обработка документов...')
      setInstructions('')
      setCaseId(null)
      setCaseData(null)
      setError('')
      setRefineText('')
      setRefineError('')
      setStreamingText('')
      setProcessedDocs([])
      setProcessingFile(null)
      setValidationResult(null)
      setStreamReconnect({ state: 'idle', attempt: 0, delayMs: 0, maxRetries: 0 })
      setChatHistory([])
      setRefineStreamingText('')
      streamRef.current?.close()
      streamRef.current = null
      processRef.current?.close()
      processRef.current = null
      refineStreamRef.current?.abort?.()
      refineStreamRef.current = null
      if (validationPollRef.current) { clearInterval(validationPollRef.current); validationPollRef.current = null }
      if (refineValidationPollRef.current) { clearInterval(refineValidationPollRef.current); refineValidationPollRef.current = null }
      if (reconnectHintTimerRef.current) { clearTimeout(reconnectHintTimerRef.current); reconnectHintTimerRef.current = null }
      return
    }

    setPhase('loading')
    setCaseId(id)
    setRefineText('')
    setRefineError('')
    setStreamingText('')
    setProcessedDocs([])
    setProcessingFile(null)
    setValidationResult(null)
    setStreamReconnect({ state: 'idle', attempt: 0, delayMs: 0, maxRetries: 0 })
    setChatHistory([])
    setRefineStreamingText('')
    streamRef.current?.close()
    streamRef.current = null
    processRef.current?.close()
    processRef.current = null
    refineStreamRef.current?.abort?.()
    refineStreamRef.current = null
    if (validationPollRef.current) { clearInterval(validationPollRef.current); validationPollRef.current = null }
    if (refineValidationPollRef.current) { clearInterval(refineValidationPollRef.current); refineValidationPollRef.current = null }
    if (reconnectHintTimerRef.current) { clearTimeout(reconnectHintTimerRef.current); reconnectHintTimerRef.current = null }

    api.getCase(id).then(async (c) => {
      setCaseData(c)
      setChatHistory(c.chat_history || [])
      if (c.validation_result) {
        setValidationResult(c.validation_result)
      } else {
        setValidationResult(null)
      }
      if (c.status === 'error') {
        setPhase('error')
        setError(c.error_message || 'Произошла ошибка при генерации решения.')
      } else if (c.status === 'completed') {
        try {
          const ctx = await api.getContext(id)
          if (ctx.doc_count > 0) {
            setProcessedDocs(ctx.documents || [])
          }
        } catch { /* ignore */ }
        if (!c.validation_result && c.final_text) {
          _pollValidation(id)
        }
        setPhase('completed')
      } else if (c.status === 'processing') {
        setPhase('processing')
        setProcessProgress(prev => ({ ...prev, pct: 30, stage: 'Обработка документов...' }))
        // Reconnect: подписываемся на /stream с прогресс-колбэками
        let batchDoneHandled = false
        const handleProgress = (data) => {
          switch (data.type) {
            case 'processing':
              setProcessingFile(data.filename)
              setProcessProgress(prev => ({ ...prev, total: data.total, pct: data.progress_pct ?? prev.pct, stage: data.stage_label || prev.stage }))
              break
            case 'ocr_progress':
              setProcessingFile(null)
              setGenStatus(`📷 Распознавание ${data.total_images} страниц...`)
              break
            case 'ocr_done':
              setGenStatus(data.ocr_elapsed
                ? `📷 OCR: ${data.ocr_images} стр за ${data.ocr_elapsed}с — извлечение данных...`
                : 'Извлечение данных из документов...'
              )
              break
            case 'doc_done':
              if (data.completed != null) setProcessProgress(prev => ({ ...prev, index: data.completed, pct: data.progress_pct ?? prev.pct, stage: data.stage_label || prev.stage }))
              setProcessedDocs(prev => [...prev, { doc_index: prev.length, doc_type: data.doc_type, filename: data.filename, summary_line: data.summary_line }])
              break
            case 'doc_error':
              if (data.completed != null) setProcessProgress(prev => ({ ...prev, index: data.completed, pct: data.progress_pct ?? prev.pct, stage: data.stage_label || prev.stage }))
              setProcessedDocs(prev => [...prev, { doc_index: prev.length, doc_type: 'error', filename: data.filename, summary_line: data.error || 'Ошибка', error: true }])
              break
            case 'doc_skip':
              if (data.completed != null) setProcessProgress(prev => ({ ...prev, index: data.completed, pct: data.progress_pct ?? prev.pct, stage: data.stage_label || prev.stage }))
              setProcessedDocs(prev => [...prev, { doc_index: prev.length, doc_type: 'skip', filename: data.filename, summary_line: data.reason || 'Пропущен', skip: true }])
              break
            case 'compiling_summary':
              setProcessingFile(null)
              setGenStatus('Формирование документа...')
              break
            case 'batch_done':
              if (batchDoneHandled) break
              batchDoneHandled = true
              setProcessingFile(null)
              setGenStatus('')
              triggerGenerate(id)
              break
            default: break
          }
        }
        connectStream(id, { onProgressCb: handleProgress })
      } else {
        try {
          const ctx = await api.getContext(id)
          if (ctx.doc_count > 0) {
            setProcessedDocs(ctx.documents || [])
            setPhase('ready')
            return
          }
        } catch { /* ignore */ }
        setPhase('empty')
      }
    }).catch(() => {
      setPhase('error')
      setError('Дело не найдено')
    })
  }, [id])  // eslint-disable-line react-hooks/exhaustive-deps

  // ── Actions ────────────────────────────────────────────

  const handleGenerate = useCallback(() => {
    if (phase === 'generating') {
      streamRef.current?.close()
      streamRef.current = null
      setPhase('completed')
      setGenStatus('')
      refreshCases?.()
      return
    }
    if (!caseId) return setError('Дело не создано')
    triggerGenerate(caseId)
  }, [phase, caseId, triggerGenerate, refreshCases])

  const handleRemoveDoc = useCallback(async (docIndex) => {
    if (!caseId) return
    try {
      await api.removeDocument(caseId, docIndex)
      setProcessedDocs(prev => prev.filter(d => d.doc_index !== docIndex))
      const ctx = await api.getContext(caseId)
      setProcessedDocs(ctx.documents || [])
    } catch (e) {
      setError(e.message)
    }
  }, [caseId])

  const handleUploadMore = useCallback(() => {
    setFiles([])
    setError('')
    setPhase('empty')
  }, [])

  const handleRetry = useCallback(() => {
    if (!caseId) return
    triggerGenerate(caseId)
  }, [caseId, triggerGenerate])

  const handleRetryProcess = useCallback(async () => {
    if (!caseId) return
    setError('')
    setPhase('processing')
    setProcessingFile(null)
    scrollToBottom()
    connectProcess(caseId, true)
  }, [caseId, connectProcess, scrollToBottom])

  const handleCopy = useCallback(() => {
    const textToCopy = caseData?.final_text || caseData?.generated_text || ''
    if (!textToCopy) return
    // iOS Safari requires synchronous clipboard access from user gesture
    // Use textarea fallback first (works everywhere), then try modern API
    const ta = document.createElement('textarea')
    ta.value = textToCopy
    ta.style.cssText = 'position:fixed;opacity:0;left:-9999px'
    document.body.appendChild(ta)
    ta.focus()
    ta.select()
    try { document.execCommand('copy') } catch {}
    document.body.removeChild(ta)
    // Also try modern API (non-blocking, may fail on iOS but textarea already copied)
    try { navigator.clipboard.writeText(textToCopy).catch(() => {}) } catch {}
    setCopied(true)
    api.trackAction("copy_text", "", caseId)
    setTimeout(() => setCopied(false), 2000)
  }, [caseData])

  const handleExportDocx = useCallback(async () => {
    if (!caseId) return
    // Direct link works on all platforms including iOS Safari
    window.open(`/api/cases/${caseId}/export/docx`, '_blank')
    api.trackAction("download_docx", "", caseId)
  }, [caseId])

  const handleUploadAndProcess = useCallback(async () => {
    if (files.length === 0) return setError('Загрузите хотя бы один файл')
    setError('')
    setPhase('processing')
    setGenStatus('')
    setProcessProgress({ index: 0, total: 0, pct: 0, stage: `Загрузка файлов... 0 из ${files.length}` })
    setProcessedDocs([])
    scrollToBottom()

    const controller = new AbortController()
    abortRef.current = controller
    let wakeLock = null

    try {
      wakeLock = await acquireWakeLock()
      let targetCaseId = caseId

      if (!targetCaseId) {
        const autoTitle = instructions.trim()
          ? (() => {
              const words = instructions.trim().split(/\s+/).slice(0, 6).join(' ')
              return words.length > 60 ? words.slice(0, 57) + '...' : words
            })()
          : null

        const c = await api.createCase(autoTitle, instructions.trim() || null, activeJudgeId)
        targetCaseId = c.id
        setCaseId(c.id)
        setCaseData(c)
        window.history.replaceState(null, '', `/cases/${c.id}`)
        refreshCases?.()
        // Track generate_start NOW — caseId is available (was null in CasePage before createCase)
        try { api.trackAction('generate_start', `canGenerate=true`, targetCaseId) } catch {}
      }

      ymGoal('upload_files', { count: files.length })
      api.trackAction('upload_files', 'count=' + files.length, targetCaseId)
      const result = await api.uploadFilesChunked(targetCaseId, files, (percent, info) => {
        const done = info?.done || 0
        setProcessProgress(prev => ({
          ...prev,
          pct: Math.round(percent * 0.3),
          stage: `Загрузка файлов... ${done} из ${info?.total || files.length}`
        }))
      }, controller.signal)

      if (result && result.uploaded === 0 && !result.errors) {
        const reasons = Array.isArray(result.skipped)
          ? result.skipped.map(s => `${s.file}: ${s.reason}`).join('\n')
          : 'Неизвестная причина'
        throw new Error(`Ни один файл не загружен:\n${reasons}`)
      }
      if (result?.errors?.length) {
        console.warn('Upload errors:', result.errors)
      }

      // Judge bonus: refresh user to get updated free_cases_left
      if (result?.judge_bonus) {
        refreshUser?.()
        setGenStatus(result.message || 'Бонус: 3 бесплатных дела!')
      }

      setFiles([])
      setProcessProgress(prev => ({ ...prev, pct: 30, stage: 'Подготовка к обработке...' }))
      scrollToBottom()
      connectProcess(targetCaseId, true)

    } catch (e) {
      if (e.name === 'AbortError') {
        setPhase(processedDocs.length > 0 ? 'ready' : 'empty')
        setError('')
      } else {
        setPhase('error')
        setError(e.message)
      }
      setGenStatus('')
    } finally {
      abortRef.current = null
      wakeLock?.release().catch(() => {})
    }
  }, [files, caseId, instructions, processedDocs.length, connectProcess, refreshCases, scrollToBottom])

  // Загрузить файлы сразу при добавлении — без создания дела
  const uploadOnAdd = useCallback(async (newFiles) => {
    if (!newFiles.length) return
    setIsUploading(true)
    setUploadPercent(0)
    let targetCaseId = caseId
    try {
      if (!targetCaseId) {
        const c = await api.createCase(null, null, activeJudgeId)
        targetCaseId = c.id
        setCaseId(c.id)
        setCaseData(c)
        window.history.replaceState(null, '', `/cases/${c.id}`)
        refreshCases?.()
      }
      await api.uploadFilesChunked(targetCaseId, newFiles, (pct) => {
        setUploadPercent(Math.round(pct))
      })
      setUploadPercent(100)
    } catch (e) {
      setError(e.message)
    } finally {
      setIsUploading(false)
    }
  }, [caseId, activeJudgeId, refreshCases])

  // Upload files + create case WITHOUT starting processing (for paywall flow)
  const ensureFilesUploaded = useCallback(async () => {
    if (files.length === 0) return null
    let targetCaseId = caseId

    if (!targetCaseId) {
      const autoTitle = instructions.trim()
        ? (() => {
            const words = instructions.trim().split(/\s+/).slice(0, 6).join(' ')
            return words.length > 60 ? words.slice(0, 57) + '...' : words
          })()
        : null
      const c = await api.createCase(autoTitle, instructions.trim() || null, activeJudgeId)
      targetCaseId = c.id
      setCaseId(c.id)
      setCaseData(c)
      window.history.replaceState(null, '', `/cases/${c.id}`)
      refreshCases?.()
    }

    // Upload files to server
    if (files.length > 0) {
      await api.uploadFilesChunked(targetCaseId, files, () => {})
    }

    return targetCaseId
  }, [files, caseId, instructions, activeJudgeId, refreshCases])

  const handleAddFilesFromCompleted = useCallback(async (selectedFiles) => {
    if (!selectedFiles?.length || !caseId) return
    setError('')
    setPhase('processing')
    setGenStatus('')
    setProcessProgress({ index: 0, total: 0, pct: 0, stage: `Загрузка файлов... 0 из ${selectedFiles.length}` })
    scrollToBottom()

    try {
      const fileList = Array.from(selectedFiles)
      await api.uploadFilesChunked(caseId, fileList, (percent, info) => {
        const done = info?.done || 0
        setProcessProgress(prev => ({
          ...prev,
          pct: Math.round(percent * 0.3),
          stage: `Загрузка файлов... ${done} из ${info?.total || fileList.length}`
        }))
      })

      setProcessProgress(prev => ({ ...prev, pct: 30, stage: 'Подготовка к обработке...' }))
      scrollToBottom()
      connectProcess(caseId, true)
    } catch (e) {
      setPhase('error')
      setError(e.message)
    }
  }, [caseId, connectProcess, scrollToBottom])

  const handleRefine = useCallback(async () => {
    if (!refineText.trim() || refining) return
    // Берём текст из последнего assistant-сообщения в chat_history (для повторных рефайнов),
    // или final_text (для первого рефайна). final_text = оригинал после AI-ревизора.
    const lastAssistant = [...(chatHistory || [])].reverse().find(m => m.role === 'assistant')
    const currentText = lastAssistant?.content || caseData?.final_text || caseData?.generated_text || ''
    if (!currentText) return

    // 1. Добавляем user-сообщение в локальную историю
    const userMsg = {
      role: 'user',
      content: refineText.trim(),
      files: [],
      ts: new Date().toISOString(),
    }
    setChatHistory(prev => [...prev, userMsg])
    setRefining(true)
    setRefineError('')
    setRefineStreamingText('')
    const requestText = refineText.trim()
    setRefineText('')
    scrollToBottom()
    ymGoal('refine_start', { case_id: caseId })
    api.trackAction('refine_start', requestText.slice(0, 100), caseId)

    // 2. SSE streaming
    const stream = api.refineStream(caseId, {
      full_text: currentText,
      selected_text: currentText,
      user_request: requestText,
      selection_offset: 0,
    }, {
      onChunk: (text) => {
        setRefineStreamingText(prev => prev + text)
        // auto-scroll если пользователь внизу
        if (scrollRef.current) {
          const el = scrollRef.current
          if (el.scrollHeight - el.scrollTop - el.clientHeight < 200) {
            setTimeout(() => el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' }), 50)
          }
        }
      },
      onDone: async (data) => {
        // 3. Перезагружаем данные дела
        try {
          const freshCase = await api.getCase(caseId)
          setCaseData(freshCase)
          const freshHistory = freshCase.chat_history || []
          setChatHistory(freshHistory)
          setRefineStreamingText('')
          setRefining(false)
          refreshCases?.()
          scrollToBottom()

          // 4. Запускаем поллинг валидации для последнего assistant-ответа
          const lastAssistantIdx = freshHistory.length - 1
          if (lastAssistantIdx >= 0 && freshHistory[lastAssistantIdx]?.role === 'assistant' && !freshHistory[lastAssistantIdx]?.validation_result) {
            _pollRefineValidation(caseId, lastAssistantIdx)
          }
        } catch {
          setRefining(false)
          setRefineStreamingText('')
        }
      },
      onError: (msg) => {
        setRefineError(msg)
        setRefining(false)
        setRefineStreamingText('')
      },
    })

    refineStreamRef.current = stream
  }, [refineText, refining, caseData, caseId, chatHistory, refreshCases, scrollToBottom, _pollRefineValidation])

  return {
    // State
    phase, setPhase,
    files, setFiles,
    instructions, setInstructions,
    genStatus,
    uploadPercent,
    isUploading,
    uploadedFilesCount: caseData?.files_count,
    error, setError,
    processedDocs,
    processingFile,
    processProgress,
    streamingText,
    caseId,
    caseData,
    copied,
    validationResult,
    streamReconnect,
    refineText, setRefineText,
    refining,
    refineError,
    chatHistory,
    refineStreamingText,

    // Refs
    scrollRef,

    // Actions
    handleGenerate,
    handleRemoveDoc,
    handleUploadMore,
    handleRetry,
    handleRetryProcess,
    handleCopy,
    handleExportDocx,
    handleUploadAndProcess,
    handleAddFilesFromCompleted,
    handleRefine,
    ensureFilesUploaded,
    scrollToBottom,
  }
}
