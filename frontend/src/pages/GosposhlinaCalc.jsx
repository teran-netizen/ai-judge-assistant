import { useState, useEffect } from 'react'
import api from '../api'
import { Calculator, Scale, ArrowRight } from 'lucide-react'

const PROPERTY_TIERS = [
  { max: 100000, base: 4000, pct: 0, over: 0 },
  { max: 300000, base: 4000, pct: 3, over: 100000 },
  { max: 500000, base: 10000, pct: 2.5, over: 300000 },
  { max: 1000000, base: 15000, pct: 2, over: 500000 },
  { max: 3000000, base: 25000, pct: 1, over: 1000000 },
  { max: 8000000, base: 45000, pct: 0.7, over: 3000000 },
  { max: 24000000, base: 80000, pct: 0.35, over: 8000000 },
  { max: 50000000, base: 136000, pct: 0.3, over: 24000000 },
  { max: 100000000, base: 214000, pct: 0.2, over: 50000000 },
  { max: Infinity, base: 314000, pct: 0.15, over: 100000000 },
]

const FIXED_TYPES = [
  { label: 'Расторжение брака', value: 5000 },
  { label: 'Взыскание алиментов', value: 150 },
  { label: 'Неимущественный иск (физлицо)', value: 3000 },
  { label: 'Неимущественный иск (организация)', value: 20000 },
  { label: 'Апелляция (физлицо)', value: 3000 },
  { label: 'Апелляция (организация)', value: 15000 },
  { label: 'Кассация (физлицо)', value: 5000 },
  { label: 'Кассация (организация)', value: 20000 },
]

function calcGosposhlina(amount) {
  if (!amount || amount <= 0) return 0
  for (const tier of PROPERTY_TIERS) {
    if (amount <= tier.max) {
      let result = tier.base + (amount - tier.over) * tier.pct / 100
      return Math.min(Math.round(result), 900000)
    }
  }
  return 900000
}

export default function GosposhlinaCalc() {
  const [mode, setMode] = useState('property')
  useEffect(() => { try { fetch('/api/activity', {method:'POST',headers:{'Content-Type':'application/json'},credentials:'include',body:JSON.stringify({action:'page_calculator',details:'Gosposhlina'})}).catch(()=>{}) } catch {} }, [])
  const [amount, setAmount] = useState('')
  useEffect(() => { try { fetch('/api/activity', {method:'POST',headers:{'Content-Type':'application/json'},credentials:'include',body:JSON.stringify({action:'page_calculator',details:'Gosposhlina'})}).catch(()=>{}) } catch {} }, [])
  const [fixedType, setFixedType] = useState(0)
  useEffect(() => { try { fetch('/api/activity', {method:'POST',headers:{'Content-Type':'application/json'},credentials:'include',body:JSON.stringify({action:'page_calculator',details:'Gosposhlina'})}).catch(()=>{}) } catch {} }, [])
  const result = mode === 'property' ? calcGosposhlina(parseFloat(amount)) : FIXED_TYPES[fixedType]?.value || 0

  return (
    <div className="min-h-screen bg-surface-50">
      <div className="max-w-2xl mx-auto px-4 py-8 sm:py-12">
        <div className="text-center mb-8">
          <h1 className="text-2xl sm:text-3xl font-display font-bold mb-2">Калькулятор госпошлины в суд</h1>
          <p className="text-surface-500">Расчёт по ст. 333.19 НК РФ (актуально на 2026 год)</p>
        </div>

        <div className="card p-6 mb-6">
          <div className="flex gap-2 mb-6">
            <button onClick={() => setMode('property')} className={`flex-1 py-2 rounded-lg text-sm font-medium transition-colors ${mode === 'property' ? 'bg-brand-600 text-white' : 'bg-surface-100 text-surface-600'}`}>
              Имущественный иск
            </button>
            <button onClick={() => setMode('fixed')} className={`flex-1 py-2 rounded-lg text-sm font-medium transition-colors ${mode === 'fixed' ? 'bg-brand-600 text-white' : 'bg-surface-100 text-surface-600'}`}>
              Фиксированная пошлина
            </button>
          </div>

          {mode === 'property' ? (
            <div>
              <label className="text-sm font-medium text-surface-700 mb-1.5 block">Цена иска (руб.)</label>
              <input
                type="number"
                value={amount}
                onChange={e => setAmount(e.target.value)}
                placeholder="Введите сумму иска"
                className="input w-full text-lg"
              />
            </div>
          ) : (
            <div>
              <label className="text-sm font-medium text-surface-700 mb-1.5 block">Тип обращения</label>
              <select value={fixedType} onChange={e => setFixedType(parseInt(e.target.value))} className="input w-full">
                {FIXED_TYPES.map((t, i) => <option key={i} value={i}>{t.label}</option>)}
              </select>
            </div>
          )}

          {result > 0 && (
            <div className="mt-6 p-4 bg-brand-50 rounded-xl border border-brand-200 text-center">
              <div className="text-sm text-surface-500 mb-1">Размер госпошлины</div>
              <div className="text-3xl font-bold text-brand-700">{result.toLocaleString('ru')} &#8381;</div>
            </div>
          )}
        </div>

        {mode === 'property' && (
          <div className="card p-5 mb-6">
            <h2 className="font-semibold mb-3 text-sm">Шкала расчёта (ст. 333.19 НК РФ)</h2>
            <div className="text-xs text-surface-500 space-y-1.5">
              <div>до 100 000 &#8381; — 4 000 &#8381;</div>
              <div>100 001 — 300 000 &#8381; — 4 000 + 3% свыше 100 000</div>
              <div>300 001 — 500 000 &#8381; — 10 000 + 2,5% свыше 300 000</div>
              <div>500 001 — 1 000 000 &#8381; — 15 000 + 2% свыше 500 000</div>
              <div>1 000 001 — 3 000 000 &#8381; — 25 000 + 1% свыше 1 000 000</div>
              <div>3 000 001 — 8 000 000 &#8381; — 45 000 + 0,7% свыше 3 000 000</div>
              <div>8 000 001 — 24 000 000 &#8381; — 80 000 + 0,35% свыше 8 000 000</div>
              <div>24 000 001 — 50 000 000 &#8381; — 136 000 + 0,3% свыше 24 000 000</div>
              <div>50 000 001 — 100 000 000 &#8381; — 214 000 + 0,2% свыше 50 000 000</div>
              <div>свыше 100 000 000 &#8381; — 314 000 + 0,15% (макс. 900 000 &#8381;)</div>
            </div>
          </div>
        )}

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
          Расчёт носит информационный характер. Актуальные ставки — ст. 333.19 НК РФ (в ред. от 08.09.2024).
        </div>
      </div>
    </div>
  )
}
