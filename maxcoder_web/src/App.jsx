import React, { useEffect, useState } from 'react'
import Sidebar   from './components/Sidebar'
import ChatArea  from './components/ChatArea'
import AgentPage from './components/AgentPage'
import { useStore } from './store'

function Icon({ d, size = 16 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth={1.75} strokeLinecap="round" strokeLinejoin="round">
      <path d={d} />
    </svg>
  )
}

const ICONS = {
  chat:    'M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z',
  agent:   'M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4',
  settings:'M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065zM15 12a3 3 0 11-6 0 3 3 0 016 0z',
  sun:     'M12 3v2m0 14v2M5.6 5.6l1.4 1.4m10 10l1.4 1.4M3 12h2m14 0h2M5.6 18.4l1.4-1.4m10-10l1.4-1.4M16 12a4 4 0 11-8 0 4 4 0 018 0z',
  moon:    'M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z',
}

export default function App() {
  const newChat  = useStore(s => s.newChat)
  const chats    = useStore(s => s.chats)
  const settings = useStore(s => s.settings)
  const setSettings = useStore(s => s.setSettings)
  const [tab, setTab] = useState('chat')
  const [showQuickSettings, setShowQuickSettings] = useState(false)
  const [theme, setTheme] = useState(() => localStorage.getItem('maxcoder-theme') || 'dark')

  useEffect(() => {
    if (chats.length === 0) newChat()
  }, [])

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
    localStorage.setItem('maxcoder-theme', theme)
  }, [theme])

  // ⌘⇧L / Ctrl-Shift-L toggles theme — surfaced in welcome screen tips.
  useEffect(() => {
    const onKey = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.shiftKey && (e.key === 'L' || e.key === 'l')) {
        e.preventDefault()
        setTheme(t => (t === 'dark' ? 'light' : 'dark'))
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  return (
    <div data-theme={theme} style={{ display:'flex', flexDirection:'column', height:'100vh', width:'100vw', overflow:'hidden', background:'var(--content-bg)', color:'var(--text-primary)', position:'relative' }}>

      {/* Main row: activity bar + content */}
      <div style={{ display:'flex', flex:1, overflow:'hidden' }}>

        {/* Activity bar */}
        <div className="activity-bar">
          <div style={{ display:'flex', flexDirection:'column', gap:2, flex:1 }}>
            <button
              className={`activity-btn ${tab === 'chat' ? 'active' : ''}`}
              onClick={() => setTab('chat')}
              title="Chat"
            >
              <Icon d={ICONS.chat} />
            </button>
            <button
              className={`activity-btn ${tab === 'agent' ? 'active' : ''}`}
              onClick={() => setTab('agent')}
              title="Agent IDE"
            >
              <Icon d={ICONS.agent} />
            </button>
          </div>
          <div style={{ display:'flex', flexDirection:'column', gap:2 }}>
            <button
              className={`activity-btn ${showQuickSettings ? 'active' : ''}`}
              title="Settings"
              onClick={() => setShowQuickSettings(v => !v)}
            >
              <Icon d={ICONS.settings} />
            </button>
          </div>
        </div>

        {/* Content area */}
        <div style={{ flex:1, display:'flex', overflow:'hidden', minWidth:0 }}>
          {tab === 'chat' ? (
            <div style={{ display:'flex', height:'100%', width:'100%' }}>
              <Sidebar />
              <ChatArea />
            </div>
          ) : (
            <AgentPage />
          )}
        </div>
      </div>

      {showQuickSettings && (
        <div
          className="quick-settings-panel"
          style={{
            position:'absolute',
            left:56,
            bottom:34,
            width:260,
            background:'var(--chrome-deep)',
            border:'1px solid var(--border)',
            borderRadius:6,
            boxShadow:'var(--shadow-lg)',
            padding:12,
            display:'flex',
            flexDirection:'column',
            gap:10,
            zIndex:40,
          }}
        >
          <div style={{ fontSize:10, color:'var(--text-muted)', letterSpacing:'0.07em', textTransform:'uppercase', fontWeight:600 }}>
            Settings
          </div>

          <div>
            <div style={{ fontSize:10, color:'var(--text-muted)', marginBottom:6, letterSpacing:'0.04em', textTransform:'uppercase' }}>
              Theme
            </div>
            <div className="theme-toggle" role="group" aria-label="Theme">
              {['dark', 'light'].map(mode => (
                <button
                  key={mode}
                  type="button"
                  className={theme === mode ? 'active' : ''}
                  onClick={() => setTheme(mode)}
                >
                  {mode === 'dark' ? 'Dark' : 'Light'}
                </button>
              ))}
            </div>
          </div>

          <div>
            <div style={{ fontSize:10, color:'var(--text-muted)', marginBottom:4, letterSpacing:'0.04em', textTransform:'uppercase' }}>
              Model
            </div>
            <select
              value={settings.model}
              onChange={e => setSettings({ model: e.target.value })}
              style={{
                width:'100%',
                background:'var(--chrome-secondary)',
                border:'1px solid var(--border)',
                borderRadius:4,
                padding:'6px 8px',
                fontSize:11,
                color:'var(--text-primary)',
                outline:'none',
                cursor:'pointer',
              }}
            >
              <option value="maxcoder-fast">maxcoder-fast (3B)</option>
              <option value="maxcoder">maxcoder (7B)</option>
            </select>
          </div>

          {/* Runtime toggles (Web / RAG / Memory / Auto-run) live in the
              input-bar chips. The popover owns STRUCTURAL settings only. */}
          <div style={{ fontSize:10, color:'var(--text-muted)', marginTop:4, letterSpacing:'0.04em', textTransform:'uppercase' }}>
            Advanced
          </div>
          {[
            ['useRew', 'Query rewriter'],
            ['useCritic', 'Critic (slow)'],
            ['useReasoning', 'MaxThink (deep reasoning)'],
          ].map(([key, label]) => (
            <label key={key} style={{ display:'flex', alignItems:'center', justifyContent:'space-between', fontSize:11, color:'var(--text-secondary)', cursor:'pointer' }}>
              <span style={{ color: settings[key] ? 'var(--text-primary)' : 'var(--text-secondary)' }}>{label}</span>
              <button
                type="button"
                onClick={() => setSettings({ [key]: !settings[key] })}
                style={{
                  width:30,
                  height:16,
                  borderRadius:8,
                  border:'1px solid var(--border)',
                  background: settings[key] ? 'var(--accent)' : 'var(--chrome-secondary)',
                  position:'relative',
                  cursor:'pointer',
                  transition:'all 0.16s ease',
                  padding:0,
                }}
              >
                <span
                  style={{
                    position:'absolute',
                    top:2,
                    left: settings[key] ? 16 : 2,
                    width:10,
                    height:10,
                    borderRadius:'50%',
                    background:'#fff',
                    transition:'left 0.16s ease',
                  }}
                />
              </button>
            </label>
          ))}

          {/* ── Chat backup / restore ───────────────────────────────────── */}
          <BackupPanel />
        </div>
      )}

    </div>
  )
}


// ── Backup & restore — saves chats/projects/settings to disk on the server ──
function BackupPanel() {
  const [busy, setBusy]       = React.useState(false)
  const [status, setStatus]   = React.useState('')
  const [backups, setBackups] = React.useState([])
  const [showList, setShowList] = React.useState(false)

  const collectState = () => {
    // Pull both persisted stores from localStorage
    try {
      return {
        version:   1,
        timestamp: new Date().toISOString(),
        chat:      JSON.parse(localStorage.getItem('maxcoder-store')       || 'null'),
        agent:     JSON.parse(localStorage.getItem('maxcoder-agent-store') || 'null'),
      }
    } catch { return null }
  }

  const doBackup = async () => {
    setBusy(true)
    try {
      const payload = collectState()
      const name    = `manual_${new Date().toISOString().slice(0,10)}`
      const r = await fetch('/api/chat/backup', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ name, payload }),
      })
      const d = await r.json()
      setStatus(d.ok ? `Saved: ${d.file}` : 'Failed')
      setTimeout(() => setStatus(''), 3500)
    } catch (e) { setStatus(`Failed: ${e.message}`); setTimeout(() => setStatus(''), 3500) }
    finally     { setBusy(false) }
  }

  const downloadJson = () => {
    const payload = collectState()
    if (!payload) return
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
    const url  = URL.createObjectURL(blob)
    const a    = document.createElement('a')
    a.href     = url
    a.download = `maxcoder_backup_${new Date().toISOString().slice(0,10)}.json`
    a.click()
    URL.revokeObjectURL(url)
  }

  const loadList = async () => {
    setBusy(true)
    try {
      const r = await fetch('/api/chat/backup/list')
      const d = await r.json()
      setBackups(d.backups || [])
      setShowList(true)
    } catch (e) { setStatus(`Failed: ${e.message}`) }
    finally     { setBusy(false) }
  }

  const restoreBackup = async (fname) => {
    if (!confirm(`Restore "${fname}"? This will REPLACE your current chats and projects.`)) return
    setBusy(true)
    try {
      const r = await fetch(`/api/chat/backup/${encodeURIComponent(fname)}`)
      const d = await r.json()
      if (d.chat)  localStorage.setItem('maxcoder-store',       JSON.stringify(d.chat))
      if (d.agent) localStorage.setItem('maxcoder-agent-store', JSON.stringify(d.agent))
      setStatus('Restored — reloading...')
      setTimeout(() => window.location.reload(), 800)
    } catch (e) { setStatus(`Failed: ${e.message}`); setBusy(false) }
  }

  const restoreFromFile = async (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    if (!confirm('Restore from file? This will REPLACE your current chats and projects.')) return
    try {
      const txt = await file.text()
      const d   = JSON.parse(txt)
      if (d.chat)  localStorage.setItem('maxcoder-store',       JSON.stringify(d.chat))
      if (d.agent) localStorage.setItem('maxcoder-agent-store', JSON.stringify(d.agent))
      setStatus('Restored — reloading...')
      setTimeout(() => window.location.reload(), 800)
    } catch (err) { setStatus(`Bad file: ${err.message}`) }
  }

  const btnStyle = {
    fontSize: 10, padding: '4px 8px', borderRadius: 3,
    background: 'var(--chrome-secondary)', color: 'var(--text-primary)',
    border: '1px solid var(--border)', cursor: busy ? 'wait' : 'pointer',
    fontFamily: 'inherit', flex: 1, opacity: busy ? 0.6 : 1,
  }

  return (
    <div style={{ marginTop: 14, paddingTop: 12, borderTop: '1px solid var(--border)' }}>
      <div style={{ fontSize: 10, color: 'var(--text-secondary)', marginBottom: 6,
                     letterSpacing: 0.3, textTransform: 'uppercase' }}>
        Backup & restore
      </div>
      <div style={{ display: 'flex', gap: 4, marginBottom: 4 }}>
        <button onClick={doBackup}    disabled={busy} style={btnStyle}>Save to server</button>
        <button onClick={downloadJson} disabled={busy} style={btnStyle}>Download</button>
      </div>
      <div style={{ display: 'flex', gap: 4 }}>
        <button onClick={loadList} disabled={busy} style={btnStyle}>List backups</button>
        <label style={{ ...btnStyle, textAlign: 'center', display: 'inline-block' }}>
          Import file
          <input type="file" accept=".json" style={{ display: 'none' }}
                 onChange={restoreFromFile} />
        </label>
      </div>
      {status && (
        <div style={{ marginTop: 6, fontSize: 10, color: 'var(--accent)' }}>{status}</div>
      )}

      {showList && (
        <div style={{ marginTop: 8, maxHeight: 200, overflowY: 'auto',
                       border: '1px solid var(--border)', borderRadius: 3,
                       padding: 4, background: 'var(--surface-low)' }}>
          {backups.length === 0 && (
            <div style={{ fontSize: 10, color: 'var(--text-dim)', padding: 4 }}>
              No backups on server yet.
            </div>
          )}
          {backups.map(b => (
            <div key={b.file}
                 style={{ display: 'flex', alignItems: 'center', gap: 4,
                          padding: '3px 4px', fontSize: 10, color: 'var(--text-secondary)' }}>
              <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis',
                              whiteSpace: 'nowrap' }} title={b.file}>
                {b.file}
              </span>
              <button onClick={() => restoreBackup(b.file)}
                      style={{ fontSize: 9, padding: '2px 6px',
                               background: 'var(--accent)', color: 'white',
                               border: 'none', borderRadius: 2, cursor: 'pointer',
                               fontFamily: 'inherit' }}>
                Restore
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
