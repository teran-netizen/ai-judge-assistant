const BASE = import.meta.env.VITE_API_URL || ''
const CHUNK_SIZE = 5
const CONCURRENCY = 3
const TARGET_CHUNK_BYTES = 20 * 1024 * 1024

function clientFileId(file) {
  const raw = file.name + '|' + file.size + '|' + (file.lastModified || 0)
  let hash = 0
  for (let i = 0; i < raw.length; i++) {
    hash = ((hash << 5) - hash) + raw.charCodeAt(i)
    hash |= 0
  }
  return 'cf_' + Math.abs(hash).toString(36) + '_' + file.size.toString(36)
}

function makeChunks(files) {
  const chunks = []
  let cur = [], curBytes = 0
  for (const f of files) {
    cur.push(f)
    curBytes += f.size
    if (cur.length >= CHUNK_SIZE || curBytes >= TARGET_CHUNK_BYTES) {
      chunks.push([...cur])
      cur = []
      curBytes = 0
    }
  }
  if (cur.length) chunks.push(cur)
  return chunks
}

async function uploadChunk(caseId, files, sessionId, batchId, signal) {
  const form = new FormData()
  files.forEach(f => form.append('files', f))
  if (sessionId) form.append('upload_session_id', sessionId)
  if (batchId) form.append('upload_batch_id', batchId)
  const cfids = files.map(f => clientFileId(f))
  form.append('client_file_id', cfids.join(','))

  const resp = await fetch(BASE + '/api/cases/' + caseId + '/files', {
    method: 'POST', body: form, credentials: 'include', signal
  })
  if (resp.status === 401) { window.location.href = '/login'; throw new Error('Сессия истекла') }
  if (!resp.ok) {
    const d = await resp.json().catch(() => ({}))
    throw new Error(d.detail || 'Ошибка загрузки (' + resp.status + ')')
  }
  return resp.json()
}

async function getUploadState(caseId) {
  try {
    const r = await fetch(BASE + '/api/cases/' + caseId + '/upload-state', { credentials: 'include' })
    if (!r.ok) return { accepted_client_file_ids: [] }
    return r.json()
  } catch { return { accepted_client_file_ids: [] } }
}

async function createUploadSession(caseId, count, bytes) {
  try {
    const r = await fetch(BASE + '/api/cases/' + caseId + '/upload-sessions', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ expected_files_count: count, total_bytes: bytes })
    })
    if (!r.ok) return null
    const d = await r.json()
    return d.id || d.session_id
  } catch { return null }
}

async function finalizeSession(caseId, sessionId) {
  try {
    await fetch(BASE + '/api/cases/' + caseId + '/upload-sessions/' + sessionId + '/finalize', {
      method: 'POST', credentials: 'include'
    })
  } catch {}
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

export async function uploadFilesChunked(caseId, files, onProgress, signal) {
  if (!files.length) return { uploaded: 0, skipped: 0 }
  files = await Promise.all(Array.from(files).map(f => resizeImage(f)))

  const totalBytes = files.reduce((s, f) => s + f.size, 0)
  const sessionId = await createUploadSession(caseId, files.length, totalBytes)

  const state = await getUploadState(caseId)
  const already = new Set(state.accepted_client_file_ids || [])
  const remaining = files.filter(f => !already.has(clientFileId(f)))
  const skipped = files.length - remaining.length

  let uploaded = skipped
  onProgress && onProgress(Math.round(uploaded / files.length * 100), { done: uploaded, total: files.length })

  if (!remaining.length) {
    if (sessionId) await finalizeSession(caseId, sessionId)
    onProgress && onProgress(100, { done: files.length, total: files.length })
    return { uploaded: skipped, skipped: 0, session_id: sessionId }
  }

  const chunks = makeChunks(remaining)
  const queue = [...chunks]
  const errors = []

  async function worker() {
    while (queue.length > 0) {
      if (signal && signal.aborted) throw new DOMException('Загрузка отменена', 'AbortError')
      const chunk = queue.shift()
      const bid = Math.random().toString(36).slice(2, 10)
      let success = false
      for (let attempt = 0; attempt < 3; attempt++) {
        try {
          await uploadChunk(caseId, chunk, sessionId, bid, signal)
          success = true
          break
        } catch (e) {
          if (e.name === 'AbortError') throw e
          if (attempt < 2) {
            await new Promise(r => setTimeout(r, 2000 * (attempt + 1)))
          } else {
            errors.push({ files: chunk.map(f => f.name), error: e.message })
          }
        }
      }
      uploaded += chunk.length
      onProgress && onProgress(Math.round(uploaded / files.length * 100), { done: uploaded, total: files.length })
    }
  }

  await Promise.all(Array.from({ length: Math.min(CONCURRENCY, chunks.length) }, () => worker()))

  if (sessionId) await finalizeSession(caseId, sessionId)
  onProgress && onProgress(100, { done: files.length, total: files.length })

  return { uploaded: uploaded - errors.length, skipped, errors: errors.length ? errors : undefined, session_id: sessionId }
}

export { clientFileId, getUploadState, createUploadSession, finalizeSession }
