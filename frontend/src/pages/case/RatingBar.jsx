import { useState } from 'react'
import { Star, X } from 'lucide-react'
import api from '../../api'

export default function RatingBar({ caseId, initialRating = 0 }) {
  const [rating, setRating] = useState(initialRating)
  const [hover, setHover] = useState(0)
  const [saved, setSaved] = useState(!!initialRating)
  const [showReview, setShowReview] = useState(false)
  const [reviewText, setReviewText] = useState('')
  const [reviewSent, setReviewSent] = useState(false)

  const handleRate = async (value) => {
    setRating(value)
    setSaved(true)
    try {
      await api.rateCase(caseId, value)
      api.trackAction('rate', `rating=${value}`, caseId)
    } catch {}
  }

  const handleSubmitReview = async () => {
    if (!reviewText.trim()) return
    try {
      await api.rateCase(caseId, rating, reviewText.trim())
      api.trackAction('review', reviewText.trim().slice(0, 50), caseId)
      setReviewSent(true)
      setShowReview(false)
    } catch {}
  }

  return (
    <div className="mt-2">
      <div className="flex items-center gap-3 text-surface-300 text-sm">
        <span>{saved ? 'Спасибо!' : 'Оцените качество'}</span>
        <div className="flex gap-0.5">
          {[1, 2, 3, 4, 5].map(i => (
            <button
              key={i}
              onClick={() => handleRate(i)}
              onMouseEnter={() => setHover(i)}
              onMouseLeave={() => setHover(0)}
              className="p-0.5 transition-colors hover:text-amber-400"
            >
              <Star
                size={18}
                className={i <= (hover || rating) ? 'text-amber-400 fill-amber-400' : 'text-surface-200'}
              />
            </button>
          ))}
        </div>
        {saved && !reviewSent && (
          <button
            onClick={() => setShowReview(true)}
            className="text-surface-300 hover:text-surface-500 text-xs underline underline-offset-2 transition-colors"
          >
            Оставить отзыв
          </button>
        )}
        {reviewSent && <span className="text-emerald-400 text-xs">Отзыв отправлен</span>}
      </div>

      {showReview && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-xl shadow-xl max-w-md w-full p-5 relative">
            <button
              onClick={() => setShowReview(false)}
              className="absolute top-3 right-3 text-surface-400 hover:text-surface-600"
            >
              <X size={18} />
            </button>
            <h3 className="text-base font-semibold mb-3">Ваш отзыв</h3>
            <textarea
              value={reviewText}
              onChange={e => setReviewText(e.target.value)}
              placeholder="Что понравилось? Что можно улучшить?"
              className="w-full border border-surface-200 rounded-lg p-3 text-sm resize-none h-24 outline-none focus:border-brand-400"
              maxLength={1000}
              autoFocus
            />
            <button
              onClick={handleSubmitReview}
              disabled={!reviewText.trim()}
              className="mt-3 btn-primary w-full py-2.5 text-sm"
            >
              Отправить
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
