import React, { useState, useRef, useEffect } from 'react'
import { useStore } from '../store'

const ACCEPT = '.pdf,.docx,.xlsx,.xls,.csv,.txt,.py,.js,.ts,.jsx,.tsx,.json,.md,.yaml,.toml,.html,.css,.rs,.go,.java,.cpp,.c,.sh'

export default function InputBar() {
  const [input, setInput]           = useState('')
  const [attachedFiles, setFiles]   = useState([])  // [{name, text}]
  const [uploading, setUploading]   = useState(false)
  const sendMessage                 = useStore(s => s.sendMessage)
  const streaming                   = useStore(s => s.streaming)
  const settings                    = useStore(s => s.settings)
  const setSettings                 = useStore(s => s.setSettings)
  const taRef                       = useRef(null)
  const fileInputRef                = useRef(null)

  useEffect(() => {
    const ta = taRef.current
    if (!ta) return
    ta.style.height = 'auto'
    ta.style.height = Math.min(ta.scrollHeight, 180) + 'px'
  }, [input])

  const submit = () => {
    const trimmed = input.trim()
    if (!trimmed || streaming) return
    setInput('')
    sendMessage(trimmed, attachedFiles)
    setFiles([])
  }

  const onKey = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit() }
  }

  const handleFiles = async (e) => {
    const files = Array.from(e.target.files || [])
    if (!files.length) return
    setUploading(true)
    try {
      const results = await Promise.all(files.map(async (file) => {
        const form = new FormData()
        form.append('file', file)
        const res = await fetch('/api/upload', { method: 'POST', body: form })
        if (!res.ok) throw new Error(`Upload failed: ${file.name}`)
        return res.json()
      }))
      setFiles(prev => {
        const existing = new Set(prev.map(f => f.name))
        const fresh = results.filter(r => !existing.has(r.name))
        return [...prev, ...fresh]
      })
    } catch (err) {
      console.error(err)
    } finally {
      setUploading(false)
      e.target.value = ''
    }
  }

  const CHIPS = [
    { key:'useWeb',  label:'Web',     icon:'M12 2a10 10 0 100 20A10 10 0 0012 2zm0 0c2.5 2.5 4 6 4 10s-1.5 7.5-4 10m0-20C9.5 4.5 8 8 8 12s1.5 7.5 4 10M2 12h20' },
    { key:'useRag',  label:'RAG',     icon:'M4 7c0-1.657 3.582-3 8-3s8 1.343 8 3v10c0 1.657-3.582 3-8 3s-8-1.343-8-3V7zm0 5c0 1.657 3.582 3 8 3s8-1.343 8-3' },
    { key:'useMem',  label:'Memory',  icon:'M9 3H5a2 2 0 00-2 2v4m6-6h10a2 2 0 012 2v4M9 3v18m0 0h10a2 2 0 002-2V9M9 21H5a2 2 0 01-2-2V9m0 0h18' },
    { key:'autoRun', label:'Auto-run',icon:'M5 3l14 9-14 9V3z' },
  ]

  return (
    <div style={{ borderTop:'1px solid var(--border)', background:'var(--chrome-bg)', padding:'9px 18px 12px', flexShrink:0 }}>

      {/* Attached file chips */}
      {attachedFiles.length > 0 && (
        <div style={{ display:'flex', flexWrap:'wrap', gap:5, marginBottom:7 }}>
          {attachedFiles.map(f => (
            <span key={f.name} style={{
              display:'inline-flex', alignItems:'center', gap:5,
              background:'var(--accent-dim)', border:'1px solid var(--accent-border)',
              borderRadius:3, padding:'2px 7px 2px 6px', fontSize:11, color:'#5b9dd1',
            }}>
              <FileIcon name={f.name} />
              {f.name}
              <span style={{ fontSize:9, color:'var(--text-muted)', marginLeft:2 }}>
                {(f.chars / 1000).toFixed(1)}k chars
              </span>
              <button
                onClick={() => setFiles(prev => prev.filter(x => x.name !== f.name))}
                style={{ background:'none', border:'none', cursor:'pointer', color:'var(--text-muted)', padding:'0 1px', lineHeight:1, fontSize:13, display:'flex' }}
                onMouseEnter={e => e.currentTarget.style.color='var(--red)'}
                onMouseLeave={e => e.currentTarget.style.color='var(--text-muted)'}
              >×</button>
            </span>
          ))}
        </div>
      )}

      {/* Chips row */}
      <div style={{ display:'flex', alignItems:'center', gap:5, marginBottom:7, flexWrap:'wrap' }}>
        {CHIPS.map(({ key, label, icon }) => (
          <button
            key={key}
            onClick={() => setSettings({ [key]: !settings[key] })}
            className={`toggle-chip ${settings[key] ? 'on' : ''}`}
          >
            <svg width={9} height={9} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
              <path d={icon} />
            </svg>
            {label}
          </button>
        ))}

        {/* Model selector */}
        <div style={{ marginLeft:'auto', display:'flex', alignItems:'center', gap:5 }}>
          <svg width={10} height={10} viewBox="0 0 24 24" fill="none" stroke="var(--text-muted)" strokeWidth={1.75} strokeLinecap="round" strokeLinejoin="round">
            <path d="M9 3H5a2 2 0 00-2 2v4m6-6h10a2 2 0 012 2v4M9 3v18m0 0h10a2 2 0 002-2V9M9 21H5a2 2 0 01-2-2V9m0 0h18" />
          </svg>
          <select
            value={settings.model}
            onChange={e => setSettings({ model: e.target.value })}
            style={{ background:'transparent', border:'none', fontSize:10, color:'var(--text-secondary)', outline:'none', cursor:'pointer', fontFamily:'inherit' }}
            onMouseEnter={e => e.currentTarget.style.color='var(--text-primary)'}
            onMouseLeave={e => e.currentTarget.style.color='var(--text-secondary)'}
          >
            <option value="maxcoder-fast">3B fast</option>
            <option value="maxcoder">7B quality</option>
          </select>
        </div>
      </div>

      {/* Input box */}
      <div className="input-wrap" style={{ display:'flex', alignItems:'flex-end', gap:4, padding:'5px 5px 5px 10px' }}>

        {/* Attach button */}
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept={ACCEPT}
          onChange={handleFiles}
          style={{ display:'none' }}
        />
        <button
          onClick={() => fileInputRef.current?.click()}
          disabled={uploading}
          title="Attach files (PDF, DOCX, XLSX, CSV, code files…)"
          style={{
            background:'none', border:'none', cursor: uploading ? 'wait' : 'pointer',
            color: uploading ? 'var(--accent)' : 'var(--text-dim)',
            display:'flex', alignItems:'center', padding:'2px 4px', borderRadius:3,
            flexShrink:0, marginBottom:3, transition:'color 0.12s',
          }}
          onMouseEnter={e => { if (!uploading) e.currentTarget.style.color='var(--text-primary)' }}
          onMouseLeave={e => { if (!uploading) e.currentTarget.style.color='var(--text-dim)' }}
        >
          {uploading
            ? <svg width={14} height={14} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round">
                <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83" style={{ animation:'spin 1s linear infinite', transformOrigin:'center' }}/>
              </svg>
            : <svg width={14} height={14} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.75} strokeLinecap="round" strokeLinejoin="round">
                <path d="M21.44 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48"/>
              </svg>
          }
        </button>

        <textarea
          ref={taRef}
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={onKey}
          placeholder="Ask MaxCoder to build anything…  (Shift+Enter for new line)"
          rows={1}
          className="input-textarea"
          style={{ padding:0, fontSize:13 }}
        />
        <button
          onClick={submit}
          disabled={!input.trim() || streaming}
          className="send-btn"
          style={{ marginBottom:1 }}
        >
          {streaming
            ? <svg width={11} height={11} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5} strokeLinecap="round">
                <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83" style={{ animation:'spin 1s linear infinite', transformOrigin:'center' }}/>
              </svg>
            : <svg width={12} height={12} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 19V5M5 12l7-7 7 7"/>
              </svg>
          }
        </button>
      </div>

      <style>{`@keyframes spin { from { transform: rotate(0deg) } to { transform: rotate(360deg) } }`}</style>
    </div>
  )
}

function FileIcon({ name = '' }) {
  const ext = name.split('.').pop().toLowerCase()
  const color = { pdf:'#e05a52', docx:'#2677bf', xlsx:'#4caf6e', xls:'#4caf6e', csv:'#4caf6e', py:'#e5c07b', js:'#e5c07b', ts:'#61afef', json:'#98c379', md:'#abb2bf' }[ext] || '#888d93'
  return (
    <svg width={10} height={10} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/>
    </svg>
  )
}
