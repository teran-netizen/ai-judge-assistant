import "./clientLog" // global error handlers → /api/client-log
import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import { AuthProvider } from './hooks/useAuth'
import { JudgeProvider } from './hooks/JudgeContext'
import './index.css'

// PWA — регистрация Service Worker
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker
      .getRegistrations()
      .then((regs) => regs.forEach((reg) => reg.unregister()))
      .catch(() => {})
  })
}

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <BrowserRouter>
      <AuthProvider><JudgeProvider>
        <App />
      </JudgeProvider></AuthProvider>
    </BrowserRouter>
  </React.StrictMode>
)
