import { useState, useEffect } from 'react'
import api from '../api'
import { Scale, ArrowRight } from 'lucide-react'

// ст. 333.21 НК РФ (с 08.09.2024)
const ARB_TIERS = [
  { max: 100000, base: 10000, pct: 0, over: 0 },
  { max: 200000, base: 10000, pct: 5, over: 100000 },
  { max: 1000000, base: 15000, pct: 3, over: 200000 },
  { max: 2000000, base: 39000, pct: 2, over: 1000000 },
  { max: 5000000, base: 59000, pct: 1.5, over: 2000000 },
  { max: 10000000, base: 104000, pct: 1, over: 5000000 },
  { max: 30000000, base: 154000, pct: 0.5, over: 10000000 },
  { max: 50000000, base: 254000, pct: 0.3, over: 30000000 },
  { max: 100000000, base: 314000, pct: 0.2, over: 50000000 },
  { max: Infinity, base: 414000, pct: 0.1, over: 100000000 },
]

function calcArb(amount) {
  if (!amount || amount <= 0) return 0
  for (const tier of ARB_TIERS) {
    if (amount <= tier.max) {
      let result = tier.base + (amount - tier.over) * tier.pct / 100
      return Math.min(Math.round(result), 10000000)
    }
  }
  return 10000000
}

export default function GosposhlinaArbCalc() {
  const [amount, setAmount] = useState('')
  useEffect(() => { try { fetch('/api/activity', {method:'POST',headers:{'Content-Type':'application/json'},credentials:'include',body:JSON.stringify({action:'page_calculator',details:'GosposhlinaArb'})}).catch(()=>{}) } catch {} }, [])
  const result = calcArb(parseFloat(amount))

  return (
    <div className="min-h-screen bg-surface-50">
      <div className="max-w-2xl mx-auto px-4 py-8 sm:py-12">
        <div className="text-center mb-8">
          <h1 className="text-2xl sm:text-3xl font-display font-bold mb-2">Калькулятор госпошлины в арбитражный суд</h1>
          <p className="text-surface-500">Расчёт по ст. 333.21 НК РФ (актуально на 2026 год)</p>
        </div>

        <div className="card p-6 mb-6">
          <label className="text-sm font-medium text-surface-700 mb-1.5 block">Цена иска (руб.)</label>
          <input type="number" value={amount} onChange={e => setAmount(e.target.value)} placeholder="Введите сумму иска" className="input w-full text-lg" />

          {result > 0 && (
            <div className="mt-6 p-4 bg-brand-50 rounded-xl border border-brand-200 text-center">
              <div className="text-sm text-surface-500 mb-1">Размер госпошлины</div>
              <div className="text-3xl font-bold text-brand-700">{result.toLocaleString('ru')} &#8381;</div>
            </div>
          )}
        </div>

        <div className="card p-5 mb-6">
          <h2 className="font-semibold mb-3 text-sm">Шкала (ст. 333.21 НК РФ, арбитраж)</h2>
          <div className="text-xs text-surface-500 space-y-1.5">
            <div>до 100 000 &#8381; — 10 000 &#8381;</div>
            <div>100 001 — 200 000 &#8381; — 10 000 + 5% свыше 100 000</div>
            <div>200 001 — 1 000 000 &#8381; — 15 000 + 3% свыше 200 000</div>
            <div>1 000 001 — 2 000 000 &#8381; — 39 000 + 2% свыше 1 000 000</div>
            <div>2 000 001 — 5 000 000 &#8381; — 59 000 + 1,5% свыше 2 000 000</div>
            <div>5 000 001 — 10 000 000 &#8381; — 104 000 + 1% свыше 5 000 000</div>
            <div>10 000 001 — 30 000 000 &#8381; — 154 000 + 0,5% свыше 10 000 000</div>
            <div>свыше 30 000 000 &#8381; — далее по шкале (макс. 10 000 000 &#8381;)</div>
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
