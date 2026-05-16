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
                prevMsg={i > 0 ? msgs[i - 1] : null}
                chatId={chat.id}
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

// ── Welcome screen V2 — intent-grouped starters, larger hero, shortcut tips ──
function WelcomeScreen() {
  const sendMessage = useStore(s => s.sendMessage)
  const settings    = useStore(s => s.settings)

  // Pick BY VERB — not by random topic. Teaches users what the agent can do.
  const rows = [
    { intent:'Build',    prompt:'Build a FastAPI REST API with SQLite database, authentication, and pytest tests.' },
    { intent:'Build',    prompt:'Build a React todo app with Zustand state management and TailwindCSS styling.' },
    { intent:'Refactor', prompt:'Convert this callback-style code to async/await with proper error handling.' },
    { intent:'Explain',  prompt:'Walk me through this Python file line-by-line and tell me what each block does.' },
    { intent:'Debug',    prompt:'Why is my SQLAlchemy query returning duplicate rows? Help me diagnose it.' },
  ]

  return (
    <div className="welcome-screen">
      <div className="welcome-inner">

        {/* Status pill — surfaces model + local status up front */}
        <span className="welcome-pill">
          <span className="dot" />
          {settings.model} · running locally
        </span>

        <h1>What are we building today?</h1>
        <p className="welcome-sub">
          Zero-cloud coding agent. Pick a starter or describe your own —
          MaxCoder can build, refactor, explain, or debug.
        </p>

        {/* Intent-grouped starter rows */}
        <div className="welcome-groups">
          {rows.map((r, i) => (
            <button
              key={i}
              className="welcome-row"
              onClick={() => sendMessage(r.prompt)}
            >
              <span className="intent">{r.intent}</span>
              <span className="label">{r.prompt}</span>
              <svg className="arrow" width={14} height={14} viewBox="0 0 24 24"
                   fill="none" stroke="currentColor" strokeWidth={2}
                   strokeLinecap="round" strokeLinejoin="round">
                <path d="M5 12h14M13 5l7 7-7 7"/>
              </svg>
            </button>
          ))}
        </div>

        {/* Shortcut hints — teach affordances on first run */}
        <div className="welcome-tip">
          <span><kbd>⌘K</kbd> Switch chat</span>
          <span><kbd>⌘N</kbd> New chat</span>
          <span><kbd>⌘⇧A</kbd> Agent IDE</span>
          <span><kbd>⌘⇧L</kbd> Toggle theme</span>
        </div>
      </div>
    </div>
  )
}
