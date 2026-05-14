import React, { useRef, useEffect } from 'react'
import { useStore }    from '../store'
import MessageBubble   from './MessageBubble'
import InputBar        from './InputBar'
import CodeOutputPanel from './CodeOutputPanel'

export default function ChatArea() {
  const chat       = useStore(s => s.activeChat())
  const streaming  = useStore(s => s.streaming)
  const codeOutput = useStore(s => s.codeOutput)
  const bottomRef  = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior:'smooth' })
  }, [chat?.messages?.length, streaming])

  const msgs = chat?.messages || []

  return (
    <main style={{ flex:1, display:'flex', flexDirection:'column', height:'100%', overflow:'hidden', background:'var(--content-bg)', minWidth:0 }}>

      {/* Messages */}
      <div style={{ flex:1, overflowY:'auto' }}>
        {msgs.length === 0 ? (
          <WelcomeScreen />
        ) : (
          <div>
            {msgs.map((msg, i) => (
              <MessageBubble
                key={msg.id}
                msg={msg}
                isLast={i === msgs.length - 1}
                isStreaming={streaming && i === msgs.length - 1 && msg.role === 'assistant'}
              />
            ))}
            <div ref={bottomRef} />
          </div>
        )}
      </div>

      {/* Code output panel */}
      {codeOutput && <CodeOutputPanel />}

      {/* Input */}
      <InputBar />
    </main>
  )
}

function WelcomeScreen() {
  const sendMessage = useStore(s => s.sendMessage)
  const settings    = useStore(s => s.settings)

  const examples = [
    { icon:'M13 10V3L4 14h7v7l9-11h-7z', label:'FastAPI + SQLite REST API', prompt:'Build a FastAPI REST API with SQLite database, authentication, and pytest tests.' },
    { icon:'M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4', label:'React + Zustand todo app', prompt:'Build a React todo app with Zustand state management and TailwindCSS styling.' },
    { icon:'M9 3H5a2 2 0 00-2 2v4m6-6h10a2 2 0 012 2v4M9 3v18m0 0h10a2 2 0 002-2V9M9 21H5a2 2 0 01-2-2V9m0 0h18', label:'Python web scraper', prompt:'Write a Python web scraper using httpx and BeautifulSoup that extracts article data.' },
    { icon:'M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z', label:'Solidity ERC-20 token', prompt:'Write a Solidity ERC-20 token with a 1% transfer fee and Hardhat tests.' },
  ]

  return (
    <div style={{ display:'flex', flexDirection:'column', alignItems:'center', justifyContent:'center', height:'100%', padding:'40px 28px', textAlign:'center' }}>

      {/* Logo mark */}
      <div style={{ width:48, height:48, borderRadius:8, background:'var(--accent-dim)', border:'1px solid var(--accent-border)', display:'flex', alignItems:'center', justifyContent:'center', marginBottom:20 }}>
        <svg width={22} height={22} viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth={1.75} strokeLinecap="round" strokeLinejoin="round">
          <path d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4"/>
        </svg>
      </div>

      <h1 style={{ fontSize:19, fontWeight:600, color:'var(--text-primary)', marginBottom:6, letterSpacing:'-0.01em' }}>
        MaxCoder
      </h1>
      <p style={{ color:'var(--text-muted)', fontSize:12, marginBottom:30, maxWidth:360, lineHeight:1.75 }}>
        Local coding LLM on{' '}
        <span style={{ color:'#5b9dd1', fontFamily:"'JetBrains Mono',monospace", fontSize:11 }}>Qwen2.5-Coder</span>
        {' '}— running on your machine, zero cloud, zero cost.
      </p>

      <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:8, width:'100%', maxWidth:500 }}>
        {examples.map(ex => (
          <button
            key={ex.label}
            onClick={() => sendMessage(ex.prompt)}
            style={{
              display:'flex', alignItems:'flex-start', gap:10, textAlign:'left',
              padding:'11px 14px', background:'var(--chrome-secondary)', border:'1px solid var(--border)',
              borderRadius:5, cursor:'pointer', transition:'all 0.12s',
            }}
            onMouseEnter={e => { e.currentTarget.style.borderColor='var(--accent-border)'; e.currentTarget.style.background='var(--btn-hover)' }}
            onMouseLeave={e => { e.currentTarget.style.borderColor='var(--border)'; e.currentTarget.style.background='var(--chrome-secondary)' }}
          >
            <svg width={13} height={13} viewBox="0 0 24 24" fill="none" stroke="#5b9dd1" strokeWidth={1.75} strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink:0, marginTop:1 }}>
              <path d={ex.icon}/>
            </svg>
            <span style={{ fontSize:11, color:'var(--text-secondary)', lineHeight:1.55 }}>{ex.label}</span>
          </button>
        ))}
      </div>

      <p style={{ marginTop:24, fontSize:10, color:'var(--text-dim)' }}>
        Model: <span style={{ color:'var(--text-muted)' }}>{settings.model}</span>
      </p>
    </div>
  )
}
