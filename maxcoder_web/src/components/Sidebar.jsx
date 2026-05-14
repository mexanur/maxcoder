import React, { useState } from 'react'
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
  sliders: 'M4 6h16M4 12h16M4 18h16M10 6v12M6 12v6M14 6v6',
  globe:   'M12 2a10 10 0 100 20A10 10 0 0012 2zm0 0c2.5 2.5 4 6 4 10s-1.5 7.5-4 10m0-20C9.5 4.5 8 8 8 12s1.5 7.5 4 10M2 12h20',
  db:      'M4 7c0-1.657 3.582-3 8-3s8 1.343 8 3v10c0 1.657-3.582 3-8 3s-8-1.343-8-3V7zm0 5c0 1.657 3.582 3 8 3s8-1.343 8-3',
  brain:   'M9 3H5a2 2 0 00-2 2v4m6-6h10a2 2 0 012 2v4M9 3v18m0 0h10a2 2 0 002-2V9M9 21H5a2 2 0 01-2-2V9m0 0h18',
  wand:    'M15 4V2m0 2v2m0-2h-2m2 0h2M5 8V6m0 2v2m0-2H3m2 0h2m8 10l-6-6m6 6L7 8',
  search:  'M21 21l-4.35-4.35M17 11A6 6 0 115 11a6 6 0 0112 0z',
  play:    'M5 3l14 9-14 9V3z',
}

export default function Sidebar() {
  const chats        = useStore(s => s.chats)
  const activeChatId = useStore(s => s.activeChatId)
  const newChat      = useStore(s => s.newChat)
  const deleteChat   = useStore(s => s.deleteChat)
  const settings     = useStore(s => s.settings)
  const setSettings  = useStore(s => s.setSettings)

  const [showSettings, setShowSettings] = useState(false)
  const toggle = (key) => setSettings({ [key]: !settings[key] })

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

      {/* Settings panel (collapsible) */}
      {showSettings && (
        <div style={{ borderTop:'1px solid var(--border)', padding:'10px 12px 8px', display:'flex', flexDirection:'column', gap:10, background:'var(--chrome-deep)' }}>
          <span className="section-label">Settings</span>

          {/* Model */}
          <div>
            <div style={{ fontSize:10, color:'var(--text-muted)', marginBottom:4, letterSpacing:'0.04em', textTransform:'uppercase' }}>Model</div>
            <select
              value={settings.model}
              onChange={e => setSettings({ model: e.target.value })}
              style={{
                width:'100%', background:'var(--chrome-secondary)', border:'1px solid var(--border)',
                borderRadius:4, padding:'5px 8px', fontSize:11, color:'var(--text-primary)',
                outline:'none', cursor:'pointer',
              }}
              onFocus={e => e.target.style.borderColor='var(--accent)'}
              onBlur={e => e.target.style.borderColor='var(--border)'}
            >
              <option value="maxcoder-fast">maxcoder-fast (3B)</option>
              <option value="maxcoder">maxcoder (7B)</option>
            </select>
          </div>

          {/* Toggles */}
          {[
            ['useWeb',    IC.globe,  'Web Search'],
            ['useRag',    IC.db,     'RAG'],
            ['useMem',    IC.brain,  'Memory'],
            ['useRew',    IC.wand,   'Rewriter'],
            ['useCritic', IC.search, 'Critic (slow)'],
            ['autoRun',   IC.play,   'Auto-run code'],
          ].map(([key, icon, label]) => (
            <label key={key} style={{ display:'flex', alignItems:'center', gap:8, cursor:'pointer' }}>
              <div
                onClick={() => toggle(key)}
                style={{
                  width:28, height:14, borderRadius:7,
                  background: settings[key] ? 'var(--accent)' : 'var(--chrome-secondary)',
                  border: settings[key] ? 'none' : '1px solid var(--border)',
                  display:'flex', alignItems:'center',
                  padding:'0 2px', flexShrink:0, cursor:'pointer', transition:'background 0.2s',
                }}
              >
                <div style={{
                  width:10, height:10, borderRadius:'50%', background:'white',
                  transform: settings[key] ? 'translateX(14px)' : 'translateX(0)',
                  transition:'transform 0.2s',
                }}/>
              </div>
              <svg width={11} height={11} viewBox="0 0 24 24" fill="none"
                stroke={settings[key] ? '#5b9dd1' : 'var(--text-dim)'} strokeWidth={1.75} strokeLinecap="round" strokeLinejoin="round">
                <path d={icon} />
              </svg>
              <span style={{ fontSize:11, color: settings[key] ? 'var(--text-secondary)' : 'var(--text-muted)' }}>{label}</span>
            </label>
          ))}
        </div>
      )}

      {/* Bottom */}
      <div style={{ borderTop:'1px solid var(--border)', padding:'5px 8px', flexShrink:0, background:'var(--chrome-bg)' }}>
        <button
          onClick={() => setShowSettings(v => !v)}
          className="tree-item"
          style={{
            width:'100%', borderRadius:3, height:28, justifyContent:'flex-start', gap:7,
            background: showSettings ? 'var(--btn-active)' : 'transparent',
            color: showSettings ? 'var(--text-primary)' : 'var(--text-secondary)',
            border:'none', cursor:'pointer',
          }}
        >
          <Icon d={IC.sliders} size={12} />
          <span style={{ fontSize:11 }}>Settings</span>
        </button>
      </div>

      <style>{`.tree-item:hover .del-btn { opacity: 1 !important }`}</style>
    </div>
  )
}
