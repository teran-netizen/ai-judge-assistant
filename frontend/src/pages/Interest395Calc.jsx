import { useState, useEffect } from 'react'
import api from '../api'
import { Calculator, Scale, ArrowRight } from 'lucide-react'

// Key rates history (date, rate%)
const KEY_RATES = [
  { from: '2024-10-28', rate: 21.0 },
  { from: '2025-02-14', rate: 21.0 },
  { from: '2025-04-25', rate: 21.0 },
  { from: '2025-06-06', rate: 20.0 },
  { from: '2025-07-25', rate: 19.0 },
  { from: '2025-09-12', rate: 18.0 },
  { from: '2025-10-24', rate: 17.0 },
  { from: '2025-12-19', rate: 16.0 },
  { from: '2026-02-14', rate: 15.0 },
  { from: '2026-03-21', rate: 15.0 },
]

function getRate(dateStr) {
  for (let i = KEY_RATES.length - 1; i >= 0; i--) {
    if (dateStr >= KEY_RATES[i].from) return KEY_RATES[i].rate
  }
  return KEY_RATES[0].rate
}

function daysInYear(dateStr) {
  const y = parseInt(dateStr.slice(0, 4))
  return (y % 4 === 0 && (y % 100 !== 0 || y % 400 === 0)) ? 366 : 365
}

function addDay(dateStr) {
  const d = new Date(dateStr)
  d.setDate(d.getDate() + 1)
  return d.toISOString().slice(0, 10)
}

function calcInterest(amount, dateFrom, dateTo) {
  if (!amount || !dateFrom || !dateTo || dateFrom >= dateTo) return { total: 0, periods: [] }

  let current = dateFrom
  let total = 0
  const periods = []
  let periodStart = current
  let periodRate = getRate(current)

  while (current < dateTo) {
    const rate = getRate(current)
    if (rate !== periodRate) {
      const days = Math.round((new Date(current) - new Date(periodStart)) / 86400000)
      if (days > 0) {
        const interest = amount * days * periodRate / 100 / daysInYear(periodStart)
        periods.push({ from: periodStart, to: current, days, rate: periodRate, interest: Math.round(interest * 100) / 100 })
        total += interest
      }
      periodStart = current
      periodRate = rate
    }
    current = addDay(current)
  }

  // Last period
  const days = Math.round((new Date(dateTo) - new Date(periodStart)) / 86400000)
  if (days > 0) {
    const interest = amount * days * periodRate / 100 / daysInYear(periodStart)
    periods.push({ from: periodStart, to: dateTo, days, rate: periodRate, interest: Math.round(interest * 100) / 100 })
    total += interest
  }

  return { total: Math.round(total * 100) / 100, periods }
}

export default function Interest395Calc() {
  const [amount, setAmount] = useState('')
  useEffect(() => { try { fetch('/api/activity', {method:'POST',headers:{'Content-Type':'application/json'},credentials:'include',body:JSON.stringify({action:'page_calculator',details:'Interest395'})}).catch(()=>{}) } catch {} }, [])
  const [dateFrom, setDateFrom] = useState('')
  useEffect(() => { try { fetch('/api/activity', {method:'POST',headers:{'Content-Type':'application/json'},credentials:'include',body:JSON.stringify({action:'page_calculator',details:'Interest395'})}).catch(()=>{}) } catch {} }, [])
  const [dateTo, setDateTo] = useState('')
  useEffect(() => { try { fetch('/api/activity', {method:'POST',headers:{'Content-Type':'application/json'},credentials:'include',body:JSON.stringify({action:'page_calculator',details:'Interest395'})}).catch(()=>{}) } catch {} }, [])
  const result = calcInterest(parseFloat(amount), dateFrom, dateTo)

  return (
    <div className="min-h-screen bg-surface-50">
      <div className="max-w-2xl mx-auto px-4 py-8 sm:py-12">
        <div className="text-center mb-8">
          <h1 className="text-2xl sm:text-3xl font-display font-bold mb-2">Калькулятор процентов по ст. 395 ГК РФ</h1>
          <p className="text-surface-500">Расчёт процентов за пользование чужими денежными средствами</p>
        </div>

        <div className="card p-6 mb-6">
          <div className="space-y-4">
            <div>
              <label className="text-sm font-medium text-surface-700 mb-1.5 block">Сумма задолженности (руб.)</label>
              <input type="number" value={amount} onChange={e => setAmount(e.target.value)} placeholder="Введите сумму долга" className="input w-full text-lg" />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-sm font-medium text-surface-700 mb-1.5 block">Начало просрочки</label>
                <input type="date" value={dateFrom} onChange={e => setDateFrom(e.target.value)} className="input w-full" />
              </div>
              <div>
                <label className="text-sm font-medium text-surface-700 mb-1.5 block">Конец просрочки</label>
                <input type="date" value={dateTo} onChange={e => setDateTo(e.target.value)} className="input w-full" />
              </div>
            </div>
          </div>

          {result.total > 0 && (
            <div className="mt-6">
              <div className="p-4 bg-brand-50 rounded-xl border border-brand-200 text-center mb-4">
                <div className="text-sm text-surface-500 mb-1">Проценты по ст. 395 ГК РФ</div>
                <div className="text-3xl font-bold text-brand-700">{result.total.toLocaleString('ru', { minimumFractionDigits: 2 })} &#8381;</div>
              </div>

              {result.periods.length > 0 && (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-[11px] text-surface-500 border-b">
                        <th className="text-left pb-2">Период</th>
                        <th className="text-right pb-2">Дней</th>
                        <th className="text-right pb-2">Ставка</th>
                        <th className="text-right pb-2">Проценты</th>
                      </tr>
                    </thead>
                    <tbody>
                      {result.periods.map((p, i) => (
                        <tr key={i} className="border-b border-surface-100">
                          <td className="py-1.5 text-xs">{p.from} — {p.to}</td>
                          <td className="py-1.5 text-right">{p.days}</td>
                          <td className="py-1.5 text-right">{p.rate}%</td>
                          <td className="py-1.5 text-right font-medium">{p.interest.toLocaleString('ru', { minimumFractionDigits: 2 })} &#8381;</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
        </div>

        <div className="card p-5 mb-6">
          <h2 className="font-semibold mb-3 text-sm">Формула расчёта</h2>
          <p className="text-xs text-surface-500 leading-relaxed">
            Проценты = Сумма долга x Количество дней просрочки x Ключевая ставка ЦБ РФ / Количество дней в году.
            При изменении ставки расчёт производится по каждому периоду отдельно. Текущая ключевая ставка ЦБ РФ — 15% (с 21.03.2026).
          </p>
        </div>

        <div className="card p-6 bg-gradient-to-br from-brand-50 to-white border-brand-200">
          <div className="flex items-center gap-3 mb-3">
            <Scale size={24} className="text-brand-600" />
            <h2 className="font-display font-bold">Подготовьте проект решения суда за 5 минут по фото документов</h2>
          </div>
          <p className="text-surface-600 text-sm mb-4">Проект решения суда за 5 минут. Загрузите материалы дела — ИИ напишет проект решения со ссылками на нормы права.</p>
          <a href="/login" className="btn-primary inline-flex items-center gap-2 px-5 py-2.5 text-sm">
            Решение суда за 5 минут <ArrowRight size={16} />
          </a>
        </div>

        <div className="text-center mt-6 text-xs text-surface-400">
          Расчёт носит информационный характер. Основание — ст. 395 ГК РФ, ключевая ставка ЦБ РФ.
        </div>
      </div>
    </div>
  )
}
