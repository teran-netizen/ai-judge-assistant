import { useState, useRef, useCallback } from 'react'
import api from '../api'

const TARGET_CHUNK_BYTES = 20 * 1024 * 1024 // 20MB
const MAX_FILES_PER_CHUNK = 5
const CONCURRENCY = 3
const MAX_RETRIES = 3

function buildChunks(files) {
  const chunks = []
  let current = []
  let currentSize = 0
  for (const f of files) {
    if (current.length >= MAX_FILES_PER_CHUNK || (currentSize + f.size > TARGET_CHUNK_BYTES && current.length > 0)) {
      chunks.push(current)
      current = []
      currentSize = 0
    }
    current.push(f)
    currentSize += f.size
  }
  if (current.length) chunks.push(current)
  return chunks
}

export default function useChunkedUpload(caseId) {
  const [uploadState, setUploadState] = useState({
    active: false,
    sessionId: null,
    totalFiles: 0,
    uploadedFiles: 0,
    fileStatuses: {}, // clientFileId -> 'pending'|'uploading'|'uploaded'|'error'
    error: null,
  })
  const abortRef = useRef(false)
  const fileMapRef = useRef({}) // clientFileId -> File

  const startUpload = useCallback(async (files) => {
    if (!caseId || !files.length) return

    abortRef.current = false

    // Generate client_file_id for each file
    const filesWithIds = files.map((f, i) => ({
      file: f,
      clientFileId: crypto.randomUUID(),
      index: i,
    }))

    const fileStatuses = {}
    filesWithIds.forEach(f => { fileStatuses[f.clientFileId] = 'pending' })
    fileMapRef.current = {}
    filesWithIds.forEach(f => { fileMapRef.current[f.clientFileId] = f.file })

    setUploadState({
      active: true,
      sessionId: null,
      totalFiles: files.length,
      uploadedFiles: 0,
      fileStatuses,
      error: null,
    })

    try {
      // 1. Create upload session
      const totalBytes = files.reduce((sum, f) => sum + f.size, 0)
      const session = await api.createUploadSession(caseId, files.length, totalBytes)
      const sessionId = session.upload_session_id

      setUploadState(s => ({ ...s, sessionId }))

      // 2. Build chunks
      const chunks = buildChunks(filesWithIds)
      let uploadedCount = 0
      const queue = [...chunks]

      // 3. Worker pool
      async function worker() {
        while (queue.length > 0 && !abortRef.current) {
          const chunk = queue.shift()
          if (!chunk) break

          const batchId = crypto.randomUUID()
          const chunkFiles = chunk.map(f => f.file)

          // Mark uploading
          setUploadState(s => {
            const fs = { ...s.fileStatuses }
            chunk.forEach(f => { fs[f.clientFileId] = 'uploading' })
            return { ...s, fileStatuses: fs }
          })

          let success = false
          for (let attempt = 0; attempt < MAX_RETRIES && !success; attempt++) {
            try {
              // Upload each file in chunk individually for proper client_file_id
              for (const f of chunk) {
                await api.uploadChunk(caseId, [f.file], {
                  upload_session_id: sessionId,
                  client_file_id: f.clientFileId,
                  upload_batch_id: batchId,
                })

                uploadedCount++
                setUploadState(s => ({
                  ...s,
                  uploadedFiles: uploadedCount,
                  fileStatuses: { ...s.fileStatuses, [f.clientFileId]: 'uploaded' },
                }))
              }
              success = true
            } catch (e) {
              if (attempt === MAX_RETRIES - 1) {
                // Mark failed
                setUploadState(s => {
                  const fs = { ...s.fileStatuses }
                  chunk.forEach(f => {
                    if (fs[f.clientFileId] !== 'uploaded') fs[f.clientFileId] = 'error'
                  })
                  return { ...s, fileStatuses: fs }
                })
              } else {
                await new Promise(r => setTimeout(r, 2000 * (attempt + 1)))
              }
            }
          }
        }
      }

      const workers = Array.from({ length: CONCURRENCY }, () => worker())
      await Promise.all(workers)

      if (abortRef.current) return

      // 4. Finalize
      await api.finalizeUploadSession(caseId, sessionId)
      setUploadState(s => ({ ...s, active: false }))

      return sessionId
    } catch (e) {
      setUploadState(s => ({ ...s, active: false, error: e.message }))
      throw e
    }
  }, [caseId])

  const cancelUpload = useCallback(() => {
    abortRef.current = true
    setUploadState(s => ({ ...s, active: false }))
  }, [])

  return { uploadState, startUpload, cancelUpload }
}
