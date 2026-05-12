import React, { useEffect, useState } from 'react'
import Sidebar    from './components/Sidebar'
import ChatArea   from './components/ChatArea'
import AgentPage  from './components/AgentPage'
import { useStore } from './store'

export default function App() {
  const newChat = useStore(s => s.newChat)
  const chats   = useStore(s => s.chats)
  const [tab, setTab] = useState('chat') // 'chat' | 'agent'

  useEffect(() => {
    if (chats.length === 0) newChat()
  }, [])

  return (
    <div className="flex flex-col h-screen bg-bg text-text overflow-hidden">
      {/* Top tab bar */}
      <div className="flex items-center gap-1 px-4 py-2 border-b border-border bg-surface flex-shrink-0">
        <span className="text-sm font-bold text-accent mr-4">MaxCoder</span>
        <button
          onClick={() => setTab('chat')}
          className={`text-xs px-4 py-1.5 rounded-lg font-medium transition-colors
            ${tab === 'chat' ? 'bg-accent/20 text-accent' : 'text-muted hover:text-text'}`}
        >
          💬 Chat
        </button>
        <button
          onClick={() => setTab('agent')}
          className={`text-xs px-4 py-1.5 rounded-lg font-medium transition-colors
            ${tab === 'agent' ? 'bg-accent/20 text-accent' : 'text-muted hover:text-text'}`}
        >
          🤖 Agent IDE
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-hidden">
        {tab === 'chat' ? (
          <div className="flex h-full">
            <Sidebar />
            <ChatArea />
          </div>
        ) : (
          <AgentPage />
        )}
      </div>
    </div>
  )
}
