import React, { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm    from 'remark-gfm'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism'
import { useStore } from '../store'

export default function MessageBubble({ msg, isStreaming }) {
  const isUser = msg.role === 'user'

  return (
    <div className={`flex gap-3 msg-enter ${isUser ? 'flex-row-reverse' : 'flex-row'}`}>

      {/* Avatar */}
      <div className={`w-8 h-8 rounded-full flex-shrink-0 flex items-center
                       justify-center text-xs font-bold
                       ${isUser
                         ? 'bg-accent text-white'
                         : 'bg-surface2 border border-border text-accent2'}`}>
        {isUser
          ? <i className="fa-solid fa-user text-xs"/>
          : <i className="fa-solid fa-code text-xs"/>}
      </div>

      {/* Bubble */}
      <div className={`max-w-[85%] ${isUser ? 'items-end' : 'items-start'} flex flex-col`}>
        {isUser ? (
          <div className="bg-accent text-white px-4 py-2.5 rounded-2xl
                          rounded-tr-sm text-sm leading-relaxed">
            {msg.content}
          </div>
        ) : (
          <div className="bg-surface border border-border rounded-2xl
                          rounded-tl-sm px-4 py-3 w-full">
            <div className={`prose text-sm ${!msg.done && isStreaming ? 'cursor' : ''}`}>
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{ code: CodeBlock }}
              >
                {msg.content || ' '}
              </ReactMarkdown>
            </div>

            {/* Action row */}
            {msg.done && (
              <div className="flex items-center gap-2 mt-3 pt-2 border-t border-border/50">
                <CopyBtn text={msg.content} label="Copy response"/>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

// ── Code block component ───────────────────────────────────────────────────
function CodeBlock({ node, inline, className, children, ...props }) {
  const runCode   = useStore(s => s.runCode)
  const [copied, setCopied] = useState(false)
  const lang = /language-(\w+)/.exec(className || '')?.[1] || ''
  const code = String(children).replace(/\n$/, '')
  const canRun = ['python','javascript','bash'].includes(lang)

  const copy = () => {
    navigator.clipboard.writeText(code)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  if (inline) {
    return (
      <code className="bg-surface2 text-accent2 px-1.5 py-0.5 rounded
                       font-mono text-xs" {...props}>
        {children}
      </code>
    )
  }

  return (
    <div className="code-block-wrap relative my-3 rounded-xl overflow-hidden
                    border border-border">
      {/* Header bar */}
      <div className="flex items-center justify-between px-4 py-2
                      bg-surface2 border-b border-border">
        <span className="text-xs font-mono text-slate-400 font-medium">
          {lang || 'code'}
        </span>
        <div className="flex items-center gap-2">
          {canRun && (
            <button
              onClick={() => runCode(code, lang)}
              className="flex items-center gap-1.5 text-xs text-slate-400
                         hover:text-green-400 transition-colors copy-btn"
            >
              <i className="fa-solid fa-play text-[10px]"/>
              Run
            </button>
          )}
          <button
            onClick={copy}
            className="flex items-center gap-1.5 text-xs text-slate-400
                       hover:text-white transition-colors copy-btn"
          >
            <i className={`fa-${copied ? 'solid fa-check text-green-400' : 'regular fa-copy'} text-xs`}/>
            {copied ? 'Copied' : 'Copy'}
          </button>
        </div>
      </div>

      {/* Code */}
      <SyntaxHighlighter
        language={lang}
        style={oneDark}
        customStyle={{
          margin: 0, padding: '14px 16px',
          background: '#0f1117',
          fontSize: '0.82rem',
          fontFamily: "'JetBrains Mono','Fira Code',monospace",
        }}
        showLineNumbers={code.split('\n').length > 5}
        lineNumberStyle={{ color: '#3e4a6a', fontSize: '0.7rem', minWidth: '2em' }}
      >
        {code}
      </SyntaxHighlighter>
    </div>
  )
}

function CopyBtn({ text, label }) {
  const [copied, setCopied] = useState(false)
  const copy = () => {
    navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }
  return (
    <button onClick={copy}
      className="flex items-center gap-1.5 text-xs text-slate-500
                 hover:text-slate-300 transition-colors">
      <i className={`fa-${copied ? 'solid fa-check text-green-400' : 'regular fa-copy'} text-xs`}/>
      {copied ? 'Copied' : label}
    </button>
  )
}
