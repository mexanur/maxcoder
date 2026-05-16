import React, { useState, useMemo } from 'react'
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

// Bucket a chat by its updatedAt timestamp.
// Returns 'today' | 'yesterday' | 'earlier'.
function bucket(ts) {
  if (!ts) return 'earlier'
  const t  = new Date(ts)
  const n  = new Date()
  const sameDay = t.toDateString() === n.toDateString()
  if (sameDay) return 'today'
  const y = new Date(n); y.setDate(n.getDate() - 1)
  if (t.toDateString() === y.toDateString()) return 'yesterday'
  return 'earlier'
}

function fmtTime(ts) {
  if (!ts) return ''
  const t = new Date(ts)
  const b = bucket(ts)
  if (b === 'today')     return t.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  if (b === 'yesterday') return 'Yesterday'
  return t.toLocaleDateString([], { month: 'short', day: 'numeric' })
}

export default function Sidebar() {
  const chats        = useStore(s => s.chats)
  const activeChatId = useStore(s => s.activeChatId)
  const newChat      = useStore(s => s.newChat)
  const deleteChat   = useStore(s => s.deleteChat)

  const [q, setQ] = useState('')

  // Apply search filter
  const filtered = useMemo(() => {
    if (!q.trim()) return chats
    const lower = q.toLowerCase()
    return chats.filter(c =>
      (c.title || '').toLowerCase().includes(lower) ||
      (c.messages || []).some(m =>
        typeof m?.content === 'string' && m.content.toLowerCase().includes(lower)
      )
    )
  }, [chats, q])

  // Bucket into Today / Yesterday / Earlier
  const groups = useMemo(() => {
    const g = { today: [], yesterday: [], earlier: [] }
    for (const c of filtered) {
      g[bucket(c.updatedAt || c.createdAt)].push(c)
    }
    return g
  }, [filtered])

  return (
    <div className="sidebar">

      {/* Header */}
      <div className="sidebar-header">
        <span className="section-label">Chats</span>
        <button
          onClick={newChat}
          title="New chat (⌘N)"
          style={{ background:'transparent', border:'none', cursor:'pointer', color:'var(--text-muted)', display:'flex', borderRadius:'var(--r-sm)', padding:4 }}
          onMouseEnter={e => { e.currentTarget.style.color='var(--text-primary)'; e.currentTarget.style.background='var(--chrome-secondary)' }}
          onMouseLeave={e => { e.currentTarget.style.color='var(--text-muted)'; e.currentTarget.style.background='transparent' }}
        >
          <Icon d={IC.plus} size={14} />
        </button>
      </div>

      {/* Search */}
      <div className="sidebar-search">
        <input
          className="sidebar-search-input"
          placeholder="Search chats…"
          value={q}
          onChange={e => setQ(e.target.value)}
          style={{
            // SVG search icon inline so we don't add an asset file
            backgroundImage: "url(\"data:image/svg+xml;charset=utf-8,%3Csvg width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%239fa5ad' stroke-width='2' stroke-linecap='round'%3E%3Ccircle cx='11' cy='11' r='8'/%3E%3Cpath d='m21 21-4.3-4.3'/%3E%3C/svg%3E\")",
            backgroundRepeat: 'no-repeat',
            backgroundPosition: '10px center',
          }}
        />
      </div>

      {/* Chat list */}
      <div style={{ flex:1, overflowY:'auto', padding:'4px 0' }}>
        {filtered.length === 0 && (
          <p style={{ fontSize:'var(--fs-sm)', color:'var(--text-dim)', textAlign:'center', padding:'24px 12px', lineHeight:1.6 }}>
            {q ? <>No chats match "{q}"</> : <>No chats yet.<br /><span style={{ color:'var(--accent)' }}>Click + to start.</span></>}
          </p>
        )}

        {groups.today.length > 0 && <div className="sidebar-section-label">Today</div>}
        {groups.today.map(chat => (
          <ChatRow key={chat.id} chat={chat} active={chat.id === activeChatId} onDelete={deleteChat} />
        ))}

        {groups.yesterday.length > 0 && <div className="sidebar-section-label">Yesterday</div>}
        {groups.yesterday.map(chat => (
          <ChatRow key={chat.id} chat={chat} active={chat.id === activeChatId} onDelete={deleteChat} />
        ))}

        {groups.earlier.length > 0 && <div className="sidebar-section-label">Earlier</div>}
        {groups.earlier.map(chat => (
          <ChatRow key={chat.id} chat={chat} active={chat.id === activeChatId} onDelete={deleteChat} />
        ))}
      </div>

      <style>{`.tree-item:hover .del-btn { opacity: 1 !important }`}</style>
    </div>
  )
}

// Single chat row — pulled out so we can reuse across Today/Yesterday/Earlier
function ChatRow({ chat, active, onDelete }) {
  const ts = fmtTime(chat.updatedAt || chat.createdAt)
  return (
    <div
      onClick={() => useStore.setState({ activeChatId: chat.id })}
      className={`tree-item ${active ? 'active' : ''}`}
      style={{ justifyContent:'space-between', paddingRight:6, height:34, alignItems:'center' }}
    >
      <div style={{ display:'flex', alignItems:'center', gap:8, overflow:'hidden', flex:1, minWidth:0 }}>
        <Icon d={IC.msg} size={12} />
        <div style={{ display:'flex', flexDirection:'column', overflow:'hidden', flex:1, minWidth:0, lineHeight:1.25 }}>
          <span style={{ overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap', fontSize:'var(--fs-base)' }}>
            {chat.title || 'New chat'}
          </span>
          {ts && (
            <span style={{ overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap',
                            fontSize:'var(--fs-xs)', color:'var(--text-dim)', fontFamily:'var(--type-mono)' }}>
              {ts}
            </span>
          )}
        </div>
      </div>
      <button
        onClick={e => { e.stopPropagation(); onDelete(chat.id) }}
        className="del-btn"
        title="Delete chat"
        style={{ opacity:0, background:'none', border:'none', cursor:'pointer', color:'var(--text-muted)', padding:2, borderRadius:'var(--r-sm)', display:'flex', flexShrink:0 }}
        onMouseEnter={e => { e.currentTarget.style.color='var(--danger)'; e.currentTarget.style.background='var(--danger-dim)' }}
        onMouseLeave={e => { e.currentTarget.style.color='var(--text-muted)'; e.currentTarget.style.background='transparent' }}
      >
        <Icon d={IC.trash} size={12} />
      </button>
    </div>
  )
}
