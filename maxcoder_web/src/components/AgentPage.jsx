/**
 * AgentPage — Step 2 UI redesign
 * Cursor-quality layout: tight panels, flat tabs, clean typography
 */
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
function Svg({ d, size = 14, className = '' }) {
  return (
    <svg
      width={size} height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.75}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
    >
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
  play:    'M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664zM21 12a9 9 0 11-18 0 9 9 0 0118 0z',
  save:    'M17 21H7a2 2 0 01-2-2V5a2 2 0 012-2h7l5 5v11a2 2 0 01-2 2zM17 21v-8H7v8M7 3v5h8',
  vscode:  'M17.5 3.5L8 12l-4-3L2 10.5l6 5.5-6 5.5 2 1.5 4-3 9.5 8.5 2-1V4.5l-2-1z',
  send:    'M12 19l9 2-9-18-9 18 9-2zm0 0v-8',
  chevron: 'M19 9l-7 7-7-7',
  check:   'M5 13l4 4L19 7',
  x:       'M6 18L18 6M6 6l12 12',
  robot:   'M12 2a2 2 0 012 2v1h3a2 2 0 012 2v10a2 2 0 01-2 2H7a2 2 0 01-2-2V7a2 2 0 012-2h3V4a2 2 0 012-2zm-2 9a1 1 0 102 0 1 1 0 00-2 0zm5 0a1 1 0 102 0 1 1 0 00-2 0zm-7 3h10',
}

// file extension → dim colour (subtle, not garish)
function extClr(path = '') {
  const e = path.split('.').pop().toLowerCase()
  return {
    py:'#e5c07b', js:'#e5c07b', jsx:'#56b6c2', ts:'#61afef', tsx:'#56b6c2',
    html:'#e06c75', css:'#c678dd', json:'#98c379', md:'#abb2bf',
    rs:'#e06c75', go:'#56b6c2', sh:'#98c379', sql:'#c678dd',
  }[e] || '#6c7086'
}

// ── Markdown renderer ─────────────────────────────────────────────────────────
function MdMsg({ content }) {
  const [copied, setCopied] = useState({})
  const copy = (code, id) => {
    navigator.clipboard.writeText(code)
    setCopied(p => ({ ...p, [id]: true }))
    setTimeout(() => setCopied(p => ({ ...p, [id]: false })), 1500)
  }
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      className="prose"
      components={{
        code({ inline, className, children }) {
          const lang = (className || '').replace('language-', '')
          const code = String(children).replace(/\n$/, '')
          if (inline) return <code>{code}</code>
          const id = lang + code.slice(0, 20)
          return (
            <div className="code-block">
              <div className="code-block-header">
                <span>{lang || 'code'}</span>
                <button className="copy-btn" onClick={() => copy(code, id)}>
                  {copied[id] ? 'copied' : 'copy'}
                </button>
              </div>
              <SyntaxHighlighter
                style={oneDark}
                language={lang || 'text'}
                PreTag="div"
                customStyle={{
                  margin: 0, background: '#0a0b10',
                  fontSize: '11px', padding: '10px 12px',
                  borderRadius: 0,
                }}
              >
                {code}
              </SyntaxHighlighter>
            </div>
          )
        }
      }}
    >
      {content}
    </ReactMarkdown>
  )
}

// ── Op badge ──────────────────────────────────────────────────────────────────
function OpBadge({ op }) {
  const cls = { create:'create', edit:'edit', delete:'delete', run:'run' }[op.op] || 'edit'
  const label = { create:'Created', edit:'Edited', delete:'Deleted', run:'Ran' }[op.op] || op.op
  return (
    <span className={`op-badge ${cls}`}>
      {op.ok
        ? <>{label}: <span style={{ opacity: 0.75 }}>{op.path || op.lang}</span></>
        : <>Failed: {op.path || op.msg}</>
      }
    </span>
  )
}

// ═════════════════════════════════════════════════════════════════════════════
// PROJECT SIDEBAR
// ═════════════════════════════════════════════════════════════════════════════
function ProjectSidebar() {
  const { projects, activeProjectId, fetchProjects,
          createProject, deleteProject, setActiveProject,
          clearAgentChat } = useAgentStore()
  const [naming, setNaming] = useState(false)
  const [name,   setName]   = useState('')
  const inputRef = useRef(null)

  useEffect(() => { fetchProjects() }, [])
  useEffect(() => { if (naming) inputRef.current?.focus() }, [naming])

  const submit = async () => {
    if (!name.trim()) return
    await createProject(name.trim())
    clearAgentChat()
    setNaming(false); setName('')
  }

  return (
    <div className="flex flex-col h-full panel-border-r" style={{ width: 148, background: '#0d0e14', flexShrink: 0 }}>

      {/* Header */}
      <div className="flex items-center justify-between px-3 panel-border-b" style={{ height: 34 }}>
        <span className="section-label">Projects</span>
        <button
          onClick={() => setNaming(v => !v)}
          style={{ color: naming ? '#4f6ef7' : '#6c7086', padding: '2px', borderRadius: 3, background: 'transparent', border: 'none', cursor: 'pointer', display: 'flex' }}
          onMouseEnter={e => e.currentTarget.style.color = '#cdd6f4'}
          onMouseLeave={e => e.currentTarget.style.color = naming ? '#4f6ef7' : '#6c7086'}
        >
          <Svg d={IC.plus} size={13} />
        </button>
      </div>

      {/* New project input */}
      {naming && (
        <div className="px-2 py-1.5 panel-border-b">
          <input
            ref={inputRef}
            value={name}
            onChange={e => setName(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') submit(); if (e.key === 'Escape') { setNaming(false); setName('') } }}
            placeholder="Project name…"
            style={{
              width: '100%', background: '#1a1b26', border: '1px solid #1e1f2e',
              borderRadius: 4, padding: '3px 8px', fontSize: 11,
              color: '#cdd6f4', outline: 'none',
            }}
            onFocus={e => e.target.style.borderColor = '#4f6ef750'}
            onBlur={e => e.target.style.borderColor = '#1e1f2e'}
          />
        </div>
      )}

      {/* List */}
      <div style={{ flex: 1, overflowY: 'auto' }}>
        {projects.length === 0 && (
          <p style={{ fontSize: 10, color: '#6c7086', textAlign: 'center', padding: '20px 10px', lineHeight: 1.6 }}>
            No projects.<br />Click + to start.
          </p>
        )}
        {projects.map(p => (
          <div
            key={p.id}
            className={`tree-item ${p.id === activeProjectId ? 'active' : ''}`}
            style={{ justifyContent: 'space-between', paddingRight: 6 }}
            onClick={() => { setActiveProject(p.id); clearAgentChat() }}
          >
            <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }}>
              {p.name}
            </span>
            <button
              onClick={e => { e.stopPropagation(); deleteProject(p.id) }}
              style={{
                opacity: 0, background: 'none', border: 'none', cursor: 'pointer',
                color: '#6c7086', padding: '1px', borderRadius: 3, display: 'flex', flexShrink: 0,
              }}
              onMouseEnter={e => { e.currentTarget.style.opacity = '1'; e.currentTarget.style.color = '#ef4444' }}
              onMouseLeave={e => { e.currentTarget.style.opacity = '0'; e.currentTarget.style.color = '#6c7086' }}
              className="del-btn"
            >
              <Svg d={IC.trash} size={11} />
            </button>
          </div>
        ))}
      </div>

      <style>{`.tree-item:hover .del-btn { opacity: 1 !important }`}</style>
    </div>
  )
}

// ═════════════════════════════════════════════════════════════════════════════
// FILE TREE
// ═════════════════════════════════════════════════════════════════════════════
function FileTree({ onOpen }) {
  const { files, openFile, openFileByPath, deleteFilePath, activeProjectId } = useAgentStore()

  if (!activeProjectId) return (
    <div className="panel-border-r" style={{ width: 192, flexShrink: 0, background: '#0d0e14', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <span style={{ fontSize: 11, color: '#6c7086' }}>No project selected</span>
    </div>
  )

  const dirs   = files.filter(f => f.is_dir)
  const ffiles = files.filter(f => !f.is_dir)

  return (
    <div className="flex flex-col panel-border-r" style={{ width: 192, flexShrink: 0, background: '#0d0e14' }}>

      {/* Header */}
      <div className="flex items-center justify-between px-3 panel-border-b" style={{ height: 34 }}>
        <span className="section-label">Files</span>
        <span style={{ fontSize: 10, color: '#6c7086' }}>{ffiles.length}</span>
      </div>

      {/* Tree */}
      <div style={{ flex: 1, overflowY: 'auto', fontFamily: "'JetBrains Mono', monospace" }}>
        {files.length === 0 && (
          <div style={{ textAlign: 'center', padding: '24px 12px' }}>
            <p style={{ fontSize: 11, color: '#6c7086', lineHeight: 1.7 }}>
              No files yet.<br />
              <span style={{ color: '#4f6ef7' }}>Ask the agent.</span>
            </p>
          </div>
        )}

        {dirs.map(d => (
          <div key={d.path} className="tree-item" style={{ gap: 5, cursor: 'default' }}>
            <Svg d={IC.folder} size={12} className="" style={{ color: '#e5c07b', flexShrink: 0 }} />
            <span style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{d.path}</span>
          </div>
        ))}

        {ffiles.map(f => (
          <div
            key={f.path}
            className={`tree-item ${openFile?.path === f.path ? 'active' : ''}`}
            style={{ justifyContent: 'space-between', paddingRight: 6 }}
            onClick={() => { openFileByPath(f.path); onOpen?.(f.path) }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 5, overflow: 'hidden', flex: 1 }}>
              <svg width={12} height={12} viewBox="0 0 24 24" fill="none" stroke={extClr(f.path)} strokeWidth={1.75} strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
                <path d={IC.file} />
              </svg>
              <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{f.path}</span>
            </div>
            <button
              onClick={e => { e.stopPropagation(); deleteFilePath(f.path) }}
              className="del-btn"
              style={{ opacity: 0, background: 'none', border: 'none', cursor: 'pointer', color: '#6c7086', padding: '1px', borderRadius: 3, display: 'flex', flexShrink: 0 }}
              onMouseEnter={e => { e.currentTarget.style.color = '#ef4444' }}
              onMouseLeave={e => { e.currentTarget.style.color = '#6c7086' }}
            >
              <Svg d={IC.trash} size={11} />
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}

// ═════════════════════════════════════════════════════════════════════════════
// EDITOR AREA
// ═════════════════════════════════════════════════════════════════════════════
function EditorArea() {
  const { openFile, saveFile, loadingFile, lastOps } = useAgentStore()
  const [tab,      setTab]      = useState('editor')
  const [draft,    setDraft]    = useState('')
  const [dirty,    setDirty]    = useState(false)
  const [prev,     setPrev]     = useState('')
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
      const r = await fetch('/api/run', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code: draft, lang }),
      })
      const d = await r.json()
      setRunResult({ ...d, lang }); setTab('preview')
    } catch (e) {
      setRunResult({ ok: false, stderr: String(e), stdout: '', lang: '' }); setTab('preview')
    }
  }

  const lang       = openFile?.path?.split('.').pop().toLowerCase() || ''
  const isVisual   = ['html','css','svg','md','markdown'].includes(lang)
  const isRunnable = ['python','javascript','bash','shell','go','rust','java'].includes(lang)

  const TABS = [
    { id: 'editor',  label: 'Editor',  icon: IC.code    },
    { id: 'diff',    label: 'Diff',    icon: IC.diff    },
    { id: 'preview', label: 'Preview', icon: IC.eye     },
    { id: 'sql',     label: 'SQL',     icon: IC.sql     },
    { id: 'history', label: 'History', icon: IC.history },
  ]

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, minHeight: 0, background: '#0d0e14' }}>

      {/* Tab bar */}
      <div className="editor-tab-bar">
        {/* File path breadcrumb */}
        {openFile && (
          <span style={{
            fontSize: 11, fontFamily: "'JetBrains Mono', monospace",
            color: extClr(openFile.path), marginRight: 10, flexShrink: 0,
          }}>
            {openFile.path}
            {dirty && <span style={{ color: '#4f6ef7', marginLeft: 4 }}>●</span>}
          </span>
        )}

        <div style={{ width: 1, height: 14, background: '#1e1f2e', marginRight: 6, flexShrink: 0 }} />

        {TABS.map(t => (
          <button
            key={t.id}
            className={`editor-tab ${tab === t.id ? 'active' : ''}`}
            onClick={() => setTab(t.id)}
          >
            <Svg d={t.icon} size={11} />
            {t.label}
          </button>
        ))}

        <div style={{ flex: 1 }} />

        {/* Action buttons */}
        {openFile && (isRunnable || isVisual) && (
          <button
            onClick={handleRun}
            style={{
              display: 'flex', alignItems: 'center', gap: 4,
              fontSize: 11, padding: '3px 8px', borderRadius: 4,
              background: '#22c55e12', border: '1px solid #22c55e25',
              color: '#22c55e', cursor: 'pointer',
            }}
            onMouseEnter={e => e.currentTarget.style.background = '#22c55e20'}
            onMouseLeave={e => e.currentTarget.style.background = '#22c55e12'}
          >
            <Svg d={IC.play} size={11} /> Run
          </button>
        )}

        {dirty && (
          <button
            onClick={() => handleSave()}
            style={{
              display: 'flex', alignItems: 'center', gap: 4,
              fontSize: 11, padding: '3px 8px', borderRadius: 4,
              background: '#4f6ef715', border: '1px solid #4f6ef730',
              color: '#6b84ff', cursor: 'pointer', marginLeft: 4,
            }}
            onMouseEnter={e => e.currentTarget.style.background = '#4f6ef725'}
            onMouseLeave={e => e.currentTarget.style.background = '#4f6ef715'}
          >
            <Svg d={IC.save} size={11} /> Save
          </button>
        )}

        {openFile && (
          <button
            onClick={() => window.open(`vscode://file/${encodeURIComponent(openFile.path)}`)}
            style={{
              display: 'flex', alignItems: 'center', gap: 4,
              fontSize: 11, padding: '3px 8px', borderRadius: 4,
              background: 'transparent', border: '1px solid #1e1f2e',
              color: '#6c7086', cursor: 'pointer', marginLeft: 4,
            }}
            onMouseEnter={e => { e.currentTarget.style.borderColor = '#2e3250'; e.currentTarget.style.color = '#cdd6f4' }}
            onMouseLeave={e => { e.currentTarget.style.borderColor = '#1e1f2e'; e.currentTarget.style.color = '#6c7086' }}
          >
            <Svg d={IC.vscode} size={11} /> VS Code
          </button>
        )}
      </div>

      {/* Panel */}
      <div style={{ flex: 1, minHeight: 0, overflow: 'hidden' }}>
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
            : <EmptyState icon={IC.diff} label="No diff yet" sub="Diff appears automatically after the agent edits a file" />
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
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', gap: 8 }}>
      {icon && <Svg d={icon} size={28} style={{ opacity: 0.12, color: '#cdd6f4' }} />}
      <p style={{ fontSize: 12, color: '#6c7086' }}>{label}</p>
      {sub && <p style={{ fontSize: 11, color: '#313244' }}>{sub}</p>}
    </div>
  )
}

// ═════════════════════════════════════════════════════════════════════════════
// AGENT CHAT — collapsible bottom panel
// ═════════════════════════════════════════════════════════════════════════════
function AgentChat({ collapsed, onToggle }) {
  const { agentMessages, agentStreaming, sendAgentMessage, activeProjectId } = useAgentStore()
  const settings  = useStore(s => s.settings)
  const bottomRef = useRef(null)
  const [input, setInput] = useState('')

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [agentMessages.length, agentStreaming])

  const send = () => {
    const t = input.trim()
    if (!t || agentStreaming) return
    setInput('')
    sendAgentMessage(t, settings)
  }

  const EXAMPLES = [
    'Build a FastAPI todo app with SQLite',
    'Create a landing page with Tailwind CSS',
    'Write a Python web scraper',
  ]

  return (
    <div style={{
      display: 'flex', flexDirection: 'column',
      flexShrink: 0,
      height: collapsed ? 32 : 280,
      transition: 'height 0.2s ease',
      background: '#0d0e14',
    }}>

      {/* Handle */}
      <div
        className="agent-chat-handle"
        onClick={onToggle}
        style={{ height: 32 }}
      >
        <Svg d={IC.robot} size={12} style={{ color: '#4f6ef7' }} />
        <span style={{ fontSize: 11, fontWeight: 500, color: '#cdd6f4' }}>Agent Chat</span>

        {activeProjectId && (
          <span style={{ fontSize: 10, color: '#6c7086', fontFamily: 'monospace', marginLeft: 4, overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: 120 }}>
            — {activeProjectId.slice(0, 8)}…
          </span>
        )}

        {agentStreaming && (
          <span style={{ display: 'flex', alignItems: 'center', gap: 3, marginLeft: 6 }}>
            <span className="thinking-dot" />
            <span className="thinking-dot" />
            <span className="thinking-dot" />
          </span>
        )}

        <svg
          width={12} height={12} viewBox="0 0 24 24" fill="none"
          stroke="#6c7086" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round"
          style={{ marginLeft: 'auto', transform: collapsed ? 'none' : 'rotate(180deg)', transition: 'transform 0.2s' }}
        >
          <path d={IC.chevron} />
        </svg>
      </div>

      {/* Body */}
      {!collapsed && (
        <>
          {/* Messages */}
          <div style={{ flex: 1, overflowY: 'auto', padding: '8px 14px', display: 'flex', flexDirection: 'column', gap: 8, minHeight: 0 }}>

            {agentMessages.length === 0 && (
              <div style={{ textAlign: 'center', paddingTop: 16 }}>
                <p style={{ fontSize: 11, color: '#6c7086', marginBottom: 10 }}>
                  Describe what to build or change.
                </p>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, justifyContent: 'center' }}>
                  {EXAMPLES.map(ex => (
                    <button
                      key={ex}
                      onClick={() => sendAgentMessage(ex, settings)}
                      style={{
                        fontSize: 10, padding: '4px 10px', borderRadius: 4,
                        background: '#12131a', border: '1px solid #1e1f2e',
                        color: '#6c7086', cursor: 'pointer',
                      }}
                      onMouseEnter={e => { e.currentTarget.style.borderColor = '#4f6ef750'; e.currentTarget.style.color = '#cdd6f4' }}
                      onMouseLeave={e => { e.currentTarget.style.borderColor = '#1e1f2e'; e.currentTarget.style.color = '#6c7086' }}
                    >
                      {ex}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {agentMessages.map(msg => (
              <div key={msg.id} style={{ display: 'flex', justifyContent: msg.role === 'user' ? 'flex-end' : 'flex-start' }} className="msg-enter">
                {msg.role === 'user'
                  ? <div className="msg-user" style={{ fontSize: 12, padding: '5px 10px' }}>{msg.content}</div>
                  : (
                    <div style={{ maxWidth: '88%' }}>
                      <div className="msg-assistant" style={{ fontSize: 12, padding: '7px 11px' }}>
                        <MdMsg content={msg.content || ''} />
                        {!msg.done && <span className="cursor" />}
                      </div>
                      {msg.ops?.length > 0 && (
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 4 }}>
                          {msg.ops.map((op, i) => <OpBadge key={i} op={op} />)}
                        </div>
                      )}
                    </div>
                  )
                }
              </div>
            ))}

            <div ref={bottomRef} />
          </div>

          {/* Input */}
          <div style={{ padding: '6px 10px 8px', flexShrink: 0 }}>
            <div className="input-wrap" style={{ display: 'flex', alignItems: 'flex-end', gap: 6, padding: '4px 6px 4px 0' }}>
              <textarea
                className="input-textarea"
                value={input}
                onChange={e => setInput(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() } }}
                placeholder="Describe what to build or change…"
                rows={1}
                style={{ padding: '5px 0 5px 12px', fontSize: 12 }}
              />
              <button
                className="send-btn"
                onClick={send}
                disabled={agentStreaming || !input.trim()}
                style={{ marginBottom: 2, marginRight: 2 }}
              >
                <Svg d={IC.send} size={13} />
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  )
}

// ═════════════════════════════════════════════════════════════════════════════
// ROOT
// ═════════════════════════════════════════════════════════════════════════════
export default function AgentPage() {
  const [chatCollapsed, setChatCollapsed] = useState(false)

  return (
    <div style={{ display: 'flex', height: '100%', background: '#0d0e14', overflow: 'hidden' }}>
      <ProjectSidebar />
      <FileTree onOpen={() => setChatCollapsed(true)} />
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, minHeight: 0 }}>
        <EditorArea />
        <AgentChat
          collapsed={chatCollapsed}
          onToggle={() => setChatCollapsed(v => !v)}
        />
      </div>
    </div>
  )
}
