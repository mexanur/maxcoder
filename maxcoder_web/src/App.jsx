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
  const [tab, setTab] = useState('chat')

  useEffect(() => {
    if (chats.length === 0) newChat()
  }, [])

  return (
    <div style={{ display:'flex', flexDirection:'column', height:'100vh', width:'100vw', overflow:'hidden', background:'var(--content-bg)', color:'var(--text-primary)' }}>

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
            <button className="activity-btn" title="Settings (use sidebar)">
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
        <span className="status-item">● Local</span>
        <span className="status-sep" />
        <span className="status-item">{settings?.model || 'maxcoder'}</span>
      </div>

    </div>
  )
}
