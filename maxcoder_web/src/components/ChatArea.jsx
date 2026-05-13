import React, { useRef, useEffect } from 'react'
import { useStore }   from '../store'
import MessageBubble  from './MessageBubble'
import InputBar       from './InputBar'
import CodeOutputPanel from './CodeOutputPanel'

export default function ChatArea() {
  const chat      = useStore(s => s.activeChat())
  const streaming = useStore(s => s.streaming)
  const codeOutput= useStore(s => s.codeOutput)
  const bottomRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [chat?.messages?.length, streaming])

  const msgs = chat?.messages || []

  return (
    <main className="flex-1 flex flex-col h-full overflow-hidden">

      {/* Messages */}
      <div className="flex-1 overflow-y-auto">
        {msgs.length === 0 ? (
          <WelcomeScreen />
        ) : (
          <div className="max-w-3xl mx-auto px-4 py-6 space-y-6">
            {msgs.map((msg, i) => (
              <MessageBubble
                key={msg.id}
                msg={msg}
                isLast={i === msgs.length - 1}
                isStreaming={streaming && i === msgs.length - 1 && msg.role === 'assistant'}
              />
            ))}
            <div ref={bottomRef}/>
          </div>
        )}
      </div>

      {/* Code output panel */}
      {codeOutput && <CodeOutputPanel />}

      {/* Input bar */}
      <InputBar />
    </main>
  )
}

function WelcomeScreen() {
  const sendMessage = useStore(s => s.sendMessage)
  const settings    = useStore(s => s.settings)

  const examples = [
    { icon: 'fa-python', label: 'FastAPI + SQLite REST API', prompt: 'Build a FastAPI REST API with SQLite database, authentication, and pytest tests.' },
    { icon: 'fa-rust',   label: 'Rust file watcher CLI',    prompt: 'Write a Rust CLI that watches a directory and gzips new files as they appear.' },
    { icon: 'fa-js',     label: 'React + Zustand todo app', prompt: 'Build a React todo app with Zustand state management and TailwindCSS styling.' },
    { icon: 'fa-shield-halved', label: 'Solidity ERC-20 token', prompt: 'Write a Solidity ERC-20 token with a 1% transfer fee and Hardhat tests.' },
  ]

  return (
    <div className="flex flex-col items-center justify-center h-full px-4 text-center">
      <div className="w-16 h-16 rounded-2xl bg-accent/20 border border-accent/30
                      flex items-center justify-center mb-6">
        <i className="fa-solid fa-code text-2xl text-accent2"/>
      </div>
      <h1 className="text-2xl font-bold text-white mb-2">MaxCoder</h1>
      <p className="text-slate-400 text-sm mb-8 max-w-sm">
        Local coding LLM on <code className="text-accent2">Qwen2.5-Coder</code> —
        running on your machine, zero cloud, zero cost.
      </p>

      <div className="grid grid-cols-2 gap-3 w-full max-w-lg">
        {examples.map(ex => (
          <button
            key={ex.label}
            onClick={() => sendMessage(ex.prompt)}
            className="flex items-start gap-3 text-left px-4 py-3
                       bg-surface border border-border rounded-xl
                       hover:border-accent/50 hover:bg-surface2
                       transition-all duration-150 group"
          >
            <i className={`fa-brands ${ex.icon} text-accent2 mt-0.5 text-sm`}/>
            <span className="text-xs text-slate-300 group-hover:text-white
                             leading-relaxed">{ex.label}</span>
          </button>
        ))}
      </div>

      <p className="mt-8 text-xs text-slate-600">
        Model: <span className="text-accent2">{settings.model}</span>
      </p>
    </div>
  )
}