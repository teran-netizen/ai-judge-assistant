import { Routes, Route, Navigate } from 'react-router-dom'
import { useAuth } from './hooks/useAuth'

// Сохраняем UTM-метки при первом заходе (реклама ведёт на / с UTM, а /login без них)
;(() => {
  const p = new URLSearchParams(window.location.search)
  const keys = ['utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term']
  const found = keys.some(k => p.get(k))
  if (found) {
    keys.forEach(k => { const v = p.get(k); if (v) sessionStorage.setItem(k, v) })
  }
})()
import Layout from './components/Layout'
import LoginPage, { AiLawyerPage } from './pages/LoginPage'
import CasePage from './pages/CasePage'
import BillingPage from './pages/BillingPage'
import ProfilePage from './pages/ProfilePage'
import AdminPage from './pages/AdminPage'
import ReferralPage from "./pages/ReferralPage"
import AuthCallback from './pages/AuthCallback'
import CalculatorsPage from "./pages/CalculatorsPage"
import GosposhlinaCalc from "./pages/GosposhlinaCalc"
import Interest395Calc from "./pages/Interest395Calc"
import PeniCalc from "./pages/PeniCalc"
import NeustoikaCalc from "./pages/NeustoikaCalc"
import ZarplataCalc from "./pages/ZarplataCalc"
import GosposhlinaArbCalc from "./pages/GosposhlinaArbCalc"
import DaysCalc from "./pages/DaysCalc"
import LoanCalc from "./pages/LoanCalc"

function PrivateRoute({ children }) {
  const { user, loading } = useAuth()
  if (loading) return <div className="flex items-center justify-center h-screen"><Spinner /></div>
  if (!user) return <Navigate to="/login" />
  return children
}

function Spinner() {
  return (
    <div className="w-8 h-8 border-[3px] border-brand-200 border-t-brand-600 rounded-full animate-spin" />
  )
}

function AdminRoute({ children }) {
  const { user, loading } = useAuth()
  if (loading) return <div className="flex items-center justify-center h-screen"><Spinner /></div>
  if (!user?.is_admin) return <Navigate to="/" />
  return children
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/ии-юрист" element={<AiLawyerPage />} />
      <Route path="/ии-юрист/" element={<AiLawyerPage />} />
      <Route path="/kalkulyatory" element={<CalculatorsPage />} />
      <Route path="/kalkulyator-gosposhliny" element={<GosposhlinaCalc />} />
      <Route path="/kalkulyator-395-gk" element={<Interest395Calc />} />
      <Route path="/kalkulyator-peni" element={<PeniCalc />} />
      <Route path="/kalkulyator-neustoiki" element={<NeustoikaCalc />} />
      <Route path="/kalkulyator-zarplaty" element={<ZarplataCalc />} />
      <Route path="/kalkulyator-gosposhliny-arbitrazh" element={<GosposhlinaArbCalc />} />
      <Route path="/kalkulyator-dney" element={<DaysCalc />} />
      <Route path="/kalkulyator-zajma" element={<LoanCalc />} />
      <Route path="/auth/callback" element={<AuthCallback />} />
      <Route path="/auth/vk-callback" element={<AuthCallback />} />
      <Route element={<PrivateRoute><Layout /></PrivateRoute>}>
        <Route path="/" element={<CasePage />} />
        <Route path="/cases/new" element={<CasePage />} />
        <Route path="/cases/:id" element={<CasePage />} />
        <Route path="/billing" element={<BillingPage />} />
        <Route path="/referral" element={<ReferralPage />} />
        <Route path="/profile" element={<ProfilePage />} />
        <Route path="/admin" element={<AdminRoute><AdminPage /></AdminRoute>} />
      </Route>
      <Route path="*" element={<Navigate to="/" />} />
    </Routes>
  )
}
