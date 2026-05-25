import { useState, useEffect } from 'react'
import { useAuth } from '../hooks/useAuth'
import { User, Edit3, Check, UserPlus, X, Users, Unlink, Copy, KeyRound } from 'lucide-react'
import api, { getMyAssistants, addAssistant, removeAssistant, getMyJudges, detachFromJudge, createAssistantInvite, acceptAssistantInvite } from '../api'
import { useJudge } from '../hooks/JudgeContext'

export default function ProfilePage() {
  const { user, refreshUser } = useAuth()
  const { refreshJudges, switchJudge, activeJudge, activeJudgeId } = useJudge()
  const [editName, setEditName] = useState(false)
  const [nameVal, setNameVal] = useState(user?.name || '')
  const [editEmail, setEditEmail] = useState(false)
  const [emailVal, setEmailVal] = useState(user?.email || '')
  const [editNick, setEditNick] = useState(false)
  const [nickname, setNickname] = useState(user?.nickname || '')
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState('')
  const [assistants, setAssistants] = useState([])
  const [judges, setJudges] = useState([])
  const [assistantMsg, setAssistantMsg] = useState('')
  // Invite
  const [inviteCode, setInviteCode] = useState(null)
  const [creatingInvite, setCreatingInvite] = useState(false)
  const [copied, setCopied] = useState(false)
  // Accept invite
  const [acceptCode, setAcceptCode] = useState('')
  const [accepting, setAccepting] = useState(false)
  const [acceptMsg, setAcceptMsg] = useState('')

  useEffect(() => {
    getMyAssistants().then(setAssistants).catch(() => {})
    getMyJudges().then(setJudges).catch(() => {})
  }, [])

  const saveName = async () => {
    if (!nameVal.trim()) return
    setSaving(true); setMsg('')
    try {
      await api.updateProfile({ name: nameVal.trim() })
      await refreshUser(); setEditName(false)
      setMsg('Сохранено'); setTimeout(() => setMsg(''), 2000)
    } catch (e) { setMsg(e.message) } finally { setSaving(false) }
  }

  const saveEmail = async () => {
    setSaving(true); setMsg('')
    try {
      await api.updateProfile({ email: emailVal.trim() })
      await refreshUser(); setEditEmail(false)
      setMsg('Сохранено'); setTimeout(() => setMsg(''), 2000)
    } catch (e) { setMsg(e.message) } finally { setSaving(false) }
  }

  const saveNick = async () => {
    if (!nickname.trim() || nickname.trim().length < 2) return
    setSaving(true); setMsg('')
    try {
      await api.setNickname(nickname.trim())
      await refreshUser(); setEditNick(false)
      setMsg('Сохранено'); setTimeout(() => setMsg(''), 2000)
    } catch (e) { setMsg(e.message) } finally { setSaving(false) }
  }

  const handleCreateInvite = async () => {
    setCreatingInvite(true)
    try {
      const res = await createAssistantInvite()
      setInviteCode(res.code)
      setCopied(false)
    } catch (e) { setAssistantMsg(e.message) }
    finally { setCreatingInvite(false) }
  }

  const handleCopyCode = () => {
    if (inviteCode) {
      navigator.clipboard.writeText(inviteCode).then(() => {
        setCopied(true); setTimeout(() => setCopied(false), 2000)
      })
    }
  }

  const handleRemoveAssistant = async (aid) => {
    try { await removeAssistant(aid); setAssistants(prev => prev.filter(a => a.assistant_id !== aid)) }
    catch (e) { setAssistantMsg(e.message) }
  }

  const handleAcceptInvite = async () => {
    if (!acceptCode.trim()) return
    setAccepting(true); setAcceptMsg('')
    try {
      const res = await acceptAssistantInvite(acceptCode.trim())
      setAcceptCode('')
      const updatedJudges = await getMyJudges()
      setJudges(updatedJudges)
      refreshJudges()
      // Auto-switch to judge's cabinet
      if (res.judge_id) switchJudge(res.judge_id)
      setAcceptMsg(`Вы привязаны к судье: ${res.judge_name}`)
      setTimeout(() => setAcceptMsg(''), 5000)
    } catch (e) { setAcceptMsg(e.message) }
    finally { setAccepting(false) }
  }

  const handleDetachFromJudge = async (judgeId) => {
    try { await detachFromJudge(judgeId); setJudges(prev => prev.filter(j => j.judge_id !== judgeId)); refreshJudges(); switchJudge(null) }
    catch (e) { setAcceptMsg(e.message) }
  }

  return (
    <div className="flex-1 overflow-y-auto" style={{ scrollbarGutter: 'stable' }}>
    <div className="max-w-3xl mx-auto px-6 py-6 sm:py-8">
    <div className="animate-in max-w-lg">
      <h1 className="text-2xl font-display font-bold mb-6">Профиль</h1>

      <div className="card p-6 mb-4">
        <div className="flex items-center gap-4 mb-6">
          <div className="w-14 h-14 rounded-xl bg-brand-100 flex items-center justify-center">
            <User size={28} className="text-brand-600" />
          </div>
          <div className="flex-1">
            <div className="text-xs text-surface-400 mb-0.5">ID: {user?.display_id}</div>
          </div>
        </div>

        <div className="mb-4">
          <label className="text-sm font-medium text-surface-600 mb-1.5 block">Имя</label>
          {editName ? (
            <div className="flex gap-2">
              <input value={nameVal} onChange={e => setNameVal(e.target.value)} maxLength={200} className="input flex-1" autoFocus placeholder="Ваше имя" />
              <button onClick={saveName} disabled={saving} className="btn-primary px-3"><Check size={16} /></button>
              <button onClick={() => setEditName(false)} className="px-3 text-surface-400 hover:text-surface-600"><X size={16} /></button>
            </div>
          ) : (
            <div className="flex items-center gap-2">
              <span className="text-sm">{user?.name || '\u2014'}</span>
              <button onClick={() => { setNameVal(user?.name || ''); setEditName(true) }} className="text-brand-600 hover:text-brand-700"><Edit3 size={14} /></button>
            </div>
          )}
        </div>

        <div className="mb-4">
          <label className="text-sm font-medium text-surface-600 mb-1.5 block">Email для писем</label>
          {editEmail ? (
            <div className="flex gap-2">
              <input type="email" value={emailVal} onChange={e => setEmailVal(e.target.value)} maxLength={255} className="input flex-1" autoFocus placeholder="email@example.com" />
              <button onClick={saveEmail} disabled={saving} className="btn-primary px-3"><Check size={16} /></button>
              <button onClick={() => setEditEmail(false)} className="px-3 text-surface-400 hover:text-surface-600"><X size={16} /></button>
            </div>
          ) : (
            <div className="flex items-center gap-2">
              <span className="text-sm">{user?.email || '\u2014'}</span>
              <button onClick={() => { setEmailVal(user?.email || ''); setEditEmail(true) }} className="text-brand-600 hover:text-brand-700"><Edit3 size={14} /></button>
            </div>
          )}
        </div>

        
      </div>

      {/* Judge section: manage assistants (hidden if user is an assistant of any judge) */}
      {judges.length === 0 && (
      <div className="card p-5 mb-4">
        <h3 className="font-medium text-sm text-surface-600 mb-3 flex items-center gap-2"><Users size={16} /> Мои помощники</h3>

        {assistants.length > 0 && (
          <div className="space-y-2 mb-3">
            {assistants.map(a => (
              <div key={a.assistant_id} className="flex items-center justify-between bg-surface-50 rounded-lg px-3 py-2">
                <div>
                  <span className="font-medium text-sm">{a.name || 'Пользователь'}</span>
                  <span className="text-xs text-surface-400 ml-2">ID: {a.display_id}</span>
                </div>
                <button onClick={() => handleRemoveAssistant(a.assistant_id)} className="text-red-400 hover:text-red-600 p-1" title="Удалить"><X size={16} /></button>
              </div>
            ))}
          </div>
        )}

        {/* Create invite */}
        {inviteCode ? (
          <div className="bg-brand-50 rounded-lg p-4 text-center">
            <div className="text-xs text-surface-500 mb-1">Код приглашения (24 часа)</div>
            <div className="font-mono text-2xl font-bold text-brand-700 tracking-widest mb-2">{inviteCode}</div>
            <button onClick={handleCopyCode} className="text-sm text-brand-600 hover:text-brand-700 flex items-center gap-1 mx-auto">
              <Copy size={14} /> {copied ? 'Скопировано' : 'Копировать'}
            </button>
            <p className="text-xs text-surface-400 mt-2">Передайте код помощнику</p>
          </div>
        ) : (
          <button onClick={handleCreateInvite} disabled={creatingInvite} className="btn-primary w-full text-sm flex items-center justify-center gap-2">
            <UserPlus size={16} /> Создать приглашение для помощника
          </button>
        )}
        {assistantMsg && <p className="text-xs mt-2 text-red-500">{assistantMsg}</p>}
      </div>
      )}

      {/* Assistant section: accept invite */}
      <div className="card p-5 mb-4">
        <h3 className="font-medium text-sm text-surface-600 mb-3 flex items-center gap-2"><KeyRound size={16} /> Принять приглашение судьи</h3>

        {judges.length > 0 && (
          <div className="space-y-2 mb-3">
            {judges.map(j => (
              <div key={j.judge_id} className="flex items-center justify-between bg-surface-50 rounded-lg px-3 py-2">
                <div>
                  <span className="font-medium text-sm">{j.name || 'Судья'}</span>
                  {j.nickname && <span className="text-xs text-surface-400 ml-2">@{j.nickname}</span>}
                </div>
                <button onClick={() => handleDetachFromJudge(j.judge_id)} className="text-red-400 hover:text-red-600 text-xs px-2 py-1 rounded hover:bg-red-50">Отвязаться</button>
              </div>
            ))}
          </div>
        )}

        <div className="flex gap-2">
          <input value={acceptCode} onChange={e => setAcceptCode(e.target.value.toUpperCase())} placeholder="Введите код от судьи" className="input flex-1 text-sm font-mono tracking-wider text-center" maxLength={6} onKeyDown={e => e.key === 'Enter' && handleAcceptInvite()} />
          <button onClick={handleAcceptInvite} disabled={accepting || !acceptCode.trim()} className="btn-primary px-4 text-sm">Принять</button>
        </div>
        {acceptMsg && <p className={`text-xs mt-2 ${acceptMsg.startsWith('Вы привязаны') ? 'text-emerald-600' : 'text-red-500'}`}>{acceptMsg}</p>}
      </div>

      {/* Stats */}
      <div className="card p-5">
        <h3 className="font-medium text-sm text-surface-600 mb-3">Статистика</h3>
        {activeJudge ? (
          <div className="text-center">
            {(() => {
              const sub = activeJudge.subscription_until && new Date(activeJudge.subscription_until) > new Date()
              if (sub) {
                const dt = new Date(activeJudge.subscription_until).toLocaleDateString('ru', { day: '2-digit', month: '2-digit', year: 'numeric' })
                return <div><div className="text-xl font-bold text-violet-600">∞</div><div className="text-xs text-surface-400">Безлимит до {dt}</div></div>
              }
              const total = (activeJudge.free_cases_left || 0) + (activeJudge.paid_cases_left || 0)
              return <div><div className="text-xl font-bold">{total}</div><div className="text-xs text-surface-400">Дел (через судью)</div></div>
            })()}
          </div>
        ) : (
          <div className="grid grid-cols-3 gap-4 text-center">
            <div><div className="text-xl font-bold">{(user?.free_cases_left || 0) + (user?.paid_cases_left || 0)}</div><div className="text-xs text-surface-400">Дел</div></div>
            <div><div className="text-xl font-bold">{user?.free_cases_left || 0}</div><div className="text-xs text-surface-400">Бесплатных дел</div></div>
            <div><div className="text-xl font-bold">{((user?.balance_kopecks || 0) / 100).toFixed(0)}</div><div className="text-xs text-surface-400">Бонусы ₽</div></div>
          </div>
        )}
      </div>

      <p className="text-xs text-surface-400 mt-6 text-center">Зарегистрирован: {user?.created_at ? new Date(user.created_at).toLocaleDateString('ru') : '\u2014'}</p>
    </div>
    </div>
    </div>
  )
}
