import { useState, useEffect } from 'react'
import api from '../api'
import { Scale, ArrowRight } from 'lucide-react'

const KEY_RATE = 15.0

function calcCompensation(amount, days) {
  if (!amount || !days) return 0
  // ст. 236 ТК РФ: 1/150 ключевой ставки за каждый день задержки
  return Math.round(amount * days * KEY_RATE / 100 / 150 * 100) / 100
}

export default function ZarplataCalc() {
  const [amount, setAmount] = useState('')
  useEffect(() => { try { fetch('/api/activity', {method:'POST',headers:{'Content-Type':'application/json'},credentials:'include',body:JSON.stringify({action:'page_calculator',details:'Zarplata'})}).catch(()=>{}) } catch {} }, [])
  const [days, setDays] = useState('')
  useEffect(() => { try { fetch('/api/activity', {method:'POST',headers:{'Content-Type':'application/json'},credentials:'include',body:JSON.stringify({action:'page_calculator',details:'Zarplata'})}).catch(()=>{}) } catch {} }, [])
  const result = calcCompensation(parseFloat(amount), parseInt(days))

  return (
    <div className="min-h-screen bg-surface-50">
      <div className="max-w-2xl mx-auto px-4 py-8 sm:py-12">
        <div className="text-center mb-8">
          <h1 className="text-2xl sm:text-3xl font-display font-bold mb-2">Калькулятор компенсации за задержку зарплаты</h1>
          <p className="text-surface-500">Расчёт по ст. 236 ТК РФ (1/150 ключевой ставки ЦБ)</p>
        </div>

        <div className="card p-6 mb-6">
          <div className="space-y-4">
            <div>
              <label className="text-sm font-medium text-surface-700 mb-1.5 block">Сумма задержанной выплаты (руб.)</label>
              <input type="number" value={amount} onChange={e => setAmount(e.target.value)} placeholder="Сумма зарплаты" className="input w-full text-lg" />
            </div>
            <div>
              <label className="text-sm font-medium text-surface-700 mb-1.5 block">Количество дней задержки</label>
              <input type="number" value={days} onChange={e => setDays(e.target.value)} placeholder="Дней" className="input w-full" />
            </div>
          </div>

          {result > 0 && (
            <div className="mt-6 p-4 bg-brand-50 rounded-xl border border-brand-200 text-center">
              <div className="text-sm text-surface-500 mb-1">Компенсация за задержку</div>
              <div className="text-3xl font-bold text-brand-700">{result.toLocaleString('ru', {minimumFractionDigits: 2})} &#8381;</div>
            </div>
          )}
        </div>

        <div className="card p-5 mb-6">
          <h2 className="font-semibold mb-3 text-sm">Формула (ст. 236 ТК РФ)</h2>
          <p className="text-xs text-surface-500">Компенсация = Сумма выплаты x Дни задержки x 1/150 x Ключевая ставка ЦБ ({KEY_RATE}%)</p>
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
