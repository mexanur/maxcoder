import React, { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm    from 'remark-gfm'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism'
import { useStore } from '../store'

// Parse @@GENERATE:fmt ... @@END blocks out of LLM response
function parseGenerateBlocks(text) {
  const blocks = []
  const re = /@@GENERATE:([\w]+)\n([\s\S]*?)@@END/g
  let match
  while ((match = re.exec(text)) !== null) {
    blocks.push({ fmt: match[1].toLowerCase(), content: match[2].trim(), raw: match[0] })
  }
  const clean = text.replace(/@@GENERATE:[\w]+\n[\s\S]*?@@END/g, '').trim()
  return { blocks, clean }
}

export default function MessageBubble({ msg, prevMsg, chatId, isStreaming }) {
  const isUser = msg.role === 'user'
  const { blocks: genBlocks, clean: cleanContent } = isUser
    ? { blocks: [], clean: msg.content }
    : parseGenerateBlocks(msg.content || '')

  // Format msg.startedAt as HH:MM for the message header.
  const timeLabel = msg.startedAt
    ? new Date(msg.startedAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    : null

  return (
    <div className={`chat-row ${isUser ? 'chat-row-user' : 'chat-row-assistant'} msg-enter`}>

      {/* Avatar (replaces the old uppercase sender label) */}
      <div className={`chat-avatar ${isUser ? 'chat-avatar-user' : 'chat-avatar-ai'}`}
           aria-hidden="true">
        {isUser
          ? 'Y'
          : (
            <svg width={14} height={14} viewBox="0 0 24 24" fill="none"
                 stroke="currentColor" strokeWidth={2}
                 strokeLinecap="round" strokeLinejoin="round">
              <path d="M13 2L3 14h7l-1 8 10-12h-7l1-8z"/>
            </svg>
          )
        }
      </div>

      <div className="chat-content">

      {/* Header: name + timestamp (model shown via ResponseTimer below) */}
      <div className="chat-sender">
        <span className="name">{isUser ? 'You' : 'MaxCoder'}</span>
        {timeLabel && <span className="time">{timeLabel}</span>}
      </div>

      {/* Attached file chips */}
      {msg.files?.length > 0 && (
        <div style={{ display:'flex', flexWrap:'wrap', gap:5, marginBottom:4 }}>
          {msg.files.map(f => <FileChip key={f.name} file={f} />)}
        </div>
      )}

      {/* Skill badge — appears when a deterministic skill handled this turn */}
      {!isUser && msg.skill && <SkillBadge skill={msg.skill} />}

      {/* MaxThink reasoning chain (collapsible) */}
      {!isUser && msg.reasoning && (msg.reasoning.thinking || msg.reasoning.plan) && (
        <ReasoningPanel reasoning={msg.reasoning} />
      )}

      {/* Generated file download cards */}
      {genBlocks.map((b, i) => (
        <GeneratedFileCard key={i} fmt={b.fmt} content={b.content} />
      ))}

      {/* Live task previews — show while generation is in progress */}
      {msg.liveTasks && Object.entries(msg.liveTasks).map(([idx, t]) => (
        <LiveTaskPreview key={`live-${idx}`} task={t} />
      ))}

      {/* Body */}
      <div className="chat-body">
        {isUser ? (
          <p style={{ color:'var(--text-primary)', fontSize:13, lineHeight:1.65, whiteSpace:'pre-wrap', wordBreak:'break-word' }}>
            {msg.content}
          </p>
        ) : (
          <div className={`prose ${!msg.done && isStreaming ? 'cursor' : ''}`}>
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{ code: CodeBlock }}
            >
              {cleanContent || ' '}
            </ReactMarkdown>
          </div>
        )}
      </div>

      {/* Web citations footer — appears when web skills cite sources */}
      {!isUser && msg.citations?.length > 0 && (
        <CitationsFooter sources={msg.citations} />
      )}

      {/* Uncertainty badge — appears above actions when model is unsure */}
      {!isUser && msg.done && msg.uncertainty && msg.uncertainty.show_badge && (
        <UncertaintyBadge u={msg.uncertainty} />
      )}

      {/* Actions row */}
      {!isUser && (
        <div style={{ display:'flex', alignItems:'center', gap:8, marginTop:4, flexWrap:'wrap' }}>
          {msg.done && <CopyBtn text={msg.content} />}
          {msg.done && prevMsg?.role === 'user' && (
            <FeedbackButtons
              chatId={chatId}
              msgId={msg.id}
              persistedFeedback={msg.feedback}
              query={prevMsg.augmented || prevMsg.content}
              response={msg.content}
              files={prevMsg.files}
              reasoning={msg.reasoning}
            />
          )}
          {/* Translation correction — only on translation-skill outputs */}
          {msg.done && msg.skill?.skill === 'translation' && prevMsg?.role === 'user' && (
            <TranslateCorrectionBtn
              source={prevMsg.augmented || prevMsg.content}
              draft={msg.content}
              lang={msg.skill?.target || 'unknown'}
            />
          )}
          <ResponseTimer msg={msg} isStreaming={isStreaming} />
        </div>
      )}
      </div>{/* /chat-content */}
    </div>
  )
}

function ResponseTimer({ msg, isStreaming }) {
  const [now, setNow] = useState(Date.now())

  useEffect(() => {
    if (msg.done || !isStreaming || !msg.startedAt) return
    const id = window.setInterval(() => setNow(Date.now()), 100)
    return () => window.clearInterval(id)
  }, [isStreaming, msg.done, msg.startedAt])

  if (typeof msg.durationMs === 'number') {
    return <span className="response-time">{formatDuration(msg.durationMs)}</span>
  }

  if (isStreaming && msg.startedAt) {
    return (
      <span className="response-time response-time-live">
        Generating... {formatDuration(now - msg.startedAt)}
      </span>
    )
  }

  return null
}

function formatDuration(ms) {
  const seconds = Math.max(0.1, ms / 1000)
  return `${seconds < 10 ? seconds.toFixed(1) : Math.round(seconds)}s`
}

// ── Code block ────────────────────────────────────────────────────────────────
function CodeBlock({ node, inline, className, children, ...props }) {
  const runCode = useStore(s => s.runCode)
  const [copied, setCopied] = useState(false)
  const lang = /language-(\w+)/.exec(className || '')?.[1] || ''
  const code = String(children).replace(/\n$/, '')
  const canRun = ['python','javascript','bash','shell'].includes(lang)

  const copy = () => {
    navigator.clipboard.writeText(code)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  if (inline) {
    return (
      <code style={{ background:'var(--surface-low)', color:'#5b9dd1', padding:'1px 5px', borderRadius:3, fontFamily:"'JetBrains Mono',monospace", fontSize:11, border:'1px solid var(--border)' }} {...props}>
        {children}
      </code>
    )
  }

  return (
    <div className="code-block" style={{ borderRadius:4, overflow:'hidden', margin:'8px 0', border:'1px solid var(--border)' }}>
      {/* Header */}
      <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between', padding:'5px 10px', background:'var(--surface-low)', borderBottom:'1px solid var(--border)' }}>
        <span style={{ fontFamily:"'JetBrains Mono',monospace", fontSize:10, color:'var(--text-muted)', fontWeight:500 }}>
          {lang || 'code'}
        </span>
        <div style={{ display:'flex', alignItems:'center', gap:8 }}>
          {canRun && (
            <button
              onClick={() => runCode(code, lang)}
              style={{ fontSize:10, color:'var(--text-muted)', background:'transparent', border:'none', cursor:'pointer', display:'flex', alignItems:'center', gap:4, fontFamily:'inherit', padding:'1px 4px', borderRadius:3 }}
              onMouseEnter={e => e.currentTarget.style.color='var(--green)'}
              onMouseLeave={e => e.currentTarget.style.color='var(--text-muted)'}
            >
              <svg width={9} height={9} viewBox="0 0 24 24" fill="currentColor"><path d="M5 3l14 9-14 9V3z"/></svg>
              Run
            </button>
          )}
          <button
            onClick={copy}
            style={{ fontSize:10, color: copied ? 'var(--green)' : 'var(--text-muted)', background:'transparent', border:'none', cursor:'pointer', fontFamily:'inherit', padding:'1px 4px', borderRadius:3 }}
            onMouseEnter={e => { if (!copied) e.currentTarget.style.color='var(--text-primary)' }}
            onMouseLeave={e => { if (!copied) e.currentTarget.style.color='var(--text-muted)' }}
          >
            {copied ? '✓ copied' : 'copy'}
          </button>
        </div>
      </div>

      {/* Code */}
      <SyntaxHighlighter
        language={lang || 'text'}
        style={vscDarkPlus}
        customStyle={{
          margin: 0, padding: '12px 14px',
          background: '#1e2123',
          fontSize: '11.5px',
          fontFamily: "'JetBrains Mono','Fira Code',monospace",
          lineHeight: 1.6,
        }}
        showLineNumbers={code.split('\n').length > 5}
        lineNumberStyle={{ color:'#4a4d51', fontSize:'10px', minWidth:'2em', userSelect:'none' }}
      >
        {code}
      </SyntaxHighlighter>
    </div>
  )
}

// ── Interactive file chip with preview modal ──────────────────────────────────
// ── Generated file download card ──────────────────────────────────────────────
const FMT_META = {
  pdf:  { label:'PDF',  color:'#e05a52', bg:'rgba(224,90,82,0.12)',  icon:'M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z' },
  docx: { label:'Word', color:'#2677bf', bg:'rgba(38,119,191,0.12)', icon:'M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z' },
  xlsx: { label:'Excel',color:'#4caf6e', bg:'rgba(76,175,110,0.12)', icon:'M3 10h18M3 14h18M10 3v18M14 3v18M5 3h14a2 2 0 012 2v14a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2z' },
  csv:  { label:'CSV',  color:'#4caf6e', bg:'rgba(76,175,110,0.12)', icon:'M3 10h18M3 14h18M10 3v18M14 3v18M5 3h14a2 2 0 012 2v14a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2z' },
  txt:  { label:'TXT',  color:'#888d93', bg:'rgba(136,141,147,0.12)',icon:'M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z' },
}

// ── Live task preview — shows tokens streaming in real time during generation ──
function LiveTaskPreview({ task }) {
  const [thinkOpen, setThinkOpen] = useState(false)
  const meta = FMT_META[task.fmt] || FMT_META.txt
  const hasThinking = task.thinking && task.thinking.length > 0
  const hasContent  = task.content  && task.content.length > 0
  const previewRef = useRef(null)
  const thinkRef   = useRef(null)

  // Auto-scroll to bottom as new tokens arrive
  useEffect(() => {
    if (previewRef.current) previewRef.current.scrollTop = previewRef.current.scrollHeight
  }, [task.content])
  useEffect(() => {
    if (thinkRef.current && thinkOpen) thinkRef.current.scrollTop = thinkRef.current.scrollHeight
  }, [task.thinking, thinkOpen])

  return (
    <div style={{
      border: `1px solid ${meta.color}40`,
      borderLeft: `3px solid ${meta.color}`,
      borderRadius: 4,
      background: meta.bg,
      marginBottom: 6,
      overflow: 'hidden',
    }}>
      {/* Header */}
      <div style={{ display:'flex', alignItems:'center', gap:8,
                     padding:'8px 12px', borderBottom: hasContent || hasThinking ? `1px solid ${meta.color}22` : 'none' }}>
        <svg width={14} height={14} viewBox="0 0 24 24" fill="none" stroke={meta.color}
             strokeWidth={2} strokeLinecap="round" strokeLinejoin="round"
             style={{ animation: 'spin 1.4s linear infinite', transformOrigin: 'center' }}>
          <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/>
        </svg>
        <span style={{ fontSize:12, fontWeight:600, color:'var(--text-primary)' }}>
          Generating {meta.label}
        </span>
        {task.title && (
          <span style={{ fontSize:10, color:'var(--text-secondary)' }}>
            · {task.title}
          </span>
        )}
        <span style={{ marginLeft:'auto', fontSize:10, color:'var(--text-muted)' }}>
          {task.content?.length || 0} chars
        </span>
      </div>

      {/* Live thinking (when reasoning is on) */}
      {hasThinking && (
        <div style={{ borderBottom: hasContent ? `1px solid ${meta.color}22` : 'none' }}>
          <button
            onClick={() => setThinkOpen(o => !o)}
            style={{ display:'flex', alignItems:'center', gap:6, width:'100%',
                     padding:'5px 12px', background:'transparent', border:'none',
                     fontSize:10, color:'var(--text-secondary)', cursor:'pointer',
                     fontFamily:'inherit', textAlign:'left' }}
          >
            <svg width={9} height={9} viewBox="0 0 24 24" fill="none" stroke="currentColor"
                 strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round"
                 style={{ transform: thinkOpen ? 'rotate(90deg)' : 'rotate(0deg)', transition:'transform 0.15s' }}>
              <path d="M9 18l6-6-6-6"/>
            </svg>
            💭 Thinking ({task.thinking.length.toLocaleString()} chars)
          </button>
          {thinkOpen && (
            <pre ref={thinkRef}
                 style={{ fontFamily:"'JetBrains Mono',monospace", fontSize:10, lineHeight:1.5,
                          color:'var(--text-secondary)', whiteSpace:'pre-wrap', wordBreak:'break-word',
                          margin:0, padding:'6px 12px 10px 12px', maxHeight:200, overflowY:'auto',
                          background:'var(--surface-low)' }}>
              {task.thinking}
            </pre>
          )}
        </div>
      )}

      {/* Live content */}
      {hasContent && (
        <pre ref={previewRef}
             style={{ fontFamily:"'JetBrains Mono',monospace", fontSize:11, lineHeight:1.5,
                      color:'var(--text-primary)', whiteSpace:'pre-wrap', wordBreak:'break-word',
                      margin:0, padding:'8px 12px', maxHeight:240, overflowY:'auto' }}>
          {task.content}
          <span style={{ display:'inline-block', width:6, height:11, background:meta.color,
                          marginLeft:2, animation:'blink 1s steps(2) infinite', verticalAlign:'middle' }} />
        </pre>
      )}

      <style>{`
        @keyframes spin { from { transform: rotate(0deg) } to { transform: rotate(360deg) } }
        @keyframes blink { 0%, 100% { opacity: 1 } 50% { opacity: 0 } }
      `}</style>
    </div>
  )
}


function GeneratedFileCard({ fmt, content }) {
  const [status, setStatus]   = useState('idle') // idle | loading | done | error
  const [preview, setPreview] = useState(false)
  const meta = FMT_META[fmt] || FMT_META.txt

  const download = async () => {
    setStatus('loading')
    try {
      const res = await fetch('/api/generate-file', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ content, fmt, filename: 'maxcoder_output' }),
      })
      if (!res.ok) throw new Error(await res.text())
      const blob = await res.blob()
      const url  = URL.createObjectURL(blob)
      const a    = document.createElement('a')
      const disp = res.headers.get('content-disposition') || ''
      const m    = disp.match(/filename="?([^"]+)"?/)
      a.download = m ? m[1] : `maxcoder_output.${fmt}`
      a.href = url; a.click()
      URL.revokeObjectURL(url)
      setStatus('done')
      setTimeout(() => setStatus('idle'), 3000)
    } catch (e) {
      console.error(e)
      setStatus('error')
      setTimeout(() => setStatus('idle'), 3000)
    }
  }

  return (
    <>
      <div style={{
        display:'flex', alignItems:'center', gap:12,
        background: meta.bg,
        border:`1px solid ${meta.color}40`,
        borderRadius:6, padding:'10px 14px',
        marginBottom:6,
      }}>
        {/* File icon */}
        <div style={{ width:36, height:36, borderRadius:6, background:`${meta.color}20`, border:`1px solid ${meta.color}40`, display:'flex', alignItems:'center', justifyContent:'center', flexShrink:0 }}>
          <svg width={18} height={18} viewBox="0 0 24 24" fill="none" stroke={meta.color} strokeWidth={1.75} strokeLinecap="round" strokeLinejoin="round">
            <path d={meta.icon}/>
          </svg>
        </div>

        {/* Info */}
        <div style={{ flex:1, minWidth:0 }}>
          <div style={{ fontSize:12, fontWeight:600, color:'var(--text-primary)' }}>
            Generated {meta.label} file
          </div>
          <div style={{ fontSize:10, color:'var(--text-muted)', marginTop:2 }}>
            {content.length.toLocaleString()} chars · ready to download
          </div>
        </div>

        {/* Preview toggle */}
        <button
          onClick={() => setPreview(v => !v)}
          style={{ fontSize:10, padding:'4px 9px', borderRadius:3, border:'1px solid var(--border)', background:'transparent', color:'var(--text-secondary)', cursor:'pointer', fontFamily:'inherit' }}
          onMouseEnter={e => e.currentTarget.style.color='var(--text-primary)'}
          onMouseLeave={e => e.currentTarget.style.color='var(--text-secondary)'}
        >
          {preview ? 'Hide' : 'Preview'}
        </button>

        {/* Download button */}
        <button
          onClick={download}
          disabled={status === 'loading'}
          style={{
            display:'flex', alignItems:'center', gap:6,
            fontSize:12, fontWeight:600, padding:'6px 14px',
            borderRadius:4, border:'none', cursor: status === 'loading' ? 'wait' : 'pointer',
            background: status === 'done' ? '#4caf6e' : status === 'error' ? '#e05a52' : meta.color,
            color:'white', fontFamily:'inherit', transition:'opacity 0.12s',
            opacity: status === 'loading' ? 0.7 : 1,
          }}
        >
          {status === 'loading' && (
            <svg width={11} height={11} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5} strokeLinecap="round" style={{ animation:'spin 1s linear infinite', transformOrigin:'center' }}>
              <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/>
            </svg>
          )}
          {status === 'done' && '✓ Downloaded'}
          {status === 'error' && 'Failed — retry'}
          {status === 'idle' && (
            <>
              <svg width={11} height={11} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M7 10l5 5 5-5M12 15V3"/>
              </svg>
              Download {meta.label}
            </>
          )}
        </button>
      </div>

      {/* Inline preview */}
      {preview && (
        <div style={{ background:'var(--surface-low)', border:'1px solid var(--border)', borderRadius:4, padding:'10px 14px', marginBottom:6, maxHeight:260, overflowY:'auto' }}>
          <pre style={{ fontFamily:"'JetBrains Mono',monospace", fontSize:10, lineHeight:1.6, color:'var(--text-secondary)', whiteSpace:'pre-wrap', wordBreak:'break-word', margin:0 }}>
            {content}
          </pre>
        </div>
      )}

      <style>{`@keyframes spin{from{transform:rotate(0deg)}to{transform:rotate(360deg)}}`}</style>
    </>
  )
}

function FileChip({ file }) {
  const [open, setOpen] = useState(false)
  const ext   = (file.name || '').split('.').pop().toLowerCase()
  const color = { pdf:'#e05a52', docx:'#2677bf', xlsx:'#4caf6e', xls:'#4caf6e', csv:'#4caf6e',
                  py:'#e5c07b', js:'#e5c07b', ts:'#61afef', json:'#98c379', md:'#abb2bf' }[ext] || '#888d93'

  const download = (e) => {
    e.stopPropagation()
    if (!file.text) return
    const blob = new Blob([file.text], { type: 'text/plain' })
    const url  = URL.createObjectURL(blob)
    const a    = document.createElement('a')
    a.href     = url
    a.download = file.name.replace(/\.[^.]+$/, '') + '_extracted.txt'
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <>
      {/* Chip button */}
      <button
        onClick={() => setOpen(true)}
        title="Click to preview extracted content"
        style={{
          display:'inline-flex', alignItems:'center', gap:5,
          background:'var(--accent-dim)', border:'1px solid var(--accent-border)',
          borderRadius:3, padding:'3px 8px 3px 6px', fontSize:11, color:'#5b9dd1',
          cursor:'pointer', fontFamily:'inherit', transition:'background 0.12s',
        }}
        onMouseEnter={e => e.currentTarget.style.background='rgba(38,119,191,0.28)'}
        onMouseLeave={e => e.currentTarget.style.background='var(--accent-dim)'}
      >
        <svg width={11} height={11} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
          <path d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/>
        </svg>
        {file.name}
        {file.chars > 0 && (
          <span style={{ fontSize:9, color:'var(--text-muted)', marginLeft:1 }}>
            {(file.chars / 1000).toFixed(1)}k
          </span>
        )}
      </button>

      {/* Preview modal */}
      {open && (
        <div
          onClick={() => setOpen(false)}
          style={{
            position:'fixed', inset:0, zIndex:1000,
            background:'rgba(12,14,16,0.72)',
            backdropFilter:'blur(4px)',
            display:'flex', alignItems:'center', justifyContent:'center',
          }}
        >
          <div
            onClick={e => e.stopPropagation()}
            style={{
              background:'var(--chrome-deep)',
              border:'1px solid var(--border-light)',
              borderRadius:6,
              boxShadow:'0 8px 24px rgba(0,0,0,0.5)',
              width:'min(680px, 90vw)',
              maxHeight:'70vh',
              display:'flex', flexDirection:'column',
              overflow:'hidden',
            }}
          >
            {/* Modal header */}
            <div style={{
              display:'flex', alignItems:'center', gap:8,
              padding:'10px 14px', borderBottom:'1px solid var(--border)',
              background:'var(--chrome-bg)', flexShrink:0,
            }}>
              <svg width={13} height={13} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
                <path d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/>
              </svg>
              <span style={{ fontSize:12, fontWeight:600, color:'var(--text-primary)', flex:1, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>
                {file.name}
              </span>
              <span style={{ fontSize:10, color:'var(--text-muted)', marginRight:8 }}>
                {file.chars?.toLocaleString()} chars extracted
              </span>
              {/* Download button */}
              <button
                onClick={download}
                title="Download extracted text"
                style={{
                  display:'flex', alignItems:'center', gap:5, fontSize:11,
                  padding:'4px 10px', borderRadius:4,
                  background:'var(--accent-dim)', border:'1px solid var(--accent-border)',
                  color:'#5b9dd1', cursor:'pointer', fontFamily:'inherit',
                  transition:'background 0.12s',
                }}
                onMouseEnter={e => e.currentTarget.style.background='rgba(38,119,191,0.28)'}
                onMouseLeave={e => e.currentTarget.style.background='var(--accent-dim)'}
              >
                <svg width={11} height={11} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
                  <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M7 10l5 5 5-5M12 15V3"/>
                </svg>
                Download
              </button>
              {/* Close button */}
              <button
                onClick={() => setOpen(false)}
                style={{
                  background:'none', border:'none', cursor:'pointer',
                  color:'var(--text-muted)', fontSize:18, lineHeight:1,
                  padding:'0 2px', display:'flex', borderRadius:3,
                  transition:'color 0.12s',
                }}
                onMouseEnter={e => e.currentTarget.style.color='var(--text-primary)'}
                onMouseLeave={e => e.currentTarget.style.color='var(--text-muted)'}
              >×</button>
            </div>

            {/* Content */}
            <div style={{ overflowY:'auto', padding:'14px 16px', flex:1 }}>
              {file.text
                ? <pre style={{
                    fontFamily:"'JetBrains Mono', monospace",
                    fontSize:11, lineHeight:1.65,
                    color:'var(--text-secondary)',
                    whiteSpace:'pre-wrap', wordBreak:'break-word', margin:0,
                  }}>{file.text}</pre>
                : <p style={{ color:'var(--text-muted)', fontSize:12 }}>No extracted content available.</p>
              }
            </div>
          </div>
        </div>
      )}
    </>
  )
}

// ── Skill badge — indicates a deterministic skill handled this turn ─────────
const SKILL_META = {
  file_generation: { label: 'File generation', color: '#9b6dff' },
  web_search:      { label: 'Web search',      color: '#2677bf' },
  web_fetch:       { label: 'Web page',        color: '#4caf6e' },
  web_compare:     { label: 'Web comparison',  color: '#e0a052' },
  docs_navigation: { label: 'Docs deep dive',  color: '#5b9dd1' },
  repo_explorer:   { label: 'GitHub repo',     color: '#888d93' },
  translation:     { label: 'Translation',     color: '#6dc4b0' },
}

function SkillBadge({ skill }) {
  const meta = SKILL_META[skill.skill] || { label: skill.label || skill.skill, color: '#2677bf' }

  // Build the status label based on stage
  let stageText = ''
  // File generation stages
  if (skill.stage === 'planning')   stageText = 'Planning…'
  else if (skill.stage === 'fast_path')  stageText = 'Fast path'
  else if (skill.stage === 'plan_ready') stageText = `${skill.count || 0} files planned${skill.complex ? ' · thinking' : ''}`
  else if (skill.stage === 'generating') stageText = `Generating ${(skill.index ?? 0) + 1}/${skill.total || '?'} — ${skill.title || ''}${skill.complex ? ' (reasoning)' : ''}`
  // Web search stages
  else if (skill.stage === 'searching')        stageText = 'Searching DuckDuckGo…'
  else if (skill.stage === 'found_results')    stageText = `Found ${skill.count || 0} results`
  else if (skill.stage === 'fetching_pages')   stageText = `Fetching ${skill.count || 0} pages…`
  else if (skill.stage === 'searching_both')   stageText = `Searching ${skill.a} vs ${skill.b}…`
  else if (skill.stage === 'fetching')         stageText = skill.url ? `Reading ${new URL(skill.url).hostname.replace(/^www\./, '')}…` : 'Fetching…'
  else if (skill.stage === 'synthesizing')     stageText = 'Synthesizing answer…'
  else if (skill.stage === 'task_plan')        stageText = 'Planning approach…'
  else if (skill.stage === 'task_thinking_delta' || skill.stage === 'task_thinking_done')
                                                stageText = 'Thinking…'
  else if (skill.stage === 'task_content_delta') stageText = 'Writing answer…'
  // Docs navigation stages
  else if (skill.stage === 'crawling')         stageText = `Crawling docs (up to ${skill.max_pages || 3} pages)…`
  // Repo explorer stages
  else if (skill.stage === 'probing_repo')     stageText = `Reading ${skill.owner}/${skill.repo}…`

  return (
    <div style={{
      display: 'inline-flex', alignItems: 'center', gap: 6, flexWrap: 'wrap',
      padding: '3px 8px', marginTop: 6, marginBottom: 4,
      background: `${meta.color}18`,
      border: `1px solid ${meta.color}40`,
      borderRadius: 12,
      fontSize: 10, color: meta.color, fontWeight: 600,
      letterSpacing: 0.2,
    }}>
      <svg width={11} height={11} viewBox="0 0 24 24" fill="none" stroke="currentColor"
           strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
        <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>
      </svg>
      {meta.label} skill
      {skill.fmt && (
        <span style={{ padding: '1px 5px', background: `${meta.color}33`,
                       borderRadius: 6, fontSize: 9, fontWeight: 700 }}>
          {String(skill.fmt).toUpperCase()}
        </span>
      )}
      {stageText && (
        <span style={{ color: 'var(--text-secondary)', fontWeight: 400, fontSize: 10 }}>
          · {stageText}
        </span>
      )}
    </div>
  )
}


// ── Citations footer — clickable source list for web-skill answers ─────────
function CitationsFooter({ sources }) {
  if (!sources || sources.length === 0) return null

  const hostname = (url) => {
    try { return new URL(url).hostname.replace(/^www\./, '') }
    catch { return url }
  }

  return (
    <div style={{
      marginTop: 8, padding: '8px 10px',
      background: 'var(--surface-low, #2a2d2f)',
      border: '1px solid var(--border)',
      borderLeft: '3px solid #2677bf',
      borderRadius: 4, fontSize: 11,
    }}>
      <div style={{
        fontSize: 9, fontWeight: 700, letterSpacing: 0.6,
        color: 'var(--text-secondary)', textTransform: 'uppercase',
        marginBottom: 6, display: 'flex', alignItems: 'center', gap: 6,
      }}>
        <svg width={10} height={10} viewBox="0 0 24 24" fill="none" stroke="#2677bf"
             strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="10"/>
          <line x1="2" y1="12" x2="22" y2="12"/>
          <path d="M12 2a15.3 15.3 0 014 10 15.3 15.3 0 01-4 10 15.3 15.3 0 01-4-10 15.3 15.3 0 014-10z"/>
        </svg>
        Sources ({sources.length})
      </div>
      <ol style={{ margin: 0, padding: 0, listStyle: 'none' }}>
        {sources.map((s, i) => (
          <li key={i} style={{ display: 'flex', alignItems: 'flex-start', gap: 6, padding: '3px 0' }}>
            <span style={{
              minWidth: 18, fontSize: 9, fontWeight: 700, color: '#2677bf',
              background: 'rgba(38,119,191,0.12)', borderRadius: 8,
              padding: '1px 5px', textAlign: 'center', marginTop: 2,
            }}>
              [{s.n || i + 1}]
            </span>
            <div style={{ flex: 1, minWidth: 0 }}>
              <a
                href={s.url}
                target="_blank"
                rel="noopener noreferrer"
                style={{
                  fontSize: 11, color: '#5b9dd1', textDecoration: 'none',
                  fontWeight: 500, lineHeight: 1.35, wordBreak: 'break-word',
                }}
                onMouseEnter={e => e.currentTarget.style.textDecoration = 'underline'}
                onMouseLeave={e => e.currentTarget.style.textDecoration = 'none'}
                title={s.url}
              >
                {s.title || hostname(s.url)}
              </a>
              <div style={{ fontSize: 10, color: 'var(--text-dim)', lineHeight: 1.35, marginTop: 1 }}>
                {hostname(s.url)}
                {s.snippet && <span style={{ marginLeft: 6, color: 'var(--text-muted)' }}>· {s.snippet.slice(0, 110)}{s.snippet.length > 110 ? '…' : ''}</span>}
              </div>
            </div>
          </li>
        ))}
      </ol>
    </div>
  )
}


// ── Uncertainty badge — surfaces low/medium-confidence answers ──────────────
function UncertaintyBadge({ u }) {
  const verifyWithWeb = useStore(s => s.verifyWithWeb)
  const [expanded, setExpanded] = useState(false)
  const [retrying, setRetrying] = useState(false)

  // Color map: LOW = orange/red, MEDIUM = amber, HIGH = none (no badge)
  const palette = u.level === 'LOW'
    ? { bg: 'rgba(224,90,82,0.10)',   border: '#e05a52', text: '#e05a52', label: 'Low confidence' }
    : u.level === 'MEDIUM'
    ? { bg: 'rgba(224,160,82,0.10)',  border: '#e0a052', text: '#e0a052', label: 'Medium confidence' }
    : { bg: 'rgba(136,141,147,0.10)', border: '#888d93', text: '#888d93', label: 'Confidence: unknown' }

  const reason = u.verbalized_reason || (u.hedge_matches?.length
    ? `Detected uncertainty signals: ${u.hedge_matches.slice(0, 3).map(m => `"${m.phrase}"`).join(', ')}`
    : 'The model expressed hedging without explicit reason.')

  const handleVerify = async () => {
    setRetrying(true)
    try { await verifyWithWeb() } finally { setRetrying(false) }
  }

  return (
    <div style={{
      background: palette.bg,
      border: `1px solid ${palette.border}33`,
      borderLeft: `3px solid ${palette.border}`,
      borderRadius: 4,
      padding: '8px 10px',
      marginTop: 6,
      fontSize: 11,
      color: 'var(--text-primary)',
    }}>
      {/* Header */}
      <div style={{ display:'flex', alignItems:'center', gap:8 }}>
        <svg width={12} height={12} viewBox="0 0 24 24" fill="none" stroke={palette.text}
             strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink:0 }}>
          <path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/>
          <line x1="12" y1="9" x2="12" y2="13"/>
          <line x1="12" y1="17" x2="12.01" y2="17"/>
        </svg>
        <span style={{ fontWeight:600, color: palette.text }}>{palette.label}</span>
        {u.verbalized_level && u.verbalized_level !== 'UNKNOWN' && (
          <span style={{ fontSize:9, padding:'1px 6px', borderRadius:8,
                         background:`${palette.border}22`, color:palette.text, fontWeight:600 }}>
            self-rated {u.verbalized_level}
          </span>
        )}
        <button
          onClick={() => setExpanded(e => !e)}
          style={{ marginLeft:'auto', fontSize:10, padding:'2px 6px',
                   background:'transparent', color:'var(--text-secondary)',
                   border:'1px solid var(--border)', borderRadius:3, cursor:'pointer',
                   fontFamily:'inherit' }}
        >
          {expanded ? 'Hide details' : 'Why?'}
        </button>
      </div>

      {/* Expandable reason */}
      {expanded && (
        <div style={{ marginTop:6, paddingTop:6, borderTop:`1px solid ${palette.border}22`,
                       color:'var(--text-secondary)', lineHeight:1.5 }}>
          {reason}
        </div>
      )}

      {/* Actions */}
      {u.suggest_web && (
        <div style={{ marginTop:8, display:'flex', gap:6 }}>
          <button
            onClick={handleVerify}
            disabled={retrying}
            style={{ display:'flex', alignItems:'center', gap:5,
                     fontSize:10, fontWeight:600, padding:'4px 10px',
                     background: palette.border, color:'white',
                     border:'none', borderRadius:3,
                     cursor: retrying ? 'wait' : 'pointer',
                     fontFamily:'inherit', opacity: retrying ? 0.7 : 1 }}
          >
            <svg width={10} height={10} viewBox="0 0 24 24" fill="none" stroke="currentColor"
                 strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="10"/>
              <line x1="2" y1="12" x2="22" y2="12"/>
              <path d="M12 2a15.3 15.3 0 014 10 15.3 15.3 0 01-4 10 15.3 15.3 0 01-4-10 15.3 15.3 0 014-10z"/>
            </svg>
            {retrying ? 'Re-asking...' : 'Verify with web search'}
          </button>
        </div>
      )}
    </div>
  )
}


// ── MaxThink reasoning chain panel — collapsible ────────────────────────────
const TASK_BADGE = {
  debug:    { label: 'Debug',     color: '#e05a52' },
  design:   { label: 'Design',    color: '#9b6dff' },
  sql_perf: { label: 'SQL Perf',  color: '#4caf6e' },
  refactor: { label: 'Refactor',  color: '#e0a052' },
  general:  { label: 'Reasoning', color: '#2677bf' },
  trivial:  { label: 'Quick',     color: '#888d93' },
}

function ReasoningPanel({ reasoning }) {
  const [open, setOpen] = useState(false)
  const badge = TASK_BADGE[reasoning.task_type] || TASK_BADGE.general
  const hasContent = reasoning.thinking || reasoning.plan

  if (!hasContent) return null

  return (
    <div style={{
      border: '1px solid var(--border)',
      borderLeft: `3px solid ${badge.color}`,
      borderRadius: 4,
      background: 'var(--surface-low, #2a2d2f)',
      marginBottom: 6,
      overflow: 'hidden',
    }}>
      {/* Header — click to expand */}
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        style={{
          display: 'flex', alignItems: 'center', gap: 8,
          width: '100%', padding: '6px 10px',
          background: 'transparent', border: 'none', cursor: 'pointer',
          color: 'var(--text-secondary)', fontSize: 11,
          fontFamily: 'inherit', textAlign: 'left',
        }}
      >
        <svg width={10} height={10} viewBox="0 0 24 24" fill="none" stroke="currentColor"
             strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round"
             style={{ transform: open ? 'rotate(90deg)' : 'rotate(0deg)', transition: 'transform 0.15s' }}>
          <path d="M9 18l6-6-6-6"/>
        </svg>
        <span>💭 Reasoning</span>
        <span style={{
          fontSize: 9, padding: '1px 6px', borderRadius: 8,
          background: `${badge.color}22`, color: badge.color,
          fontWeight: 600, letterSpacing: 0.3,
        }}>{badge.label}</span>
        {!open && reasoning.thinking && (
          <span style={{ color: 'var(--text-dim)', fontSize: 10, marginLeft: 'auto' }}>
            {reasoning.thinking.length.toLocaleString()} chars · click to expand
          </span>
        )}
      </button>

      {/* Body */}
      {open && (
        <div style={{ padding: '8px 12px 10px 12px', borderTop: '1px solid var(--border)' }}>
          {reasoning.plan && (
            <div style={{ marginBottom: 10 }}>
              <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--text-secondary)',
                            letterSpacing: 0.5, marginBottom: 4, textTransform: 'uppercase' }}>
                Plan
              </div>
              <pre style={{ fontSize: 11, color: 'var(--text-primary)',
                            fontFamily: "'JetBrains Mono', monospace",
                            whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                            margin: 0, lineHeight: 1.5 }}>
                {reasoning.plan}
              </pre>
            </div>
          )}
          {reasoning.thinking && (
            <div>
              <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--text-secondary)',
                            letterSpacing: 0.5, marginBottom: 4, textTransform: 'uppercase' }}>
                Thinking
              </div>
              <pre style={{ fontSize: 11, color: 'var(--text-primary)',
                            fontFamily: "'JetBrains Mono', monospace",
                            whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                            margin: 0, lineHeight: 1.5,
                            maxHeight: 360, overflowY: 'auto' }}>
                {reasoning.thinking}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}


// ── Thumbs up / thumbs down — feeds the conversation capture flywheel ───────
function FeedbackButtons({ chatId, msgId, persistedFeedback, query, response, files, reasoning }) {
  const setMessageFeedback = useStore(s => s.setMessageFeedback)

  // vote: null | 'up' | 'down' | 'error'
  // Initialize from the persisted feedback on the message so it survives refresh.
  const [vote, setVote]       = useState(persistedFeedback?.vote || null)
  const [showReason, setShow] = useState(false)
  const [reason, setReason]   = useState('')

  // If a reasoning chain exists, include it in the saved response so future
  // retrieval can show the full thinking pattern, not just the final answer.
  const enrichedResponse = reasoning?.thinking
    ? `${response}\n\n---\n\n[Reasoning chain — ${reasoning.task_type || 'general'}]\n` +
      (reasoning.plan ? `\nPLAN:\n${reasoning.plan}\n` : '') +
      (reasoning.thinking ? `\nTHINKING:\n${reasoning.thinking}` : '')
    : response

  const send = async (kind, reasonText = '') => {
    try {
      const url  = `/api/feedback/${kind === 'up' ? 'positive' : 'negative'}`
      const body = kind === 'up'
        ? { query, response: enrichedResponse, files: files || [] }
        : { query, response, reason: reasonText }
      const res = await fetch(url, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify(body),
      })
      if (!res.ok) throw new Error(await res.text())
      setVote(kind)
      // Persist the vote on the message so it survives refresh
      if (chatId && msgId) {
        setMessageFeedback(chatId, msgId, kind, reasonText)
      }
    } catch (e) {
      console.error('feedback failed', e)
      setVote('error')
      setTimeout(() => setVote(null), 2500)
    }
  }

  const btnStyle = (active, color) => ({
    display: 'flex', alignItems: 'center', gap: 4,
    fontSize: 10,
    color: active ? color : 'var(--text-dim)',
    background: 'transparent',
    border: `1px solid ${active ? color : 'transparent'}`,
    borderRadius: 3, padding: '2px 6px', cursor: vote ? 'default' : 'pointer',
    fontFamily: 'inherit', transition: 'all 0.12s',
  })

  // Already voted — show locked state
  if (vote === 'up') {
    return (
      <div style={btnStyle(true, 'var(--green, #4caf6e)')}>
        <svg width={10} height={10} viewBox="0 0 24 24" fill="currentColor"><path d="M2 21h4V9H2v12zm20-11c0-1.1-.9-2-2-2h-6.31l.95-4.57.03-.32c0-.41-.17-.79-.44-1.06L13.17 1 7.59 6.59C7.22 6.95 7 7.45 7 8v10c0 1.1.9 2 2 2h9c.83 0 1.54-.5 1.84-1.22l3.02-7.05c.09-.23.14-.47.14-.73v-1z"/></svg>
        Saved as good
      </div>
    )
  }
  if (vote === 'down') {
    return (
      <div style={btnStyle(true, '#e05a52')}>
        <svg width={10} height={10} viewBox="0 0 24 24" fill="currentColor"><path d="M22 3h-4v12h4V3zM2 14c0 1.1.9 2 2 2h6.31l-.95 4.57-.03.32c0 .41.17.79.44 1.06L10.83 23l5.59-5.59c.36-.36.58-.86.58-1.41V6c0-1.1-.9-2-2-2H6c-.83 0-1.54.5-1.84 1.22L1.14 12.27c-.09.23-.14.47-.14.73v1z"/></svg>
        Marked
      </div>
    )
  }
  if (vote === 'error') {
    return <div style={btnStyle(true, '#e05a52')}>Failed</div>
  }

  return (
    <>
      {/* Thumbs up */}
      <button
        onClick={() => send('up')}
        style={btnStyle(false, 'var(--green, #4caf6e)')}
        onMouseEnter={e => { e.currentTarget.style.color='var(--green, #4caf6e)'; e.currentTarget.style.borderColor='var(--border)' }}
        onMouseLeave={e => { e.currentTarget.style.color='var(--text-dim)'; e.currentTarget.style.borderColor='transparent' }}
        title="Save as good — this answer will be retrieved for similar future questions"
      >
        <svg width={10} height={10} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
          <path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"/>
        </svg>
        Good
      </button>

      {/* Thumbs down */}
      <button
        onClick={() => setShow(true)}
        style={btnStyle(false, '#e05a52')}
        onMouseEnter={e => { e.currentTarget.style.color='#e05a52'; e.currentTarget.style.borderColor='var(--border)' }}
        onMouseLeave={e => { e.currentTarget.style.color='var(--text-dim)'; e.currentTarget.style.borderColor='transparent' }}
        title="Mark as bad — this answer will be reviewed, not used"
      >
        <svg width={10} height={10} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
          <path d="M10 15v4a3 3 0 0 0 3 3l4-9V2H5.72a2 2 0 0 0-2 1.7l-1.38 9a2 2 0 0 0 2 2.3zM17 2h2.67A2.31 2.31 0 0 1 22 4v7a2.31 2.31 0 0 1-2.33 2H17"/>
        </svg>
        Bad
      </button>

      {/* Reason modal */}
      {showReason && (
        <div
          onClick={() => setShow(false)}
          style={{ position:'fixed', inset:0, background:'rgba(0,0,0,0.55)', display:'flex', alignItems:'center', justifyContent:'center', zIndex:999 }}
        >
          <div
            onClick={e => e.stopPropagation()}
            style={{ background:'var(--chrome-bg, #323639)', border:'1px solid var(--border)', borderRadius:6, padding:18, width:'min(420px, 90vw)', boxShadow:'0 12px 40px rgba(0,0,0,0.5)' }}
          >
            <div style={{ fontSize:13, fontWeight:600, color:'var(--text-primary)', marginBottom:10 }}>
              Why was this answer bad?
            </div>
            <textarea
              autoFocus
              value={reason}
              onChange={e => setReason(e.target.value)}
              placeholder="Optional — e.g. wrong API used, missed the question, broken code"
              style={{ width:'100%', minHeight:80, padding:8, fontSize:12, fontFamily:'inherit', background:'var(--surface-low, #2a2d2f)', color:'var(--text-primary)', border:'1px solid var(--border)', borderRadius:4, resize:'vertical', outline:'none' }}
            />
            <div style={{ display:'flex', justifyContent:'flex-end', gap:8, marginTop:12 }}>
              <button
                onClick={() => setShow(false)}
                style={{ fontSize:11, padding:'5px 12px', background:'transparent', color:'var(--text-secondary)', border:'1px solid var(--border)', borderRadius:3, cursor:'pointer', fontFamily:'inherit' }}
              >
                Cancel
              </button>
              <button
                onClick={() => { setShow(false); send('down', reason) }}
                style={{ fontSize:11, padding:'5px 12px', background:'#e05a52', color:'white', border:'none', borderRadius:3, cursor:'pointer', fontFamily:'inherit', fontWeight:600 }}
              >
                Submit
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

// ── Translation correction button — lets users contribute corrected translations ──
function TranslateCorrectionBtn({ source, draft, lang }) {
  const [open, setOpen]       = useState(false)
  const [target, setTarget]   = useState(draft || '')
  const [note, setNote]       = useState('')
  const [submitting, setSub]  = useState(false)
  const [result, setResult]   = useState(null)   // {ok, status, reasons}

  const submit = async () => {
    if (!target.trim() || target.trim() === (draft || '').trim()) return
    setSub(true)
    try {
      const res = await fetch('/api/translation/candidates', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ source, target, lang, draft, note }),
      })
      const data = await res.json()
      setResult(data)
      if (data.ok && data.status === 'pending') {
        setTimeout(() => { setOpen(false); setResult(null); setNote('') }, 2500)
      }
    } catch (e) {
      setResult({ ok: false, error: e.message })
    } finally { setSub(false) }
  }

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        title="Submit a corrected translation. It enters the review queue, not the live corpus."
        style={{ fontSize:10, padding:'2px 6px', background:'transparent',
                  color:'var(--text-dim)', border:'1px solid transparent',
                  borderRadius:3, cursor:'pointer', fontFamily:'inherit', display:'flex',
                  alignItems:'center', gap:4, transition:'all 0.12s' }}
        onMouseEnter={e => { e.currentTarget.style.color='#6dc4b0'; e.currentTarget.style.borderColor='var(--border)' }}
        onMouseLeave={e => { e.currentTarget.style.color='var(--text-dim)'; e.currentTarget.style.borderColor='transparent' }}
      >
        <svg width={10} height={10} viewBox="0 0 24 24" fill="none" stroke="currentColor"
             strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
          <path d="M12 20h9M16.5 3.5a2.121 2.121 0 113 3L7 19l-4 1 1-4L16.5 3.5z"/>
        </svg>
        Suggest better
      </button>

      {open && (
        <div onClick={() => setOpen(false)}
             style={{ position:'fixed', inset:0, background:'rgba(0,0,0,0.6)',
                       display:'flex', alignItems:'center', justifyContent:'center', zIndex:999 }}>
          <div onClick={e => e.stopPropagation()}
               style={{ background:'var(--chrome-bg, #323639)', border:'1px solid var(--border)',
                         borderLeft:'3px solid #6dc4b0', borderRadius:6, padding:18,
                         width:'min(620px, 92vw)', maxHeight:'85vh', overflowY:'auto',
                         boxShadow:'0 12px 40px rgba(0,0,0,0.5)' }}>

            <div style={{ display:'flex', alignItems:'center', gap:8, marginBottom:10 }}>
              <span style={{ fontSize:13, fontWeight:600, color:'var(--text-primary)' }}>
                Suggest a better {lang} translation
              </span>
              <span style={{ fontSize:9, padding:'2px 7px', borderRadius:8,
                              background:'rgba(109,196,176,0.2)', color:'#6dc4b0',
                              fontWeight:600, letterSpacing:0.4 }}>
                AWAITS REVIEW
              </span>
            </div>

            <div style={{ fontSize:11, color:'var(--text-secondary)', marginBottom:10, lineHeight:1.55 }}>
              Your contribution goes to a review queue, NOT the live corpus.
              Auto-checks (length, script, junk detection) screen out garbage.
              Approved corrections become few-shot examples for future translations.
            </div>

            <label style={{ fontSize:10, fontWeight:600, color:'var(--text-secondary)',
                             textTransform:'uppercase', letterSpacing:0.5 }}>Source</label>
            <pre style={{ fontFamily:"'JetBrains Mono', monospace", fontSize:11,
                            color:'var(--text-primary)', whiteSpace:'pre-wrap', wordBreak:'break-word',
                            margin:'4px 0 12px 0', padding:'8px 10px', borderRadius:3,
                            background:'var(--surface-low, #2a2d2f)', border:'1px solid var(--border)',
                            maxHeight:120, overflowY:'auto' }}>
              {source}
            </pre>

            <label style={{ fontSize:10, fontWeight:600, color:'var(--text-secondary)',
                             textTransform:'uppercase', letterSpacing:0.5 }}>Your {lang} translation</label>
            <textarea
              autoFocus
              value={target}
              onChange={e => setTarget(e.target.value)}
              placeholder={`Type the correct ${lang} translation...`}
              style={{ width:'100%', minHeight:140, padding:8, marginTop:4, marginBottom:10,
                        fontSize:12, fontFamily:'inherit', resize:'vertical',
                        background:'var(--surface-low, #2a2d2f)', color:'var(--text-primary)',
                        border:'1px solid var(--border)', borderRadius:3, outline:'none' }}
            />

            <label style={{ fontSize:10, fontWeight:600, color:'var(--text-secondary)',
                             textTransform:'uppercase', letterSpacing:0.5 }}>Note (optional)</label>
            <input
              type="text"
              value={note}
              onChange={e => setNote(e.target.value)}
              placeholder="e.g. 'Better tech term', 'Correct verb agreement'..."
              style={{ width:'100%', padding:8, marginTop:4, marginBottom:14,
                        fontSize:11, fontFamily:'inherit',
                        background:'var(--surface-low, #2a2d2f)', color:'var(--text-primary)',
                        border:'1px solid var(--border)', borderRadius:3, outline:'none' }}
            />

            {result && (
              <div style={{ fontSize:11, padding:8, marginBottom:10, borderRadius:3,
                              background: result.ok && result.status === 'pending'
                                ? 'rgba(76,175,110,0.12)' : 'rgba(224,160,82,0.12)',
                              border: `1px solid ${result.ok && result.status === 'pending'
                                ? 'rgba(76,175,110,0.4)' : 'rgba(224,160,82,0.4)'}`,
                              color:'var(--text-primary)' }}>
                {!result.ok && <>❌ Submission failed: {result.error}</>}
                {result.ok && result.status === 'pending' && (
                  <>✓ Added to review queue. It will be auto-screened then await your approval at <code>/translation/candidates</code>.</>
                )}
                {result.ok && result.status === 'rejected_auto' && (
                  <>
                    ⚠️ Auto-screening flagged this submission:
                    <ul style={{ margin:'4px 0 0 16px', padding:0 }}>
                      {(result.reasons || []).map((r, i) => <li key={i}>{r}</li>)}
                    </ul>
                  </>
                )}
              </div>
            )}

            <div style={{ display:'flex', justifyContent:'flex-end', gap:8 }}>
              <button
                onClick={() => setOpen(false)}
                style={{ fontSize:11, padding:'6px 12px', background:'transparent',
                          color:'var(--text-secondary)', border:'1px solid var(--border)',
                          borderRadius:3, cursor:'pointer', fontFamily:'inherit' }}
              >Cancel</button>
              <button
                onClick={submit}
                disabled={submitting || !target.trim()}
                style={{ fontSize:11, fontWeight:600, padding:'6px 14px',
                          background: submitting ? '#888' : '#6dc4b0',
                          color:'white', border:'none', borderRadius:3,
                          cursor: submitting ? 'wait' : 'pointer', fontFamily:'inherit' }}
              >
                {submitting ? 'Submitting…' : 'Submit for review'}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}


function CopyBtn({ text }) {
  const [copied, setCopied] = useState(false)
  const copy = () => {
    navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }
  return (
    <button
      onClick={copy}
      style={{
        display:'flex', alignItems:'center', gap:4,
        fontSize:10, color: copied ? 'var(--green)' : 'var(--text-dim)',
        background:'transparent', border:'none', cursor:'pointer',
        fontFamily:'inherit', padding:'2px 6px', borderRadius:3,
        border: '1px solid transparent',
        transition: 'all 0.12s',
      }}
      onMouseEnter={e => { if (!copied) { e.currentTarget.style.color='var(--text-secondary)'; e.currentTarget.style.borderColor='var(--border)' } }}
      onMouseLeave={e => { if (!copied) { e.currentTarget.style.color='var(--text-dim)'; e.currentTarget.style.borderColor='transparent' } }}
    >
      <svg width={10} height={10} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
        {copied
          ? <path d="M5 13l4 4L19 7"/>
          : <><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></>
        }
      </svg>
      {copied ? 'Copied' : 'Copy response'}
    </button>
  )
}
