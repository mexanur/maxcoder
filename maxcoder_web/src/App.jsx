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

      {/* Status bar */}
      <div className="status-bar">
        <span className="status-item accent">
          <Icon d={ICONS.agent} size={11} />
          MaxCoder
        </span>
        <span className="status-sep" />
        <span className="status-item">
          {tab === 'chat' ? 'Chat' : 'Agent IDE'}
        </span>
        <div style={{ flex:1 }} />
        <span className="status-item">Local</span>
        <span className="status-sep" />
        <span className="status-item">{settings?.model || 'maxcoder'}</span>
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

          {[
            ['useWeb', 'Web Search'],
            ['useRag', 'RAG'],
            ['useMem', 'Memory'],
            ['useRew', 'Rewriter'],
            ['useCritic', 'Critic (slow)'],
            ['autoRun', 'Auto-run code'],
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
        </div>
      )}

    </div>
  )
}
