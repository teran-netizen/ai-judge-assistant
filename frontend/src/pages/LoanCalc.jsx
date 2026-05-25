import { useState, useEffect } from 'react'
import api from '../api'
import { Scale, ArrowRight } from 'lucide-react'

function calcLoanInterest(amount, rate, days) {
  if (!amount || !rate || !days) return 0
  return Math.round(amount * rate / 100 / 365 * days * 100) / 100
}

export default function LoanCalc() {
  const [amount, setAmount] = useState('')
  useEffect(() => { try { fetch('/api/activity', {method:'POST',headers:{'Content-Type':'application/json'},credentials:'include',body:JSON.stringify({action:'page_calculator',details:'Loan'})}).catch(()=>{}) } catch {} }, [])
  const [rate, setRate] = useState('15')
  useEffect(() => { try { fetch('/api/activity', {method:'POST',headers:{'Content-Type':'application/json'},credentials:'include',body:JSON.stringify({action:'page_calculator',details:'Loan'})}).catch(()=>{}) } catch {} }, [])
  const [days, setDays] = useState('')
  useEffect(() => { try { fetch('/api/activity', {method:'POST',headers:{'Content-Type':'application/json'},credentials:'include',body:JSON.stringify({action:'page_calculator',details:'Loan'})}).catch(()=>{}) } catch {} }, [])
  const result = calcLoanInterest(parseFloat(amount), parseFloat(rate), parseInt(days))

  return (
    <div className="min-h-screen bg-surface-50">
      <div className="max-w-2xl mx-auto px-4 py-8 sm:py-12">
        <div className="text-center mb-8">
          <h1 className="text-2xl sm:text-3xl font-display font-bold mb-2">Калькулятор процентов по договору займа</h1>
          <p className="text-surface-500">Расчёт процентов по ст. 809 ГК РФ</p>
        </div>

        <div className="card p-6 mb-6">
          <div className="space-y-4">
            <div>
              <label className="text-sm font-medium text-surface-700 mb-1.5 block">Сумма займа (руб.)</label>
              <input type="number" value={amount} onChange={e => setAmount(e.target.value)} placeholder="Сумма" className="input w-full text-lg" />
            </div>
            <div>
              <label className="text-sm font-medium text-surface-700 mb-1.5 block">Процентная ставка (% годовых)</label>
              <input type="number" step="0.1" value={rate} onChange={e => setRate(e.target.value)} className="input w-full" />
            </div>
            <div>
              <label className="text-sm font-medium text-surface-700 mb-1.5 block">Срок (дней)</label>
              <input type="number" value={days} onChange={e => setDays(e.target.value)} placeholder="Дней" className="input w-full" />
            </div>
          </div>

          {result > 0 && (
            <div className="mt-6 p-4 bg-brand-50 rounded-xl border border-brand-200 text-center">
              <div className="text-sm text-surface-500 mb-1">Проценты по займу</div>
              <div className="text-3xl font-bold text-brand-700">{result.toLocaleString('ru', {minimumFractionDigits: 2})} &#8381;</div>
              <div className="text-xs text-surface-400 mt-1">Возврат с процентами: {(parseFloat(amount) + result).toLocaleString('ru', {minimumFractionDigits: 2})} &#8381;</div>
            </div>
          )}
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
