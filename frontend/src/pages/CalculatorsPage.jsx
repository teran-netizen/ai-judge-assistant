import { Link } from 'react-router-dom'
import { Calculator, Scale, Percent, Clock, Banknote, CalendarDays, Landmark, HandCoins } from 'lucide-react'

const calcs = [
  { to: '/kalkulyator-gosposhliny', icon: Scale, title: 'Госпошлина', desc: 'Расчёт госпошлины в суд общей юрисдикции' },
  { to: '/kalkulyator-gosposhliny-arbitrazh', icon: Landmark, title: 'Госпошлина (арбитраж)', desc: 'Расчёт госпошлины в арбитражный суд' },
  { to: '/kalkulyator-peni', icon: Percent, title: 'Пени', desc: 'Расчёт пени за просрочку' },
  { to: '/kalkulyator-neustoiki', icon: Banknote, title: 'Неустойка', desc: 'Расчёт неустойки по договору' },
  { to: '/kalkulyator-395-gk', icon: HandCoins, title: 'Проценты по ст. 395 ГК', desc: 'Проценты за пользование чужими денежными средствами' },
  { to: '/kalkulyator-zarplaty', icon: Calculator, title: 'Зарплата', desc: 'Расчёт задолженности по заработной плате' },
  { to: '/kalkulyator-dney', icon: CalendarDays, title: 'Дни', desc: 'Расчёт количества дней между датами' },
  { to: '/kalkulyator-zajma', icon: Clock, title: 'Займ', desc: 'Расчёт процентов по договору займа' },
]

export default function CalculatorsPage() {
  return (
    <div className="min-h-screen bg-gradient-to-b from-surface-50 to-white">
      <div className="max-w-4xl mx-auto px-4 py-12">
        <div className="text-center mb-10">
          <h1 className="text-3xl font-display font-bold text-surface-900 mb-3">Судебные калькуляторы</h1>
          <p className="text-surface-500 text-lg">Бесплатные онлайн-калькуляторы для судей и юристов</p>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {calcs.map(({ to, icon: Icon, title, desc }) => (
            <Link
              key={to}
              to={to}
              className="group flex items-start gap-4 p-5 bg-white rounded-xl border border-surface-200 hover:border-brand-300 hover:shadow-md transition-all"
            >
              <div className="w-11 h-11 rounded-lg bg-brand-50 group-hover:bg-brand-100 flex items-center justify-center shrink-0 transition-colors">
                <Icon size={22} className="text-brand-600" />
              </div>
              <div>
                <div className="font-semibold text-surface-900 group-hover:text-brand-700 transition-colors">{title}</div>
                <div className="text-sm text-surface-500 mt-0.5">{desc}</div>
              </div>
            </Link>
          ))}
        </div>

        <div className="text-center mt-10">
          <Link to="/login" className="text-brand-600 hover:text-brand-700 text-sm font-medium">
            AI Помощник Судьи — генерация судебных решений
          </Link>
        </div>
      </div>
    </div>
  )
}
