import React, { useEffect, useState } from 'react'
import Sidebar   from './components/Sidebar'
import ChatArea  from './components/ChatArea'
import AgentPage from './components/AgentPage'
import { useStore } from './store'

// ── Icons ─────────────────────────────────────────────────────────────────────
const ChatIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8}
       strokeLinecap="round" strokeLinejoin="round" className="w-3.5 h-3.5">
    <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/>
  </svg>
)

const AgentIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8}
       strokeLinecap="round" strokeLinejoin="round" className="w-3.5 h-3.5">
    <rect x="3" y="11" width="18" height="10" rx="2"/>
    <path d="M12 2a3 3 0 013 3v6H9V5a3 3 0 013-3z"/>
    <path d="M9 17h.01M15 17h.01"/>
  </svg>
)

export default function App() {
  const newChat = useStore(s => s.newChat)
  const chats   = useStore(s => s.chats)
  const [tab, setTab] = useState('chat')

  useEffect(() => {
    if (chats.length === 0) newChat()
  }, [])

  return (
    <div className="flex flex-col h-screen w-screen overflow-hidden bg-bg text-text">

      {/* ── Top nav bar ─────────────────────────────────────────────────── */}
      <header className="topbar">
        <span className="topbar-logo">MaxCoder</span>

        <div className="w-px h-4 bg-border mx-1 flex-shrink-0" />

        <button
          onClick={() => setTab('chat')}
          className={`nav-tab ${tab === 'chat' ? 'active' : ''}`}
        >
          <ChatIcon />
          Chat
        </button>

        <button
          onClick={() => setTab('agent')}
          className={`nav-tab ${tab === 'agent' ? 'active' : ''}`}
        >
          <AgentIcon />
          Agent IDE
        </button>
      </header>

      {/* ── Content ─────────────────────────────────────────────────────── */}
      <main className="flex-1 overflow-hidden">
        {tab === 'chat' ? (
          <div className="flex h-full">
            <Sidebar />
            <ChatArea />
          </div>
        ) : (
          <AgentPage />
        )}
      </main>

    </div>
  )
}