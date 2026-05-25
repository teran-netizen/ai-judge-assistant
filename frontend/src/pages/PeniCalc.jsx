import { useState, useEffect } from 'react'
import api from '../api'
import { Scale, ArrowRight } from 'lucide-react'

// 1/300 ключевой ставки за каждый день просрочки (с 31-го дня 1/150)
const KEY_RATE = 15.0 // с 21.03.2026

function calcPeni(amount, days) {
  if (!amount || !days || days <= 0) return { total: 0, first30: 0, after30: 0 }
  const first30days = Math.min(days, 30)
  const after30days = Math.max(0, days - 30)
  const first30 = amount * first30days * KEY_RATE / 100 / 300
  const after30 = amount * after30days * KEY_RATE / 100 / 150
  return {
    total: Math.round((first30 + after30) * 100) / 100,
    first30: Math.round(first30 * 100) / 100,
    after30: Math.round(after30 * 100) / 100,
    first30days,
    after30days,
  }
}

export default function PeniCalc() {
  const [amount, setAmount] = useState('')
  useEffect(() => { try { fetch('/api/activity', {method:'POST',headers:{'Content-Type':'application/json'},credentials:'include',body:JSON.stringify({action:'page_calculator',details:'Peni'})}).catch(()=>{}) } catch {} }, [])
  const [days, setDays] = useState('')
  useEffect(() => { try { fetch('/api/activity', {method:'POST',headers:{'Content-Type':'application/json'},credentials:'include',body:JSON.stringify({action:'page_calculator',details:'Peni'})}).catch(()=>{}) } catch {} }, [])
  const r = calcPeni(parseFloat(amount), parseInt(days))

  return (
    <div className="min-h-screen bg-surface-50">
      <div className="max-w-2xl mx-auto px-4 py-8 sm:py-12">
        <div className="text-center mb-8">
          <h1 className="text-2xl sm:text-3xl font-display font-bold mb-2">Калькулятор пеней по налогам</h1>
          <p className="text-surface-500">Расчёт пеней по ст. 75 НК РФ (ключевая ставка ЦБ {KEY_RATE}%)</p>
        </div>

        <div className="card p-6 mb-6">
          <div className="space-y-4">
            <div>
              <label className="text-sm font-medium text-surface-700 mb-1.5 block">Сумма задолженности (руб.)</label>
              <input type="number" value={amount} onChange={e => setAmount(e.target.value)} placeholder="Сумма недоимки" className="input w-full text-lg" />
            </div>
            <div>
              <label className="text-sm font-medium text-surface-700 mb-1.5 block">Количество дней просрочки</label>
              <input type="number" value={days} onChange={e => setDays(e.target.value)} placeholder="Дней" className="input w-full" />
            </div>
          </div>

          {r.total > 0 && (
            <div className="mt-6 p-4 bg-brand-50 rounded-xl border border-brand-200 text-center">
              <div className="text-sm text-surface-500 mb-1">Сумма пеней</div>
              <div className="text-3xl font-bold text-brand-700">{r.total.toLocaleString('ru', {minimumFractionDigits: 2})} &#8381;</div>
              <div className="text-xs text-surface-400 mt-2">
                Первые 30 дней (1/300): {r.first30.toLocaleString('ru', {minimumFractionDigits: 2})} &#8381;
                {r.after30 > 0 && <> | С 31-го дня (1/150): {r.after30.toLocaleString('ru', {minimumFractionDigits: 2})} &#8381;</>}
              </div>
            </div>
          )}
        </div>

        <div className="card p-5 mb-6">
          <h2 className="font-semibold mb-3 text-sm">Формула расчёта</h2>
          <div className="text-xs text-surface-500 space-y-1">
            <div>Первые 30 дней: Сумма x Дни x Ключевая ставка / 300</div>
            <div>С 31-го дня: Сумма x Дни x Ключевая ставка / 150</div>
            <div>Ключевая ставка ЦБ РФ: {KEY_RATE}% (с 21.03.2026)</div>
          </div>
        </div>

        <div className="card p-6 bg-gradient-to-br from-brand-50 to-white border-brand-200">
          <div className="flex items-center gap-3 mb-3">
            <Scale size={24} className="text-brand-600" />
            <h2 className="font-display font-bold">Подготовьте проект решения суда за 5 минут по фото документов</h2>
          </div>
          <p className="text-surface-600 text-sm mb-4">Проект решения суда за 5 минут с помощью нейросети.</p>
          <a href="/login" className="btn-primary inline-flex items-center gap-2 px-5 py-2.5 text-sm">Попробовать <ArrowRight size={16} /></a>
        </div>
      </div>
    </div>
  )
}
