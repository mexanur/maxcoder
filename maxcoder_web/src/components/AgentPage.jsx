import React, { useEffect, useState, useRef } from 'react'
import { useAgentStore } from '../agentStore'
import { useStore }      from '../store'
import MonacoEditor      from './MonacoEditor'
import DiffViewer        from './DiffViewer'
import LivePreview       from './LivePreview'
import SqlPanel          from './SqlPanel'
import HistoryPanel      from './HistoryPanel'
import ReactMarkdown     from 'react-markdown'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism'
import remarkGfm from 'remark-gfm'

// ── SVG icon helper ───────────────────────────────────────────────────────────
function Svg({ d, size = 14, style = {} }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth={1.75} strokeLinecap="round" strokeLinejoin="round"
      style={style}>
      <path d={d} />
    </svg>
  )
}

const IC = {
  plus:    'M12 4v16m8-8H4',
  trash:   'M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16',
  file:    'M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z',
  folder:  'M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V7z',
  code:    'M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4',
  diff:    'M9 3H5a2 2 0 00-2 2v4m6-6h10a2 2 0 012 2v4M9 3v18m0 0h10a2 2 0 002-2V9M9 21H5a2 2 0 01-2-2V9m0 0h18',
  eye:     'M15 12a3 3 0 11-6 0 3 3 0 016 0zM2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z',
  sql:     'M4 6h16M4 10h16M4 14h16M4 18h16',
  history: 'M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z',
  play:    'M5 3l14 9-14 9V3z',
  save:    'M17 21H7a2 2 0 01-2-2V5a2 2 0 012-2h7l5 5v11a2 2 0 01-2 2zM17 21v-8H7v8M7 3v5h8',
  vscode:  'M17.5 3.5L8 12l-4-3L2 10.5l6 5.5-6 5.5 2 1.5 4-3 9.5 8.5 2-1V4.5l-2-1z',
  send:    'M12 19l9 2-9-18-9 18 9-2zm0 0v-8',
  chevL:   'M15 18l-6-6 6-6',
  chevR:   'M9 18l6-6-6-6',
  robot:   'M12 2a2 2 0 012 2v1h3a2 2 0 012 2v10a2 2 0 01-2 2H7a2 2 0 01-2-2V7a2 2 0 012-2h3V4a2 2 0 012-2zm-2 9a1 1 0 102 0 1 1 0 00-2 0zm5 0a1 1 0 102 0 1 1 0 00-2 0zm-7 3h10',
  check:   'M5 13l4 4L19 7',
}

function extClr(path = '') {
  const e = path.split('.').pop().toLowerCase()
  return { py:'#e5c07b', js:'#e5c07b', jsx:'#56b6c2', ts:'#61afef', tsx:'#56b6c2', html:'#e06c75', css:'#c678dd', json:'#98c379', md:'#abb2bf', rs:'#e06c75', go:'#56b6c2', sh:'#98c379', sql:'#c678dd' }[e] || 'var(--text-muted)'
}

// ── Strip raw @@op blocks from agent output — show only prose summary ─────────
function cleanAgentContent(raw) {
  return raw
    // Remove @@CREATE / @@EDIT blocks (path + fenced code)
    .replace(/@@(CREATE|EDIT)\s+\S+\s*\n```[\s\S]*?```\n?/g, '')
    // Remove @@DELETE lines
    .replace(/@@DELETE\s+\S+\n?/g, '')
    // Replace @@RUN blocks with a compact inline indicator
    .replace(/@@RUN\s+(\S+)\s*\n```[\s\S]*?```\n?/g, (_, lang) =>
      `\n> ▶ Running \`${lang}\` code…\n`
    )
    .trim()
}

// ── Markdown renderer ─────────────────────────────────────────────────────────
function MdMsg({ content }) {
  const [copied, setCopied] = useState({})
  const copy = (code, id) => {
    navigator.clipboard.writeText(code)
    setCopied(p => ({ ...p, [id]: true }))
    setTimeout(() => setCopied(p => ({ ...p, [id]: false })), 1500)
  }

  const clean = cleanAgentContent(content)

  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      className="prose"
      components={{
        code({ inline, className, children }) {
          const lang = (className || '').replace('language-', '')
          const code = String(children).replace(/\n$/, '')
          if (inline) return (
            <code style={{ background:'#1a1b26', color:'#6b84ff', padding:'1px 5px', borderRadius:3, fontFamily:"'JetBrains Mono',monospace", fontSize:'10px', border:'1px solid #1e1f2e' }}>
              {code}
            </code>
          )
          const id = lang + code.slice(0, 20)
          return (
            <div className="code-block" style={{ margin:'6px 0', borderRadius:4 }}>
              <div className="code-block-header">
                <span>{lang || 'code'}</span>
                <button className="copy-btn" onClick={() => copy(code, id)}>
                  {copied[id] ? 'copied' : 'copy'}
                </button>
              </div>
              <SyntaxHighlighter style={oneDark} language={lang || 'text'} PreTag="div"
                customStyle={{ margin:0, background:'#0a0b10', fontSize:'11px', padding:'8px 10px', borderRadius:0 }}>
                {code}
              </SyntaxHighlighter>
            </div>
          )
        }
      }}
    >
      {clean || content}
    </ReactMarkdown>
  )
}

// ── Op badge ──────────────────────────────────────────────────────────────────
function OpBadge({ op }) {
  const cls   = { create:'create', edit:'edit', delete:'delete', run:'run' }[op.op] || 'edit'
  const label = { create:'Created', edit:'Edited', delete:'Deleted', run:'Ran' }[op.op] || op.op
  return (
    <span className={`op-badge ${cls}`}>
      {op.ok
        ? <>{label}: <span style={{ opacity:0.7 }}>{op.path || op.lang}</span></>
        : <>Failed: {op.path || op.msg}</>}
    </span>
  )
}

function formatDuration(ms) {
  const seconds = Math.max(0.1, ms / 1000)
  return `${seconds < 10 ? seconds.toFixed(1) : Math.round(seconds)}s`
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

// ═════════════════════════════════════════════════════════════════════════════
// EXPLORER SIDEBAR — projects + files combined
// ═════════════════════════════════════════════════════════════════════════════
function ExplorerSidebar({ onFileOpen, width = 248 }) {
  const { projects, activeProjectId, files, openFile, fetchProjects,
          createProject, deleteProject, setActiveProject,
          openFileByPath, deleteFilePath, clearAgentChat } = useAgentStore()
  const [naming,  setNaming]  = useState(false)
  const [name,    setName]    = useState('')
  const [projExp, setProjExp] = useState(true)
  const [fileExp, setFileExp] = useState(true)
  const inputRef = useRef(null)

  useEffect(() => { fetchProjects() }, [])
  useEffect(() => { if (naming) inputRef.current?.focus() }, [naming])

  const submit = async () => {
    if (!name.trim()) return
    await createProject(name.trim())
    clearAgentChat()
    setNaming(false); setName('')
  }

  const ffiles = files.filter(f => !f.is_dir)

  return (
    <div className="agent-explorer" style={{ width, flexShrink:0, display:'flex', flexDirection:'column', height:'100%', background:'var(--sidebar-bg)', borderRight:'1px solid var(--border)' }}>

      {/* PROJECTS section */}
      <div>
        <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between', padding:'0 10px', height:28, borderBottom:'1px solid var(--border)' }}>
          <button
            onClick={() => setProjExp(v => !v)}
            style={{ display:'flex', alignItems:'center', gap:5, background:'none', border:'none', cursor:'pointer', color:'var(--text-muted)', fontSize:10, fontWeight:600, letterSpacing:'0.07em', textTransform:'uppercase', fontFamily:'inherit' }}
            onMouseEnter={e => e.currentTarget.style.color='var(--text-primary)'}
            onMouseLeave={e => e.currentTarget.style.color='var(--text-muted)'}
          >
            <svg width={9} height={9} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5} strokeLinecap="round">
              <path d={projExp ? 'M19 9l-7 7-7-7' : 'M9 18l6-6-6-6'} />
            </svg>
            Projects
          </button>
          <button
            onClick={() => setNaming(v => !v)}
            style={{ background:'none', border:'none', cursor:'pointer', color: naming ? 'var(--accent)' : 'var(--text-muted)', display:'flex', borderRadius:3, padding:2 }}
            onMouseEnter={e => e.currentTarget.style.color='var(--text-primary)'}
            onMouseLeave={e => e.currentTarget.style.color=naming ? 'var(--accent)' : 'var(--text-muted)'}
            title="New project"
          >
            <Svg d={IC.plus} size={12} />
          </button>
        </div>

        {projExp && (
          <div>
            {naming && (
              <div style={{ padding:'4px 10px', borderBottom:'1px solid var(--border)' }}>
                <input
                  ref={inputRef}
                  value={name || ''}
                  onChange={e => setName(e.target.value)}
                  onKeyDown={e => { if (e.key==='Enter') submit(); if (e.key==='Escape') { setNaming(false); setName('') } }}
                  placeholder="Project name…"
                  style={{ width:'100%', background:'var(--chrome-deep)', border:'1px solid var(--border)', borderRadius:3, padding:'3px 7px', fontSize:11, color:'var(--text-primary)', outline:'none', fontFamily:'inherit' }}
                  onFocus={e => e.target.style.borderColor='#4f6ef750'}
                  onBlur={e => e.target.style.borderColor='var(--border)'}
                />
              </div>
            )}
            {projects.length === 0 && !naming && (
              <p style={{ fontSize:10, color:'var(--text-dim)', padding:'10px 12px', lineHeight:1.6 }}>No projects. Click + to create one.</p>
            )}
            {projects.map(p => (
              <div
                key={p.id}
                className={`tree-item ${p.id === activeProjectId ? 'active' : ''}`}
                style={{ justifyContent:'space-between', paddingRight:6, height:26 }}
                onClick={() => { setActiveProject(p.id); clearAgentChat() }}
              >
                <span style={{ overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap', flex:1, fontSize:12 }}>{p.name}</span>
                <button
                  onClick={e => { e.stopPropagation(); deleteProject(p.id) }}
                  className="del-btn"
                  style={{ opacity:0, background:'none', border:'none', cursor:'pointer', color:'var(--text-muted)', padding:'1px', borderRadius:3, display:'flex', flexShrink:0 }}
                  onMouseEnter={e => e.currentTarget.style.color='#ef4444'}
                  onMouseLeave={e => e.currentTarget.style.color='var(--text-muted)'}
                >
                  <Svg d={IC.trash} size={11} />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* FILES section */}
      <div style={{ borderTop:'1px solid var(--border)', display:'flex', flexDirection:'column', flex:1, overflow:'hidden' }}>
        <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between', padding:'0 10px', height:28, borderBottom:'1px solid var(--border)', flexShrink:0 }}>
          <button
            onClick={() => setFileExp(v => !v)}
            style={{ display:'flex', alignItems:'center', gap:5, background:'none', border:'none', cursor:'pointer', color:'var(--text-muted)', fontSize:10, fontWeight:600, letterSpacing:'0.07em', textTransform:'uppercase', fontFamily:'inherit' }}
            onMouseEnter={e => e.currentTarget.style.color='var(--text-primary)'}
            onMouseLeave={e => e.currentTarget.style.color='var(--text-muted)'}
          >
            <svg width={9} height={9} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5} strokeLinecap="round">
              <path d={fileExp ? 'M19 9l-7 7-7-7' : 'M9 18l6-6-6-6'} />
            </svg>
            Files
          </button>
          <span style={{ fontSize:10, color:'var(--text-dim)' }}>{ffiles.length}</span>
        </div>

        {fileExp && (
          <div style={{ flex:1, overflowY:'auto', fontFamily:"'JetBrains Mono',monospace" }}>
            {!activeProjectId && (
              <p style={{ fontSize:11, color:'var(--text-dim)', padding:'16px 12px', lineHeight:1.6 }}>Select a project to see files.</p>
            )}
            {activeProjectId && ffiles.length === 0 && (
              <p style={{ fontSize:11, color:'var(--text-dim)', padding:'16px 12px', lineHeight:1.6 }}>No files yet. <span style={{ color:'var(--accent)' }}>Ask the agent.</span></p>
            )}
            {ffiles.map(f => (
                <div
                  key={f.path}
                  className={`tree-item ${openFile?.path === f.path ? 'active' : ''}`}
                  style={{ justifyContent:'space-between', paddingRight:6, height:26 }}
                  onClick={() => { openFileByPath(f.path); onFileOpen?.() }}
                >
                  <div style={{ display:'flex', alignItems:'center', gap:5, overflow:'hidden', flex:1 }}>
                    <svg width={11} height={11} viewBox="0 0 24 24" fill="none" stroke={extClr(f.path)} strokeWidth={1.75} strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink:0 }}>
                      <path d={IC.file}/>
                    </svg>
                    <span style={{ overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap', fontSize:11 }}>{f.path}</span>
                  </div>
                  <button
                    onClick={e => { e.stopPropagation(); deleteFilePath(f.path) }}
                    className="del-btn"
                    style={{ opacity:0, background:'none', border:'none', cursor:'pointer', color:'var(--text-muted)', padding:'1px', borderRadius:3, display:'flex', flexShrink:0 }}
                    onMouseEnter={e => e.currentTarget.style.color='#ef4444'}
                    onMouseLeave={e => e.currentTarget.style.color='var(--text-muted)'}
                  >
                    <Svg d={IC.trash} size={11} />
                  </button>
                </div>
            ))}
          </div>
        )}
      </div>

      <style>{`.tree-item:hover .del-btn { opacity: 1 !important }`}</style>
    </div>
  )
}

// ═════════════════════════════════════════════════════════════════════════════
// EDITOR AREA
// ═════════════════════════════════════════════════════════════════════════════
function EditorArea() {
  const { openFile, saveFile, loadingFile, lastOps } = useAgentStore()
  const [tab,       setTab]       = useState('editor')
  const [draft,     setDraft]     = useState('')
  const [dirty,     setDirty]     = useState(false)
  const [prev,      setPrev]      = useState('')
  const [runResult, setRunResult] = useState(null)

  useEffect(() => {
    setDraft(openFile?.content || '')
    setDirty(false); setRunResult(null)
    if (tab !== 'sql' && tab !== 'history') setTab('editor')
  }, [openFile?.path])

  useEffect(() => {
    if (!openFile || !lastOps?.length) return
    const op = lastOps.find(o => o.path === openFile.path && o.op === 'edit')
    if (op) { setPrev(draft); setDraft(openFile.content); setDirty(false); setTab('diff') }
    const runOp = lastOps.find(o => o.op === 'run')
    if (runOp) setRunResult(runOp)
  }, [lastOps])

  const handleSave = async (val) => {
    if (!openFile) return
    await saveFile(openFile.path, val ?? draft)
    setDirty(false)
  }

  const handleRun = async () => {
    if (!openFile) return
    const lang = openFile.path.split('.').pop().toLowerCase()
    try {
      const r = await fetch('/api/run', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ code:draft, lang }) })
      const d = await r.json()
      setRunResult({ ...d, lang }); setTab('preview')
    } catch (e) {
      setRunResult({ ok:false, stderr:String(e), stdout:'', lang:'' }); setTab('preview')
    }
  }

  const lang       = openFile?.path?.split('.').pop().toLowerCase() || ''
  const isRunnable = ['python','javascript','bash','shell','go','rust','java'].includes(lang)
  const isVisual   = ['html','css','svg','md','markdown'].includes(lang)

  const TABS = [
    { id:'editor',  label:'Editor',  icon:IC.code    },
    { id:'diff',    label:'Diff',    icon:IC.diff    },
    { id:'preview', label:'Preview', icon:IC.eye     },
    { id:'sql',     label:'SQL',     icon:IC.sql     },
    { id:'history', label:'History', icon:IC.history },
  ]

  return (
    <div style={{ flex:1, display:'flex', flexDirection:'column', minWidth:0, minHeight:0, background:'var(--content-bg)' }}>

      {/* Tab bar */}
      <div className="editor-tab-bar">
        {openFile && (
          <span style={{ fontSize:11, fontFamily:"'JetBrains Mono',monospace", color:extClr(openFile.path), marginRight:8, flexShrink:0 }}>
            {openFile.path}
            {dirty && <span style={{ color:'var(--accent)', marginLeft:4 }}>●</span>}
          </span>
        )}
        <div style={{ width:1, height:14, background:'var(--border)', marginRight:6, flexShrink:0 }} />
        {TABS.map(t => (
          <button key={t.id} className={`editor-tab ${tab === t.id ? 'active' : ''}`} onClick={() => setTab(t.id)}>
            <Svg d={t.icon} size={11} />
            {t.label}
          </button>
        ))}
        <div style={{ flex:1 }} />

        {openFile && (isRunnable || isVisual) && (
          <button onClick={handleRun}
            style={{ display:'flex', alignItems:'center', gap:4, fontSize:11, padding:'3px 8px', borderRadius:4, background:'#22c55e12', border:'1px solid #22c55e25', color:'#22c55e', cursor:'pointer' }}
            onMouseEnter={e => e.currentTarget.style.background='#22c55e20'}
            onMouseLeave={e => e.currentTarget.style.background='#22c55e12'}>
            <Svg d={IC.play} size={11} /> Run
          </button>
        )}
        {dirty && (
          <button onClick={() => handleSave()}
            style={{ display:'flex', alignItems:'center', gap:4, fontSize:11, padding:'3px 8px', borderRadius:4, background:'#4f6ef715', border:'1px solid #4f6ef730', color:'#6b84ff', cursor:'pointer', marginLeft:4 }}
            onMouseEnter={e => e.currentTarget.style.background='#4f6ef725'}
            onMouseLeave={e => e.currentTarget.style.background='#4f6ef715'}>
            <Svg d={IC.save} size={11} /> Save
          </button>
        )}
        {openFile && (
          <button onClick={() => window.open(`vscode://file/${encodeURIComponent(openFile.path)}`)}
            style={{ display:'flex', alignItems:'center', gap:4, fontSize:11, padding:'3px 8px', borderRadius:4, background:'transparent', border:'1px solid var(--border)', color:'var(--text-muted)', cursor:'pointer', marginLeft:4 }}
            onMouseEnter={e => { e.currentTarget.style.borderColor='#2e3250'; e.currentTarget.style.color='var(--text-primary)' }}
            onMouseLeave={e => { e.currentTarget.style.borderColor='var(--border)'; e.currentTarget.style.color='var(--text-muted)' }}>
            <Svg d={IC.vscode} size={11} /> VS Code
          </button>
        )}
      </div>

      {/* Panel */}
      <div style={{ flex:1, minHeight:0, overflow:'hidden' }}>
        {tab === 'sql'     && <SqlPanel />}
        {tab === 'history' && <HistoryPanel />}
        {tab === 'editor' && (
          loadingFile
            ? <EmptyState label="Loading…" />
            : !openFile
              ? <EmptyState icon={IC.code} label="Select a file to edit" sub="or ask the agent to create one" />
              : <MonacoEditor path={openFile.path} value={draft}
                  onChange={v => { setDraft(v); setDirty(true) }}
                  onSave={handleSave} height="100%" />
        )}
        {tab === 'diff' && (
          prev && openFile
            ? <DiffViewer path={openFile.path} original={prev} modified={draft} height="100%" />
            : <EmptyState icon={IC.diff} label="No diff yet" sub="Diff appears after the agent edits a file" />
        )}
        {tab === 'preview' && openFile
          ? <LivePreview code={draft} lang={lang} runResult={runResult} />
          : tab === 'preview' && <EmptyState icon={IC.eye} label="Open a file first" />
        }
      </div>
    </div>
  )
}

function EmptyState({ icon, label, sub }) {
  return (
    <div style={{ display:'flex', flexDirection:'column', alignItems:'center', justifyContent:'center', height:'100%', gap:8 }}>
      {icon && <Svg d={icon} size={28} style={{ opacity:0.1, color:'var(--text-primary)' }} />}
      <p style={{ fontSize:12, color:'var(--text-muted)' }}>{label}</p>
      {sub && <p style={{ fontSize:11, color:'var(--text-dim)' }}>{sub}</p>}
    </div>
  )
}

// ═════════════════════════════════════════════════════════════════════════════
// AGENT CHAT — right panel (Cursor-style)
// ═════════════════════════════════════════════════════════════════════════════
const ATTACH_ACCEPT = '.pdf,.docx,.xlsx,.xls,.csv,.txt,.py,.js,.ts,.jsx,.tsx,.json,.md,.yaml,.toml,.html,.css,.rs,.go,.java,.cpp,.c,.sh'

function AgentChatPanel({ collapsed, onToggle }) {
  const { agentMessages, agentStreaming, sendAgentMessage, stopAgentGeneration, activeProjectId } = useAgentStore()
  const settings  = useStore(s => s.settings)
  const bottomRef = useRef(null)
  const [input, setInput]         = useState('')
  const [attachedFiles, setFiles] = useState([])
  const [uploading, setUploading] = useState(false)
  const taRef       = useRef(null)
  const fileInputRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior:'smooth' })
  }, [agentMessages.length, agentStreaming])

  useEffect(() => {
    const ta = taRef.current
    if (!ta) return
    ta.style.height = 'auto'
    ta.style.height = Math.min(ta.scrollHeight, 120) + 'px'
  }, [input])

  const send = () => {
    const t = input.trim()
    if (!t || agentStreaming) return
    let content = t
    if (attachedFiles.length > 0) {
      const ctx = attachedFiles
        .map(f => `[ATTACHED FILE: ${f.name}]\n\n${f.text}`)
        .join('\n\n---\n\n')
      content = `${ctx}\n\n---\n\nUser request: ${t}`
    }
    setInput('')
    setFiles([])
    sendAgentMessage(content, settings)
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
        return [...prev, ...results.filter(r => !existing.has(r.name))]
      })
    } catch (err) {
      console.error(err)
    } finally {
      setUploading(false)
      e.target.value = ''
    }
  }

  const EXAMPLES = [
    'Build a FastAPI todo app with SQLite',
    'Create a landing page with Tailwind CSS',
    'Write a Python web scraper',
  ]

  return (
    <div className={`agent-panel ${collapsed ? 'collapsed' : ''}`} style={{ width:'100%', overflow:'hidden' }}>

      {/* Header */}
      <div className="agent-panel-header">
        <Svg d={IC.robot} size={13} style={{ color:'var(--accent)', flexShrink:0 }} />
        <span style={{ fontSize:11, fontWeight:600, color:'var(--text-primary)', flex:1 }}>Agent</span>

        {agentStreaming && (
          <span style={{ display:'flex', alignItems:'center', gap:3, marginRight:6 }}>
            <span className="thinking-dot" />
            <span className="thinking-dot" />
            <span className="thinking-dot" />
          </span>
        )}

        <button
          onClick={onToggle}
          style={{ background:'none', border:'none', cursor:'pointer', color:'var(--text-muted)', display:'flex', borderRadius:3, padding:2 }}
          onMouseEnter={e => e.currentTarget.style.color='var(--text-primary)'}
          onMouseLeave={e => e.currentTarget.style.color='var(--text-muted)'}
          title={collapsed ? 'Open Agent' : 'Close Agent'}
        >
          <Svg d={IC.chevR} size={13} />
        </button>
      </div>

      {/* Messages */}
      <div style={{ flex:1, overflowY:'auto', padding:'10px 12px', display:'flex', flexDirection:'column', gap:8, minHeight:0 }}>
        {agentMessages.length === 0 && (
          <div style={{ paddingTop:16 }}>
            <p style={{ fontSize:11, color:'var(--text-muted)', marginBottom:10, lineHeight:1.6 }}>
              {activeProjectId ? 'Describe what to build or change.' : 'Select or create a project first.'}
            </p>
            <div style={{ display:'flex', flexDirection:'column', gap:5 }}>
              {EXAMPLES.map(ex => (
                <button key={ex} onClick={() => sendAgentMessage(ex, settings)}
                  style={{ fontSize:11, padding:'5px 10px', borderRadius:4, background:'var(--surface-low)', border:'1px solid var(--border)', color:'var(--text-muted)', cursor:'pointer', textAlign:'left', fontFamily:'inherit' }}
                  onMouseEnter={e => { e.currentTarget.style.borderColor='var(--accent-border)'; e.currentTarget.style.color='var(--text-primary)' }}
                  onMouseLeave={e => { e.currentTarget.style.borderColor='var(--border)'; e.currentTarget.style.color='var(--text-muted)' }}>
                  {ex}
                </button>
              ))}
            </div>
          </div>
        )}

        {agentMessages.map(msg => (
          <div key={msg.id} style={{ display:'flex', justifyContent: msg.role==='user' ? 'flex-end' : 'flex-start' }} className="msg-enter">
            {msg.role === 'user'
              ? <div className="msg-user">{msg.content}</div>
              : (
                <div style={{ maxWidth:'100%', display:'flex', flexDirection:'column', gap:4 }}>
                  <div className="msg-assistant">
                    <MdMsg content={msg.content || ''} />
                    {!msg.done && <span className="cursor" />}
                  </div>
                  {msg.ops?.length > 0 && (
                    <div style={{ display:'flex', flexWrap:'wrap', gap:3 }}>
                      {msg.ops.map((op, i) => <OpBadge key={i} op={op} />)}
                    </div>
                  )}
                  <span style={{ alignSelf:'flex-start' }}>
                    <ResponseTimer msg={msg} isStreaming={!msg.done && agentStreaming} />
                  </span>
                </div>
              )
            }
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div style={{ padding:'8px 10px 10px', flexShrink:0, borderTop:'1px solid var(--border)' }}>

        {/* Attached file chips */}
        {attachedFiles.length > 0 && (
          <div style={{ display:'flex', flexWrap:'wrap', gap:4, marginBottom:6 }}>
            {attachedFiles.map(f => (
              <span key={f.name} style={{
                display:'inline-flex', alignItems:'center', gap:4,
                background:'var(--accent-dim)', border:'1px solid var(--accent-border)',
                borderRadius:3, padding:'2px 6px 2px 5px', fontSize:10, color:'#5b9dd1',
              }}>
                <svg width={9} height={9} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
                  <path d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/>
                </svg>
                {f.name}
                <button
                  onClick={() => setFiles(prev => prev.filter(x => x.name !== f.name))}
                  style={{ background:'none', border:'none', cursor:'pointer', color:'var(--text-muted)', padding:0, lineHeight:1, fontSize:12, display:'flex' }}
                  onMouseEnter={e => e.currentTarget.style.color='var(--red)'}
                  onMouseLeave={e => e.currentTarget.style.color='var(--text-muted)'}
                >×</button>
              </span>
            ))}
          </div>
        )}

        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept={ATTACH_ACCEPT}
          onChange={handleFiles}
          style={{ display:'none' }}
        />

        <div className="input-wrap" style={{ display:'flex', alignItems:'flex-end', gap:6, padding:'6px 6px 6px 6px' }}>
          {/* Attach button */}
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading || !activeProjectId}
            className="attach-btn"
            title="Attach files"
            style={{
              background:'none', border:'none',
              cursor: (uploading || !activeProjectId) ? 'not-allowed' : 'pointer',
              color:'var(--text-dim)', flexShrink:0,
              marginBottom:1, opacity: !activeProjectId ? 0.4 : 1,
              transition:'color 0.12s, background 0.12s',
            }}
            onMouseEnter={e => { if (activeProjectId && !uploading) e.currentTarget.style.color='var(--text-primary)' }}
            onMouseLeave={e => e.currentTarget.style.color='var(--text-dim)'}
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.75} strokeLinecap="round" strokeLinejoin="round">
              <path d="M21.44 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48"/>
            </svg>
          </button>

          <textarea
            ref={taRef}
            className="input-textarea"
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                if (agentStreaming) stopAgentGeneration()
                else                send()
              }
              if (e.key === 'Escape' && agentStreaming) {
                e.preventDefault()
                stopAgentGeneration()
              }
            }}
            placeholder={activeProjectId ? 'Describe what to build…' : 'Select a project first…'}
            disabled={!activeProjectId}
            rows={1}
            style={{ padding:'4px 0 4px 6px', fontSize:12 }}
          />
          {agentStreaming ? (
            <button
              className="send-btn stop-btn"
              onClick={stopAgentGeneration}
              title="Stop generation (Esc)"
              style={{
                marginBottom: 2, marginRight: 2,
                background: '#e05a52', borderColor: '#e05a52', color: 'white',
              }}
            >
              <svg width={11} height={11} viewBox="0 0 24 24" fill="currentColor" stroke="none">
                <rect x="6" y="6" width="12" height="12" rx="2"/>
              </svg>
            </button>
          ) : (
            <button
              className="send-btn"
              onClick={send}
              disabled={!input.trim() || !activeProjectId}
              title="Send (Enter)"
              style={{ marginBottom: 2, marginRight: 2 }}
            >
              <Svg d={IC.send} size={12} />
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Collapsed toggle button in editor tab bar ─────────────────────────────────
function AgentToggleBtn({ onClick }) {
  return (
    <button
      onClick={onClick}
      style={{ display:'flex', alignItems:'center', gap:4, fontSize:11, padding:'3px 8px', borderRadius:4, background:'#4f6ef712', border:'1px solid #4f6ef730', color:'#6b84ff', cursor:'pointer' }}
      onMouseEnter={e => e.currentTarget.style.background='#4f6ef722'}
      onMouseLeave={e => e.currentTarget.style.background='#4f6ef712'}
      title="Open Agent panel"
    >
      <Svg d={IC.robot} size={11} />
      Agent
    </button>
  )
}

// ═════════════════════════════════════════════════════════════════════════════
// ROOT
// ═════════════════════════════════════════════════════════════════════════════
export default function AgentPage() {
  const [agentOpen, setAgentOpen] = useState(true)
  const [explorerWidth, setExplorerWidth] = useState(248)
  const [chatWidth, setChatWidth] = useState(560)
  const [dragging, setDragging] = useState(false)
  const rootRef = useRef(null)
  const dragRef = useRef(null)
  const widthRef = useRef({ explorer: 248, chat: 560 })

  useEffect(() => {
    widthRef.current = { explorer: explorerWidth, chat: chatWidth }
  }, [explorerWidth, chatWidth])

  useEffect(() => {
    const clamp = (value, min, max) => Math.min(Math.max(value, min), max)

    const onMove = (e) => {
      const drag = dragRef.current
      if (!drag) return
      const rect = rootRef.current?.getBoundingClientRect()
      if (!rect) return
      const widths = widthRef.current

      if (drag.type === 'explorer') {
        const maxExplorer = Math.max(200, rect.width - widths.chat - 16 - 420)
        setExplorerWidth(clamp(e.clientX - rect.left, 200, Math.min(380, maxExplorer)))
      }

      if (drag.type === 'chat') {
        const maxChat = Math.max(340, rect.width - widths.explorer - 16 - 420)
        setChatWidth(clamp(rect.right - e.clientX, 340, Math.min(860, maxChat)))
      }
    }

    const onUp = () => {
      if (!dragRef.current) return
      dragRef.current = null
      setDragging(false)
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
    }

    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    return () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
  }, [])

  const startDrag = (type, e) => {
    e.preventDefault()
    dragRef.current = {
      type,
      startX: e.clientX,
      startExplorer: explorerWidth,
      startChat: chatWidth,
    }
    setDragging(true)
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
  }

  return (
    <div
      ref={rootRef}
      style={{
        display:'grid',
        gridTemplateColumns: agentOpen
          ? `${explorerWidth}px 8px minmax(0,1fr) 8px ${chatWidth}px`
          : `${explorerWidth}px 8px minmax(0,1fr) 0px 0px`,
        height:'100%',
        background:'var(--content-bg)',
        overflow:'hidden',
        position:'relative',
      }}
    >
      {dragging && (
        <div
          style={{
            position:'absolute',
            inset:0,
            zIndex:1000,
            cursor:'col-resize',
            background:'transparent',
          }}
        />
      )}

      {/* Left: Explorer */}
      <ExplorerSidebar width={explorerWidth} />

      {/* Explorer resizer */}
      <div
        onMouseDown={(e) => startDrag('explorer', e)}
        title="Resize explorer"
        style={{
          width: 8,
          cursor: 'col-resize',
          flexShrink: 0,
          background: 'linear-gradient(90deg, transparent 0, transparent 3px, var(--border) 3px, var(--border) 4px, transparent 4px)',
        }}
      />

      {/* Center: Editor */}
      <div style={{ display:'flex', flexDirection:'column', minWidth:0, minHeight:0, position:'relative' }}>
        <EditorArea />

        {/* Show agent toggle btn in editor when panel is closed */}
        {!agentOpen && (
          <div style={{ position:'absolute', top:4, right:8, zIndex:10 }}>
            <AgentToggleBtn onClick={() => setAgentOpen(true)} />
          </div>
        )}
      </div>

      {/* Chat resizer */}
      {agentOpen && (
        <div
          onMouseDown={(e) => startDrag('chat', e)}
          title="Resize agent chat"
          style={{
            width: 8,
            cursor: 'col-resize',
            flexShrink: 0,
            background: 'linear-gradient(90deg, transparent 0, transparent 3px, var(--border) 3px, var(--border) 4px, transparent 4px)',
          }}
        />
      )}

      {/* Right: Agent Chat panel */}
      <AgentChatPanel
        collapsed={!agentOpen}
        onToggle={() => setAgentOpen(v => !v)}
      />
    </div>
  )
}

