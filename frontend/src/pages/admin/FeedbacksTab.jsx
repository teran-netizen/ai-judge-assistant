import React, { useEffect, useState } from 'react'
import { CheckCircle, XCircle } from 'lucide-react'
import api from '../../api'
import { Spinner, EmptyState, StatusFilter } from '../AdminPage'

export default function FeedbacksTab() {
  const [feedbacks, setFeedbacks] = useState([])
  const [status, setStatus] = useState('new')
  const [loading, setLoading] = useState(true)
  const [processing, setProcessing] = useState(null)
  const [modal, setModal] = useState(null)
  const [modalResponse, setModalResponse] = useState('')
  const [modalReward, setModalReward] = useState('')
  const [actionError, setActionError] = useState(null)

  const load = () => {
    setLoading(true)
    api.getAdminFeedbacks(status)
      .then(setFeedbacks)
      .catch(console.error)
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [status])

  const handleProcess = (fb) => {
    setModal({ type: 'process', fb })
    setModalResponse('')
    setModalReward('')
    setActionError(null)
  }

  const confirmProcess = async () => {
    const fb = modal.fb
    const reward = parseInt(modalReward) || 0
    setProcessing(fb.id)
    setActionError(null)
    try {
      const newStatus = reward > 0 ? 'rewarded' : 'accepted'
      await api.processAdminFeedback(fb.id, newStatus, modalResponse, reward)
      setModal(null)
      load()
    } catch (e) {
      setActionError(e.message)
    } finally {
      setProcessing(null)
    }
  }

  const handleReject = (fb) => {
    setModal({ type: 'reject', fb })
    setModalResponse('')
    setActionError(null)
  }

  const confirmReject = async () => {
    const fb = modal.fb
    setProcessing(fb.id)
    setActionError(null)
    try {
      await api.processAdminFeedback(fb.id, 'rejected', modalResponse, 0)
      setModal(null)
      load()
    } catch (e) {
      setActionError(e.message)
    } finally {
      setProcessing(null)
    }
  }

  const categoryLabels = {
    bug: 'Баг', suggestion: 'Предложение', prompt: 'Промпт',
    new_category: 'Новая категория', other: 'Другое',
  }

  return (
    <div>
      <StatusFilter
        options={['new', 'in_review', 'accepted', 'rejected', 'rewarded']}
        labels={{ new: 'Новые', in_review: 'Проверка', accepted: 'Принятые', rejected: 'Отклон.', rewarded: 'Награда' }}
        value={status}
        onChange={(s) => setStatus(s)}
      />

      {loading ? <Spinner /> : feedbacks.length === 0 ? (
        <EmptyState text="Нет фидбека с этим статусом" />
      ) : (
        <div className="space-y-3 mt-4">
          {feedbacks.map(fb => (
            <div key={fb.id} className="card p-3 sm:p-4">
              <div className="flex items-center gap-2 mb-1.5">
                <span className="px-2 py-0.5 bg-surface-100 text-surface-600 rounded text-xs font-medium">
                  {categoryLabels[fb.category] || fb.category}
                </span>
                <span className="text-xs text-surface-400">
                  {new Date(fb.created_at).toLocaleString('ru')}
                </span>
              </div>
              <p className="text-sm text-surface-700 whitespace-pre-wrap">{fb.text}</p>
              {fb.admin_response && (
                <div className="mt-2 p-2 bg-surface-50 rounded text-xs text-surface-600">
                  <span className="font-medium">Ответ:</span> {fb.admin_response}
                </div>
              )}
              {fb.reward_kopecks > 0 && (
                <div className="mt-1 text-xs text-emerald-600 font-medium">
                  Награда: {(fb.reward_kopecks / 100).toLocaleString('ru')} ₽
                </div>
              )}
              {(status === 'new' || status === 'in_review') && (
                <div className="flex gap-2 mt-3 pt-2 border-t border-surface-100">
                  <button
                    onClick={() => handleProcess(fb)}
                    disabled={processing === fb.id}
                    className="flex items-center gap-1.5 px-3 py-1.5 bg-emerald-50 text-emerald-700 rounded-lg text-xs font-medium hover:bg-emerald-100 disabled:opacity-50"
                  >
                    <CheckCircle size={14} /> Принять
                  </button>
                  <button
                    onClick={() => handleReject(fb)}
                    disabled={processing === fb.id}
                    className="flex items-center gap-1.5 px-3 py-1.5 bg-red-50 text-red-700 rounded-lg text-xs font-medium hover:bg-red-100 disabled:opacity-50"
                  >
                    <XCircle size={14} /> Отклонить
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Action Modal — bottom sheet on mobile */}
      {modal && (
        <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center">
          <div className="absolute inset-0 bg-black/50" onClick={() => setModal(null)} />
          <div className="relative bg-white rounded-t-xl sm:rounded-xl shadow-xl p-4 sm:p-6 w-full sm:max-w-md sm:mx-4">
            <h3 className="text-lg font-semibold mb-4">
              {modal.type === 'process' ? 'Принять фидбек' : 'Отклонить фидбек'}
            </h3>
            <div className="space-y-3">
              <div>
                <label className="block text-xs text-surface-500 mb-1">
                  {modal.type === 'process' ? 'Ответ пользователю (необязательно)' : 'Причина отклонения'}
                </label>
                <textarea
                  value={modalResponse}
                  onChange={e => setModalResponse(e.target.value)}
                  className="w-full border border-surface-200 rounded-lg px-3 py-2 text-sm resize-none"
                  rows={3}
                  placeholder={modal.type === 'process' ? 'Необязательный ответ...' : 'Укажите причину...'}
                />
              </div>
              {modal.type === 'process' && (
                <div>
                  <label className="block text-xs text-surface-500 mb-1">Награда в токенах (0 = без награды)</label>
                  <input
                    type="number"
                    value={modalReward}
                    onChange={e => setModalReward(e.target.value)}
                    className="w-full border border-surface-200 rounded-lg px-3 py-2 text-sm"
                    placeholder="0"
                    min="0"
                  />
                </div>
              )}
              {actionError && (
                <div className="text-sm text-red-600 bg-red-50 px-3 py-2 rounded-lg">{actionError}</div>
              )}
            </div>
            <div className="flex gap-2 mt-5 justify-end">
              <button
                onClick={() => setModal(null)}
                className="px-4 py-2 text-sm text-surface-600 hover:text-surface-800"
              >
                Отмена
              </button>
              <button
                onClick={modal.type === 'process' ? confirmProcess : confirmReject}
                disabled={processing}
                className={`px-4 py-2 text-sm font-medium text-white rounded-lg disabled:opacity-50 ${
                  modal.type === 'process' ? 'bg-emerald-600 hover:bg-emerald-700' : 'bg-red-600 hover:bg-red-700'
                }`}
              >
                {processing ? '...' : modal.type === 'process' ? 'Принять' : 'Отклонить'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
