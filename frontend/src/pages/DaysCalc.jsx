import { useState, useEffect } from 'react'
import api from '../api'
import { Scale, ArrowRight } from 'lucide-react'

function calcDays(from, to) {
  if (!from || !to) return null
  const d1 = new Date(from)
  const d2 = new Date(to)
  const diff = Math.round((d2 - d1) / 86400000)
  // Count working days (excluding weekends)
  let workDays = 0
  let current = new Date(d1)
  while (current < d2) {
    const day = current.getDay()
    if (day !== 0 && day !== 6) workDays++
    current.setDate(current.getDate() + 1)
  }
  return { calendar: diff, working: workDays }
}

export default function DaysCalc() {
  const [dateFrom, setDateFrom] = useState('')
  useEffect(() => { try { fetch('/api/activity', {method:'POST',headers:{'Content-Type':'application/json'},credentials:'include',body:JSON.stringify({action:'page_calculator',details:'Days'})}).catch(()=>{}) } catch {} }, [])
  const [dateTo, setDateTo] = useState('')
  useEffect(() => { try { fetch('/api/activity', {method:'POST',headers:{'Content-Type':'application/json'},credentials:'include',body:JSON.stringify({action:'page_calculator',details:'Days'})}).catch(()=>{}) } catch {} }, [])
  const result = calcDays(dateFrom, dateTo)

  return (
    <div className="min-h-screen bg-surface-50">
      <div className="max-w-2xl mx-auto px-4 py-8 sm:py-12">
        <div className="text-center mb-8">
          <h1 className="text-2xl sm:text-3xl font-display font-bold mb-2">Калькулятор дней в периоде</h1>
          <p className="text-surface-500">Подсчёт календарных и рабочих дней между датами</p>
        </div>

        <div className="card p-6 mb-6">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-sm font-medium text-surface-700 mb-1.5 block">Дата начала</label>
              <input type="date" value={dateFrom} onChange={e => setDateFrom(e.target.value)} className="input w-full" />
            </div>
            <div>
              <label className="text-sm font-medium text-surface-700 mb-1.5 block">Дата окончания</label>
              <input type="date" value={dateTo} onChange={e => setDateTo(e.target.value)} className="input w-full" />
            </div>
          </div>

          {result && result.calendar > 0 && (
            <div className="mt-6 grid grid-cols-2 gap-3">
              <div className="p-4 bg-brand-50 rounded-xl border border-brand-200 text-center">
                <div className="text-sm text-surface-500 mb-1">Календарных дней</div>
                <div className="text-3xl font-bold text-brand-700">{result.calendar}</div>
              </div>
              <div className="p-4 bg-emerald-50 rounded-xl border border-emerald-200 text-center">
                <div className="text-sm text-surface-500 mb-1">Рабочих дней</div>
                <div className="text-3xl font-bold text-emerald-700">{result.working}</div>
              </div>
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
