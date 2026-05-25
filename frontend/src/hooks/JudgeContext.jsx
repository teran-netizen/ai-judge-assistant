import { createContext, useContext, useState, useEffect } from 'react'
import { getMyJudges } from '../api'
import { useAuth } from './useAuth'

const JudgeCtx = createContext(null)

export function JudgeProvider({ children }) {
  const { user } = useAuth()
  const [judges, setJudges] = useState([])
  const [activeJudgeId, setActiveJudgeId] = useState(null)

  useEffect(() => {
    if (!user) {
      setJudges([])
      setActiveJudgeId(null)
      return
    }
    getMyJudges().then(list => {
      setJudges(list || [])
      const saved = sessionStorage.getItem('activeJudgeId')
      if (saved && (list || []).some(j => j.judge_id === saved)) {
        setActiveJudgeId(saved)
      } else if ((list || []).length > 0) {
        setActiveJudgeId(list[0].judge_id)
        sessionStorage.setItem('activeJudgeId', list[0].judge_id)
      }
    }).catch(() => {})
  }, [user])

  const switchJudge = (judgeId) => {
    setActiveJudgeId(judgeId)
    if (judgeId) sessionStorage.setItem('activeJudgeId', judgeId)
    else sessionStorage.removeItem('activeJudgeId')
  }

  const activeJudge = judges.find(j => j.judge_id === activeJudgeId) || null

  const refreshJudges = () => {
    if (!user) return
    getMyJudges().then(setJudges).catch(() => {})
  }

  return (
    <JudgeCtx.Provider value={{ judges, activeJudgeId, activeJudge, switchJudge, refreshJudges }}>
      {children}
    </JudgeCtx.Provider>
  )
}

export function useJudge() {
  const ctx = useContext(JudgeCtx)
  if (!ctx) throw new Error('useJudge must be used within JudgeProvider')
  return ctx
}
