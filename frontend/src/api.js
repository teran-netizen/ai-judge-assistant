import { uploadFilesChunked as _uploadChunked } from './lib/uploadChunked.js'

const BASE = import.meta.env.VITE_API_URL || ''
const PENDING_PAYMENT_KEY = 'pending_payment_ctx_v1'
const PENDING_PAYMENT_TTL_MS = 24 * 60 * 60 * 1000

async function request(method, path, body = null, opts = {}) {
  const headers = { ...opts.headers }

  const config = { method, headers, credentials: 'include' }

  if (body instanceof FormData) {
    config.body = body
  } else if (body) {
    headers['Content-Type'] = 'application/json'
    config.body = JSON.stringify(body)
  }

  // Timeout: настраиваемый через opts.timeout (мс), по умолчанию 60 сек
  // Не применяется если передан signal
  const timeoutMs = opts.timeout || 60000
  let timeoutId
  let isOwnTimeout = false
  if (!opts.signal) {
    const controller = new AbortController()
    config.signal = controller.signal
    timeoutId = setTimeout(() => { isOwnTimeout = true; controller.abort() }, timeoutMs)
  } else {
    config.signal = opts.signal
  }

  let res
  try {
    res = await fetch(`${BASE}${path}`, config)
  } catch (e) {
    if (e.name === 'AbortError') {
      if (isOwnTimeout) throw new Error(`Превышено время ожидания (${Math.round(timeoutMs / 1000)} сек)`)
      throw e  // Внешняя отмена — пробрасываем как есть
    }
    throw e
  } finally {
    if (timeoutId) clearTimeout(timeoutId)
  }

  if (res.status === 401) {
    // Auto-refresh: if 401 and we have refresh_token in localStorage, restore session
    if (!path.includes('/auth/')) {
      const rt = localStorage.getItem('refresh_token')
      if (rt) {
        try {
          const rr = await fetch(`${BASE}/api/auth/refresh`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            credentials: 'include', body: JSON.stringify({ refresh_token: rt }),
          })
          if (rr.ok) return request(method, path, body, opts)
          else localStorage.removeItem('refresh_token')
        } catch { localStorage.removeItem('refresh_token') }
      }
    }
    // Don't redirect if already on login or during OAuth callback
    const path = window.location.pathname
    if (path !== '/login' && !path.startsWith('/auth/')) {
      window.location.href = '/login'
    }
    throw new Error('Сессия истекла')
  }

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Ошибка сервера' }))
    const error = new Error(err.detail || `Ошибка ${res.status}`)
    error.status = res.status
    throw error
  }

  if (res.headers.get('content-type')?.includes('json')) {
    return res.json()
  }
  return res
}

function savePendingPayment(operationId, transactionId = '') {
  if (!operationId) return
  const payload = {
    operation_id: operationId,
    transaction_id: transactionId || '',
    ts: Date.now(),
  }
  localStorage.setItem(PENDING_PAYMENT_KEY, JSON.stringify(payload))
}

function getPendingPayment() {
  try {
    const raw = localStorage.getItem(PENDING_PAYMENT_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    if (!parsed?.operation_id || !parsed?.ts) {
      localStorage.removeItem(PENDING_PAYMENT_KEY)
      return null
    }
    if (Date.now() - Number(parsed.ts) > PENDING_PAYMENT_TTL_MS) {
      localStorage.removeItem(PENDING_PAYMENT_KEY)
      return null
    }
    return parsed
  } catch {
    localStorage.removeItem(PENDING_PAYMENT_KEY)
    return null
  }
}

function clearPendingPayment() {
  localStorage.removeItem(PENDING_PAYMENT_KEY)
}


// Resize image before upload (max 2000px, JPEG 0.85 quality)
async function resizeImage(file, maxSize = 2000) {
  if (!file.type.startsWith('image/') || file.type === 'image/gif') return file
  return new Promise((resolve) => {
    const img = new Image()
    img.onload = () => {
      URL.revokeObjectURL(img.src)
      if (img.width <= maxSize && img.height <= maxSize) { resolve(file); return }
      const scale = Math.min(maxSize / img.width, maxSize / img.height)
      const canvas = document.createElement('canvas')
      canvas.width = Math.round(img.width * scale)
      canvas.height = Math.round(img.height * scale)
      const ctx = canvas.getContext('2d')
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height)
      canvas.toBlob((blob) => {
        if (!blob || blob.size >= file.size) { resolve(file); return }
        resolve(new File([blob], file.name.replace(/\.[^.]+$/, '.jpg'), { type: 'image/jpeg' }))
      }, 'image/jpeg', 0.85)
    }
    img.onerror = () => resolve(file)
    img.src = URL.createObjectURL(file)
  })
}

async function resizeFiles(files) {
  return Promise.all(Array.from(files).map(f => resizeImage(f)))
}

const api = {
  // Auth
  sendOTP: (email) => request('POST', '/api/auth/otp/send', { email }),
  verifyOTP: (email, code, state) => request('POST', '/api/auth/otp/verify', { email, code, state }),
  updateProfile: (data) => request('PUT', '/api/auth/profile', data),
  getMe: () => request('GET', '/api/auth/me'),
  logout: () => {
    const rt = (typeof window !== 'undefined' && window.localStorage) ? localStorage.getItem('refresh_token') : null
    try { if (typeof window !== 'undefined' && window.localStorage) localStorage.removeItem('refresh_token') } catch {}
    return request('POST', '/api/auth/logout', rt ? { refresh_token: rt } : null)
  },
  setNickname: (nickname) => request('PUT', '/api/auth/nickname', { nickname }),

  // Cases
  getCases: (offset = 0, limit = 50, judgeId = null) => request('GET', `/api/cases/?offset=${offset}&limit=${limit}${judgeId ? `&judge_id=${judgeId}` : ''}`),
  createCase: (title, userInstructions, judgeId = null) => request('POST', '/api/cases/', { title, user_instructions: userInstructions || null, ...(judgeId ? { judge_id: judgeId } : {}) }),
  getCase: (id) => request('GET', `/api/cases/${id}`),
  deleteCase: (id) => request('DELETE', `/api/cases/${id}`),
  renameCase: (id, title) => request('PATCH', `/api/cases/${id}/title`, { title }),
  uploadFiles: (caseId, files) => {
    const form = new FormData()
    files.forEach(f => form.append('files', f))
    return request('POST', `/api/cases/${caseId}/files`, form)
  },

  // Upload with progress callback: onProgress(percent) where percent is 0-100
  // signal (AbortSignal) — для отмены загрузки из UI
  // Chunked upload with resume support
  uploadFilesChunked: async (caseId, files, onProgress, signal) => {
    return _uploadChunked(caseId, files, onProgress, signal)
  },
  uploadFilesWithProgress: async (caseId, files, onProgress, signal) => {
    const BATCH = 2
    const total = files.length
    let uploaded = 0
    let skipped = []
    let lastResult = null

    files = await resizeFiles(files)
    for (let i = 0; i < total; i += BATCH) {
      if (signal?.aborted) throw new DOMException('Загрузка отменена', 'AbortError')

      const batch = Array.from(files).slice(i, i + BATCH)
      const batchStart = i
      let batchResult
      for (let attempt = 0; attempt < 3; attempt++) {
        try {
          batchResult = await new Promise((resolve, reject) => {
        const form = new FormData()
        batch.forEach(f => form.append('files', f))

        const xhr = new XMLHttpRequest()
        xhr.open('POST', `${BASE}/api/cases/${caseId}/files`)
        xhr.withCredentials = true

        if (signal) {
          signal.addEventListener('abort', () => {
            xhr.abort()
            reject(new DOMException('Загрузка отменена', 'AbortError'))
          }, { once: true })
        }

        xhr.upload.addEventListener('progress', (e) => {
          if (e.lengthComputable && onProgress) {
            const batchPct = e.loaded / e.total
            const overallPct = Math.round(((batchStart + batch.length * batchPct) / total) * 100)
            onProgress(Math.min(overallPct, 99), { done: batchStart, total })
          }
        })

        xhr.addEventListener('load', () => {
          if (xhr.status === 401) {
            window.location.href = '/login'
            return reject(new Error('Сессия истекла'))
          }
          let data
          try { data = JSON.parse(xhr.responseText) } catch { data = null }
          if (xhr.status >= 400) {
            return reject(new Error(data?.detail || `Ошибка загрузки (${xhr.status})`))
          }
          resolve(data)
        })

        xhr.addEventListener('error', () => reject(new Error('Ошибка сети при загрузке файлов')))
        xhr.addEventListener('timeout', () => reject(new Error('Превышено время загрузки файлов')))
        xhr.timeout = 3 * 60 * 1000
        xhr.send(form)
      })
          break
        } catch (e) {
          if (e.name === 'AbortError' || attempt === 2) throw e
          await new Promise(r => setTimeout(r, 2000))
        }
      }

      uploaded += batchResult?.uploaded || batch.length
      if (batchResult?.skipped) skipped.push(...batchResult.skipped)
      lastResult = batchResult
    }

    if (onProgress) onProgress(100, { done: total, total })
    return { uploaded, skipped, ...(lastResult || {}) }
  },
  generate: (caseId, signal) => {
    // Теперь возвращает мгновенно — pipeline работает в фоне
    return request('POST', `/api/cases/${caseId}/generate`, null, { signal: signal || new AbortController().signal })
  },

  // POST /process — enqueue OCR+extract to worker, returns immediately
  streamCase: (caseId, {
    onChunk,
    onDone,
    onError,
    onFull,
    onValidation,
    onProgress,
    onConnectionState,
    maxRetries = 12,
    baseRetryMs = 1000,
    maxRetryMs = 15000,
  }) => {
    let isDone = false
    let retryCount = 0
    let reconnectTimer = null
    let closedManually = false
    let lastEventId = ''
    const parseEventSeq = (id) => {
      if (!id || typeof id !== 'string') return 0
      const part = id.includes(':') ? id.split(':').pop() : id
      const n = Number.parseInt(part, 10)
      return Number.isFinite(n) ? n : 0
    }
    const progressEventTypes = new Set([
      'processing',
      'ocr_progress',
      'ocr_done',
      'doc_done',
      'doc_error',
      'doc_skip',
      'compiling_summary',
    ])

    const handle = {
      _es: null,
      close() {
        closedManually = true
        isDone = true
        if (reconnectTimer) {
          clearTimeout(reconnectTimer)
          reconnectTimer = null
        }
        this._es?.close()
        this._es = null
        onConnectionState?.({ state: 'closed', attempt: retryCount, maxRetries })
      },
    }

    const scheduleReconnect = () => {
      if (closedManually || isDone) return
      retryCount += 1
      if (retryCount > maxRetries) {
        onConnectionState?.({ state: 'failed', attempt: retryCount - 1, maxRetries })
        onError?.('Потеряно соединение с сервером. Проверьте интернет и повторите попытку.')
        return
      }
      const delayMs = Math.min(maxRetryMs, baseRetryMs * (2 ** Math.max(0, retryCount - 1)))
      onConnectionState?.({ state: 'reconnecting', attempt: retryCount, delayMs, maxRetries })
      reconnectTimer = setTimeout(() => {
        reconnectTimer = null
        connect()
      }, delayMs)
    }

    const connect = () => {
      if (closedManually || isDone) return
      onConnectionState?.({ state: 'connecting', attempt: retryCount, maxRetries })
      const streamUrl = lastEventId
        ? `${BASE}/api/cases/${caseId}/stream?last_event_id=${encodeURIComponent(lastEventId)}`
        : `${BASE}/api/cases/${caseId}/stream`
      const es = new EventSource(streamUrl, { withCredentials: true })
      handle._es = es

      es.onopen = () => {
        retryCount = 0
        onConnectionState?.({ state: 'connected', attempt: 0, maxRetries })
      }

      es.onmessage = (event) => {
        try {
          if (event?.lastEventId) {
            // Guard against rare out-of-order reconnect delivery.
            if (parseEventSeq(event.lastEventId) <= parseEventSeq(lastEventId)) return
            lastEventId = event.lastEventId
          }
          const data = JSON.parse(event.data)
          if (!data || typeof data !== 'object' || typeof data.type !== 'string') return
          if (data.type === 'chunk') {
            onChunk?.(data.text)
          } else if (data.type === 'full') {
            onFull?.(data.text)
          } else if (data.type === 'done' || data.type === 'partial_done') {
            isDone = true
            onConnectionState?.({ state: 'done', attempt: 0, maxRetries })
            onDone?.()
          } else if (data.type === 'validation_complete') {
            isDone = true
            es.close()
            handle._es = null
            onConnectionState?.({ state: 'done', attempt: 0, maxRetries })
            onValidation?.(data)
          } else if (data.type === 'error') {
            isDone = true
            es.close()
            handle._es = null
            onConnectionState?.({ state: 'failed', attempt: retryCount, maxRetries })
            onError?.(data.message || 'Ошибка генерации')
          } else if (data.type === 'batch_done') {
            isDone = true
            es.close()
            handle._es = null
            onConnectionState?.({ state: 'done', attempt: 0, maxRetries })
            onProgress?.(data)
          } else if (progressEventTypes.has(data.type)) {
            onProgress?.(data)
          } else {
            console.warn('[SSE] unknown event type ignored:', data.type)
          }
        } catch {
          // Ignore parse errors for keepalive comments
        }
      }

      es.onerror = () => {
        if (closedManually || isDone) {
          es.close()
          return
        }
        es.close()
        if (handle._es === es) handle._es = null
        scheduleReconnect()
      }
    }

    connect()
    return handle
  },
  processFiles: (caseId) => {
    return request('POST', `/api/cases/${caseId}/process`)
  },

  getContext: (caseId) => request('GET', `/api/cases/${caseId}/context`),

  removeDocument: (caseId, docIndex) => request('DELETE', `/api/cases/${caseId}/context/documents/${docIndex}`),

  saveFinal: (caseId, text) => request('PUT', `/api/cases/${caseId}/final`, { final_text: text }),
  // SSE-стриминг доработки: POST → StreamingResponse (чанки текста)
  refineStream: (caseId, body, { onChunk, onDone, onError }) => {
    const controller = new AbortController()
    const timeoutId = setTimeout(() => controller.abort(), 900000) // 15 мин

    ;(async () => {
      try {
        const response = await fetch(`${BASE}/api/cases/${caseId}/refine`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify(body),
          signal: controller.signal,
        })

        if (response.status === 401) {
          window.location.href = '/login'
          onError?.('Сессия истекла')
          return
        }
        if (!response.ok) {
          const err = await response.json().catch(() => ({}))
          onError?.(err.detail || `Ошибка ${response.status}`)
          return
        }

        const reader = response.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''

        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })

          const parts = buffer.split('\n\n')
          buffer = parts.pop() // неполный кусок остаётся
          for (const part of parts) {
            if (!part.startsWith('data: ')) continue
            try {
              const data = JSON.parse(part.slice(6))
              if (data.type === 'chunk') onChunk?.(data.text)
              else if (data.type === 'done') onDone?.(data)
              else if (data.type === 'error') onError?.(data.message)
            } catch { /* ignore malformed SSE */ }
          }
        }
      } catch (e) {
        if (e.name === 'AbortError') onError?.('Превышено время ожидания (5 мин)')
        else onError?.(e.message)
      } finally {
        clearTimeout(timeoutId)
      }
    })()

    return { abort: () => { clearTimeout(timeoutId); controller.abort() } }
  },

  // Delete individual file
  deleteFile: (caseId, fileId) => request('DELETE', `/api/cases/${caseId}/files/${fileId}`),

  // OCR-check: SSE endpoint for instant per-file OCR feedback
  ocrCheck: (caseId, { onFile, onDone, onError }) => {
    const es = new EventSource(`${BASE}/api/cases/${caseId}/ocr-check`, { withCredentials: true })

    es.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        if (data.type === 'file') onFile?.(data)
        else if (data.type === 'done' || data.type === 'partial_done') { es.close(); onDone?.(data) }
        else if (data.type === 'error') { es.close(); onError?.(data.message || 'Ошибка OCR') }
      } catch { /* ignore */ }
    }

    es.onerror = () => { es.close(); onError?.('Потеряно соединение при OCR') }
    return es
  },

  // Billing
  getPackages: () => request('GET', '/api/billing/packages'),
  getBalance: () => request('GET', '/api/billing/balance'),
  checkPaymentStatus: (orderId) => request('GET', `/api/billing/payment-status/${orderId}`),

  // Norms (hover popup)
  getNorm: (normId) => request('GET', `/api/norms/${normId}`),

  // Validation (AI-ревизор)
  getValidation: (caseId) => request('GET', `/api/cases/${caseId}/validation`),

  // Invites (gift codes)
  activateInvite: (code) => request('POST', '/api/invites/activate', { code }),
  trackReferralCopy: () => request("POST", "/api/referral/track-copy"),
  getReferralStats: () => request("GET", "/api/referral/my-stats"),
  getAdminReferralStats: () => request("GET", "/api/referral/admin/stats"),
  getAdminReferredUsers: (referrerId) => request("GET", `/api/referral/admin/referred/${referrerId}`),
  getAdminInviteStats: () => request("GET", "/api/invites/admin/stats"),

  // Purchase attempt (cases billing model)
  purchaseAttempt: (packageType, returnUrl) => request('POST', '/api/billing/purchase-attempt', { package_type: packageType, return_url: returnUrl || '' }),
  savePendingPayment,
  getPendingPayment,
  clearPendingPayment,

  // Export
  exportDocx: async (caseId) => {
    const res = await fetch(`${BASE}/api/cases/${caseId}/export/docx`, {
      credentials: 'include',
    })
    if (!res.ok) throw new Error('Ошибка экспорта')
    const blob = await res.blob()
    // Извлекаем имя файла из Content-Disposition (filename*=UTF-8'' или filename=)
    const cd = res.headers.get('Content-Disposition') || ''
    let filename = 'Решение.docx'
    const utf8Match = cd.match(/filename\*=UTF-8''(.+?)(?:;|$)/)
    if (utf8Match) {
      filename = decodeURIComponent(utf8Match[1])
    } else {
      const basicMatch = cd.match(/filename="?(.+?)"?(?:;|$)/)
      if (basicMatch) filename = basicMatch[1]
    }
    return { blob, filename }
  },

  // Payment confirmation
  rateCase: (caseId, rating, reviewText = '') => request('POST', `/api/cases/${caseId}/rate`, { rating, review_text: reviewText }),
  confirmPayment: (operationId, transactionId = '') => request('POST', '/api/billing/confirm-payment', { operation_id: operationId, transaction_id: transactionId }),

  // Email
  collectEmail: (email) => request('POST', '/api/email/collect', { email }),
  sendDocxEmail: (caseId, email) => request('POST', `/api/email/send-docx/${caseId}`, { email }),

  // Admin
  getAdminDashboard: () => request('GET', '/api/admin/dashboard'),
  getAdminUsers: () => request('GET', '/api/admin/users'),
  getAdminClients: () => request('GET', '/api/admin/clients'),
  getAdminPurchaseAttempts: () => request('GET', '/api/admin/purchase-attempts'),
  getAdminAnalytics: (days = 14) => request('GET', `/api/admin/analytics?days=${days}`),
  getAdminFeedbacks: (status = 'new') => request('GET', `/api/admin/feedbacks?status=${status}`),
  processAdminFeedback: (id, status, responseText, reward) =>
    request('PUT', `/api/admin/feedbacks/${id}`, { status, response_text: responseText, reward: reward || 0 }),

  // Activity tracking — fire and forget
  trackAction: (action, details = '', caseId = '') => {
    try {
      navigator.sendBeacon?.(
        `${BASE}/api/activity`,
        new Blob([JSON.stringify({ action, details, case_id: caseId || undefined })], { type: 'application/json' })
      ) || request('POST', '/api/activity', { action, details, case_id: caseId || undefined }).catch(() => {})
    } catch {}
  },
}

export async function getMyJudges() { return request("GET", "/api/assistants/judges") }
export default api

// === Upload Sessions API ===
api.createUploadSession = (caseId, expectedFilesCount, totalBytes) =>
  request('POST', `/api/cases/${caseId}/upload-sessions`, { expected_files_count: expectedFilesCount, total_bytes: totalBytes })

api.getUploadState = (caseId, sessionId) =>
  request('GET', `/api/cases/${caseId}/upload-state?session_id=${sessionId}`)

api.finalizeUploadSession = (caseId, sessionId) =>
  request('POST', `/api/cases/${caseId}/upload-sessions/${sessionId}/finalize`)

api.uploadChunk = (caseId, files, metadata) => {
  const form = new FormData()
  files.forEach(f => form.append('files', f))
  if (metadata.upload_session_id) form.append('upload_session_id', metadata.upload_session_id)
  if (metadata.client_file_id) form.append('client_file_id', metadata.client_file_id)
  if (metadata.upload_batch_id) form.append('upload_batch_id', metadata.upload_batch_id)
  return request('POST', `/api/cases/${caseId}/files`, form, { timeout: 120000 })
}

// Named exports for assistant/judge features
export async function getMyAssistants() { return request("GET", "/api/assistants/") }
export async function addAssistant(code) { return request("POST", "/api/assistants/", { code }) }
export async function removeAssistant(assistantId) { return request("DELETE", `/api/assistants/${assistantId}`) }
export async function createAssistantInvite() { return request("POST", "/api/assistants/invite") }
export async function acceptAssistantInvite(code) { return request("POST", "/api/assistants/accept", { code }) }
export async function detachFromJudge(judgeId) { return request("DELETE", `/api/assistants/judges/${judgeId}`) }
