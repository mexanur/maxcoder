import React, { useState } from 'react'
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

export default function MessageBubble({ msg, isStreaming }) {
  const isUser = msg.role === 'user'
  const { blocks: genBlocks, clean: cleanContent } = isUser
    ? { blocks: [], clean: msg.content }
    : parseGenerateBlocks(msg.content || '')

  return (
    <div className={`chat-row ${isUser ? 'chat-row-user' : 'chat-row-assistant'} msg-enter`}>

      {/* Sender label */}
      <div className="chat-sender">
        <span className={`sender-dot ${isUser ? 'sender-dot-user' : 'sender-dot-ai'}`} />
        {isUser ? 'You' : 'MaxCoder'}
      </div>

      {/* Attached file chips */}
      {msg.files?.length > 0 && (
        <div style={{ display:'flex', flexWrap:'wrap', gap:5, marginBottom:4 }}>
          {msg.files.map(f => <FileChip key={f.name} file={f} />)}
        </div>
      )}

      {/* Generated file download cards */}
      {genBlocks.map((b, i) => (
        <GeneratedFileCard key={i} fmt={b.fmt} content={b.content} />
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

      {/* Actions row */}
      {msg.done && !isUser && (
        <div style={{ display:'flex', alignItems:'center', gap:8, marginTop:4, flexWrap:'wrap' }}>
          <CopyBtn text={msg.content} />
        </div>
      )}
    </div>
  )
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
