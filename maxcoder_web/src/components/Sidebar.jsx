import React from 'react'
import { useStore } from '../store'

function Icon({ d, size = 12 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth={1.75} strokeLinecap="round" strokeLinejoin="round">
      <path d={d} />
    </svg>
  )
}

const IC = {
  plus:    'M12 4v16m8-8H4',
  trash:   'M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16',
  msg:     'M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z',
}

export default function Sidebar() {
  const chats        = useStore(s => s.chats)
  const activeChatId = useStore(s => s.activeChatId)
  const newChat      = useStore(s => s.newChat)
  const deleteChat   = useStore(s => s.deleteChat)

  return (
    <div className="sidebar">

      {/* Header */}
      <div className="sidebar-header">
        <span className="section-label">Chats</span>
        <button
          onClick={newChat}
          title="New chat"
          style={{ background:'transparent', border:'none', cursor:'pointer', color:'var(--text-muted)', display:'flex', borderRadius:3, padding:4, transition:'color 0.12s, background 0.12s' }}
          onMouseEnter={e => { e.currentTarget.style.color='var(--text-primary)'; e.currentTarget.style.background='var(--btn-hover)' }}
          onMouseLeave={e => { e.currentTarget.style.color='var(--text-muted)'; e.currentTarget.style.background='transparent' }}
        >
          <Icon d={IC.plus} size={13} />
        </button>
      </div>

      {/* Chat list */}
      <div style={{ flex:1, overflowY:'auto', padding:'4px 0' }}>
        {chats.length === 0 && (
          <p style={{ fontSize:11, color:'var(--text-dim)', textAlign:'center', padding:'20px 12px', lineHeight:1.6 }}>
            No chats yet.<br />
            <span style={{ color:'var(--accent)' }}>Click + to start.</span>
          </p>
        )}
        {chats.map(chat => (
          <div
            key={chat.id}
            onClick={() => useStore.setState({ activeChatId: chat.id })}
            className={`tree-item ${activeChatId === chat.id ? 'active' : ''}`}
            style={{ justifyContent:'space-between', paddingRight:6, height:28 }}
          >
            <div style={{ display:'flex', alignItems:'center', gap:6, overflow:'hidden', flex:1 }}>
              <Icon d={IC.msg} size={11} />
              <span style={{ overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap', fontSize:12 }}>
                {chat.title || 'New chat'}
              </span>
            </div>
            <button
              onClick={e => { e.stopPropagation(); deleteChat(chat.id) }}
              className="del-btn"
              style={{ opacity:0, background:'none', border:'none', cursor:'pointer', color:'var(--text-muted)', padding:'1px', borderRadius:3, display:'flex', flexShrink:0 }}
              onMouseEnter={e => e.currentTarget.style.color='var(--red)'}
              onMouseLeave={e => e.currentTarget.style.color='var(--text-muted)'}
            >
              <Icon d={IC.trash} size={11} />
            </button>
          </div>
        ))}
      </div>

      <style>{`.tree-item:hover .del-btn { opacity: 1 !important }`}</style>
    </div>
  )
}
