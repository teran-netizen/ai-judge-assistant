import { useState } from 'react'
import { ymGoal } from '../../ym'
import api from '../../api'

export default function EmailCollectModal({ caseId, onClose, onSuccess, onEmailCollected }) {
  const [email, setEmail] = useState('')
  const [loading, setLoading] = useState(false)
  const [sent, setSent] = useState(false)

  const handleSubmit = async () => {
    if (!email || !email.includes('@')) return
    setLoading(true)
    try {
      await api.collectEmail(email)
      ymGoal('email_collected')
      if (onEmailCollected) onEmailCollected(email)
      setSent(true)
      setTimeout(onSuccess, 2000)
    } catch {
      onSuccess()
    }
    setLoading(false)
  }

  if (sent) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 animate-in">
        <div className="bg-white rounded-2xl shadow-xl max-w-md w-full p-6 text-center">
          <div className="text-4xl mb-3">✅</div>
          <h2 className="text-lg font-display font-bold">Решение отправлено!</h2>
          <p className="text-surface-500 text-sm mt-2">Проверьте почту {email}</p>
        </div>
      </div>
    )
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 animate-in">
      <div className="bg-white rounded-2xl shadow-xl max-w-md w-full p-6">
        <div className="text-center mb-4">
          <div className="text-3xl mb-2">📧</div>
          <h2 className="text-lg font-display font-bold">Получить документ на email?</h2>
          <p className="text-surface-500 text-sm mt-1">Отправим готовый документ в формате .docx на вашу почту</p>
        </div>
        <input
          type="email"
          value={email}
          onChange={e => setEmail(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && handleSubmit()}
          placeholder="your@email.com"
          className="w-full px-4 py-3 border border-surface-200 rounded-xl text-sm focus:outline-none focus:border-brand-500 mb-3"
          autoFocus
        />
        <button
          onClick={handleSubmit}
          disabled={loading || !email.includes('@')}
          className="btn-primary w-full py-3 text-sm"
        >
          {loading ? 'Отправляю...' : 'Отправить на email'}
        </button>
        <button onClick={onClose} className="w-full mt-2 text-sm text-surface-400 hover:text-surface-600 py-2">Позже</button>
      </div>
    </div>
  )
}
