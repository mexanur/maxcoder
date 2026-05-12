/**
 * AgentPage — Phase 1 IDE layout
 *
 * ┌─────────────┬──────────────────────┬──────────────────────┐
 * │ Projects    │ File Tree            │ Agent Chat           │
 * │ sidebar     │                      │                      │
 * └─────────────┴──────────────────────┴──────────────────────┘
 */
import React, { useEffect, useState } from 'react'
import { useAgentStore } from '../agentStore'
import { useStore }      from '../store'
import ReactMarkdown     from 'react-markdown'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism'
import remarkGfm from 'remark-gfm'

// ── Icons (inline SVG, no extra dep) ─────────────────────────────────────────
const Icon = ({ name, className = '' }) => {
  const icons = {
    folder:     <svg viewBox="0 0 24 24" fill="currentColor" className={`w-4 h-4 ${className}`}><path d="M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V7z"/></svg>,
    file:       <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} className={`w-4 h-4 ${className}`}><path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/></svg>,
    plus:       <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className={`w-4 h-4 ${className}`}><path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4"/></svg>,
    trash:      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} className={`w-4 h-4 ${className}`}><path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg>,
    send:       <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className={`w-4 h-4 ${className}`}><path strokeLinecap="round" strokeLinejoin="round" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"/></svg>,
    robot:      <svg viewBox="0 0 24 24" fill="currentColor" className={`w-5 h-5 ${className}`}><path d="M12 2a2 2 0 012 2v1h2a3 3 0 013 3v9a3 3 0 01-3 3H8a3 3 0 01-3-3V8a3 3 0 013-3h2V4a2 2 0 012-2zm0 5a1 1 0 100 2 1 1 0 000-2zm-3 5a1 1 0 100 2 1 1 0 000-2zm6 0a1 1 0 100 2 1 1 0 000-2z"/></svg>,
    check:      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5} className={`w-3.5 h-3.5 ${className}`}><path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7"/></svg>,
    x:          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5} className={`w-3.5 h-3.5 ${className}`}><path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12"/></svg>,
    edit:       <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} className={`w-3.5 h-3.5 ${className}`}><path strokeLinecap="round" strokeLinejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931z"/></svg>,
    create:     <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} className={`w-3.5 h-3.5 ${className}`}><path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m3.75 9v6m3-3H9m1.5-12H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z"/></svg>,
  }
  return icons[name] || null
}

// ── File extension → colour ───────────────────────────────────────────────────
const extColor = (path) => {
  const ext = path.split('.').pop().toLowerCase()
  const map  = {
    py: 'text-yellow-400', js: 'text-yellow-300', jsx: 'text-cyan-400',
    ts: 'text-blue-400',  tsx: 'text-cyan-300',  html: 'text-orange-400',
    css: 'text-pink-400', json: 'text-green-400', md: 'text-slate-300',
    rs: 'text-orange-500', go: 'text-cyan-500',  sh: 'text-lime-400',
    sql: 'text-purple-400',
  }
  return map[ext] || 'text-slate-400'
}

// ── Op badge ──────────────────────────────────────────────────────────────────
const OpBadge = ({ op }) => {
  const cfg = {
    create: { bg: 'bg-emerald-500/15 border-emerald-500/30 text-emerald-400', icon: 'create', label: 'Created' },
    edit:   { bg: 'bg-blue-500/15 border-blue-500/30 text-blue-400',          icon: 'edit',   label: 'Edited'  },
    delete: { bg: 'bg-red-500/15 border-red-500/30 text-red-400',             icon: 'trash',  label: 'Deleted' },
    run:    { bg: 'bg-violet-500/15 border-violet-500/30 text-violet-400',    icon: 'robot',  label: 'Ran'     },
  }[op.op] || { bg: 'bg-slate-500/15 border-slate-500/30 text-slate-400', label: op.op }

  return (
    <span className={`inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded border ${cfg.bg} font-mono`}>
      {cfg.icon && <Icon name={cfg.icon} />}
      {op.ok
        ? <><Icon name="check" className="text-current" />{cfg.label}: {op.path || op.lang}</>
        : <><Icon name="x"     className="text-red-400" />Failed: {op.msg}</>
      }
    </span>
  )
}

// ── Markdown renderer for chat messages ───────────────────────────────────────
const MdMessage = ({ content }) => (
  <ReactMarkdown
    remarkPlugins={[remarkGfm]}
    components={{
      code({ inline, className, children }) {
        const lang = (className || '').replace('language-', '')
        return !inline && lang
          ? <SyntaxHighlighter style={oneDark} language={lang} PreTag="div" className="rounded-lg text-xs my-2">
              {String(children).replace(/\n$/, '')}
            </SyntaxHighlighter>
          : <code className="bg-white/10 px-1.5 py-0.5 rounded text-xs font-mono">{children}</code>
      }
    }}
  >
    {content}
  </ReactMarkdown>
)

// ── Project Sidebar ───────────────────────────────────────────────────────────
function ProjectSidebar() {
  const projects        = useAgentStore(s => s.projects)
  const activeProjectId = useAgentStore(s => s.activeProjectId)
  const fetchProjects   = useAgentStore(s => s.fetchProjects)
  const createProject   = useAgentStore(s => s.createProject)
  const deleteProject   = useAgentStore(s => s.deleteProject)
  const setActiveProject= useAgentStore(s => s.setActiveProject)
  const clearAgentChat  = useAgentStore(s => s.clearAgentChat)

  const [naming, setNaming] = useState(false)
  const [name,   setName]   = useState('')

  useEffect(() => { fetchProjects() }, [])

  const handleCreate = async () => {
    if (!name.trim()) return
    await createProject(name.trim())
    clearAgentChat()
    setNaming(false)
    setName('')
  }

  return (
    <div className="flex flex-col h-full border-r border-border bg-surface">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-3 border-b border-border">
        <span className="text-xs font-bold uppercase tracking-widest text-muted">Projects</span>
        <button
          onClick={() => setNaming(v => !v)}
          className="p-1 rounded hover:bg-surface2 text-muted hover:text-text transition-colors"
          title="New project"
        >
          <Icon name="plus" />
        </button>
      </div>

      {/* New project input */}
      {naming && (
        <div className="p-2 border-b border-border">
          <input
            autoFocus
            value={name}
            onChange={e => setName(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') handleCreate(); if (e.key === 'Escape') setNaming(false) }}
            placeholder="Project name..."
            className="w-full text-sm bg-surface2 border border-border rounded-lg px-3 py-1.5 text-text placeholder:text-muted focus:outline-none focus:border-accent"
          />
        </div>
      )}

      {/* Project list */}
      <div className="flex-1 overflow-y-auto py-1">
        {projects.length === 0 && (
          <p className="text-xs text-muted text-center py-6 px-3">No projects yet.<br/>Click + to create one.</p>
        )}
        {projects.map(p => (
          <div
            key={p.id}
            onClick={() => { setActiveProject(p.id); clearAgentChat() }}
            className={`group flex items-center justify-between px-3 py-2 cursor-pointer transition-colors text-sm
              ${p.id === activeProjectId
                ? 'bg-accent/15 text-accent border-r-2 border-accent'
                : 'text-text hover:bg-surface2'
              }`}
          >
            <span className="truncate">{p.name}</span>
            <button
              onClick={e => { e.stopPropagation(); deleteProject(p.id) }}
              className="opacity-0 group-hover:opacity-100 p-0.5 rounded hover:text-red-400 transition-all text-muted"
            >
              <Icon name="trash" />
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── File Tree ─────────────────────────────────────────────────────────────────
function FileTree() {
  const files         = useAgentStore(s => s.files)
  const openFile      = useAgentStore(s => s.openFile)
  const openFileByPath= useAgentStore(s => s.openFileByPath)
  const deleteFilePath= useAgentStore(s => s.deleteFilePath)
  const activeProject = useAgentStore(s => s.activeProjectId)

  if (!activeProject) {
    return (
      <div className="flex items-center justify-center h-full text-muted text-sm">
        Select or create a project
      </div>
    )
  }

  const dirs  = files.filter(f => f.is_dir)
  const ffiles = files.filter(f => !f.is_dir)

  return (
    <div className="flex flex-col h-full border-r border-border bg-surface">
      <div className="flex items-center px-3 py-3 border-b border-border">
        <span className="text-xs font-bold uppercase tracking-widest text-muted">Files</span>
        <span className="ml-auto text-xs text-muted">{ffiles.length} files</span>
      </div>

      <div className="flex-1 overflow-y-auto py-1 font-mono text-xs">
        {files.length === 0 && (
          <p className="text-muted text-center py-8 px-3">
            No files yet.<br/>
            <span className="text-accent">Ask the agent to create them.</span>
          </p>
        )}

        {/* Directories first */}
        {dirs.map(d => (
          <div key={d.path} className="flex items-center gap-2 px-3 py-1 text-muted">
            <Icon name="folder" className="text-yellow-400 flex-shrink-0" />
            <span className="truncate">{d.path}</span>
          </div>
        ))}

        {/* Files */}
        {ffiles.map(f => (
          <div
            key={f.path}
            onClick={() => openFileByPath(f.path)}
            className={`group flex items-center gap-2 px-3 py-1 cursor-pointer transition-colors
              ${openFile?.path === f.path
                ? 'bg-accent/15 text-accent'
                : 'hover:bg-surface2 text-text'
              }`}
          >
            <Icon name="file" className={`flex-shrink-0 ${extColor(f.path)}`} />
            <span className="truncate flex-1">{f.path}</span>
            <button
              onClick={e => { e.stopPropagation(); deleteFilePath(f.path) }}
              className="opacity-0 group-hover:opacity-100 p-0.5 rounded hover:text-red-400 transition-all text-muted"
            >
              <Icon name="trash" />
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── File Viewer ───────────────────────────────────────────────────────────────
function FileViewer() {
  const openFile   = useAgentStore(s => s.openFile)
  const loadingFile= useAgentStore(s => s.loadingFile)
  const saveFile   = useAgentStore(s => s.saveFile)
  const [editing,  setEditing]  = useState(false)
  const [draft,    setDraft]    = useState('')

  useEffect(() => {
    setEditing(false)
    setDraft(openFile?.content || '')
  }, [openFile?.path])

  if (loadingFile) return <div className="flex-1 flex items-center justify-center text-muted text-sm">Loading...</div>
  if (!openFile)   return <div className="flex-1 flex items-center justify-center text-muted text-sm">Click a file to view it</div>

  const lang = openFile.path.split('.').pop().toLowerCase()

  return (
    <div className="flex flex-col h-full bg-bg">
      {/* Toolbar */}
      <div className="flex items-center gap-2 px-4 py-2 border-b border-border bg-surface text-xs font-mono">
        <Icon name="file" className={extColor(openFile.path)} />
        <span className="text-text flex-1 truncate">{openFile.path}</span>
        {editing
          ? <>
              <button onClick={() => { saveFile(openFile.path, draft); setEditing(false) }}
                      className="px-3 py-1 rounded bg-accent text-white hover:bg-accent/80 transition-colors">Save</button>
              <button onClick={() => setEditing(false)}
                      className="px-3 py-1 rounded bg-surface2 text-muted hover:text-text transition-colors">Cancel</button>
            </>
          : <button onClick={() => { setEditing(true); setDraft(openFile.content) }}
                    className="px-3 py-1 rounded bg-surface2 text-muted hover:text-text transition-colors flex items-center gap-1">
              <Icon name="edit" /> Edit
            </button>
        }
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto">
        {editing
          ? <textarea
              value={draft}
              onChange={e => setDraft(e.target.value)}
              className="w-full h-full p-4 bg-bg text-text font-mono text-xs resize-none focus:outline-none border-0"
              spellCheck={false}
            />
          : <SyntaxHighlighter
              style={oneDark}
              language={lang}
              showLineNumbers
              customStyle={{ margin: 0, borderRadius: 0, height: '100%', fontSize: '0.75rem' }}
            >
              {openFile.content}
            </SyntaxHighlighter>
        }
      </div>
    </div>
  )
}

// ── Agent Chat ────────────────────────────────────────────────────────────────
function AgentChat() {
  const agentMessages  = useAgentStore(s => s.agentMessages)
  const agentStreaming = useAgentStore(s => s.agentStreaming)
  const sendAgentMessage = useAgentStore(s => s.sendAgentMessage)
  const settings       = useStore(s => s.settings)
  const bottomRef      = React.useRef(null)
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

  return (
    <div className="flex flex-col h-full bg-bg">
      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {agentMessages.length === 0 && (
          <div className="text-center text-muted text-sm py-12">
            <Icon name="robot" className="mx-auto mb-3 text-accent w-8 h-8" />
            <p className="font-semibold text-text">MaxCoder Agent</p>
            <p className="text-xs mt-1">Describe what you want to build.<br/>I'll create the files directly.</p>
            <div className="mt-4 space-y-2 text-left max-w-xs mx-auto">
              {[
                'Build a FastAPI todo app with SQLite',
                'Create a React landing page with Tailwind',
                'Write a Python web scraper for HN',
              ].map(ex => (
                <button
                  key={ex}
                  onClick={() => sendAgentMessage(ex, settings)}
                  className="w-full text-left text-xs px-3 py-2 rounded-lg bg-surface border border-border hover:border-accent/50 hover:bg-surface2 transition-all text-muted hover:text-text"
                >
                  {ex}
                </button>
              ))}
            </div>
          </div>
        )}

        {agentMessages.map(msg => (
          <div key={msg.id} className={`flex gap-3 ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            {msg.role === 'assistant' && (
              <div className="w-7 h-7 rounded-full bg-accent/20 flex items-center justify-center flex-shrink-0 mt-0.5">
                <Icon name="robot" className="text-accent w-4 h-4" />
              </div>
            )}
            <div className={`max-w-[85%] rounded-2xl px-4 py-3 text-sm
              ${msg.role === 'user'
                ? 'bg-accent text-white rounded-tr-sm'
                : 'bg-surface border border-border rounded-tl-sm text-text'
              }`}
            >
              {msg.role === 'assistant'
                ? <MdMessage content={msg.content || '▍'} />
                : <span>{msg.content}</span>
              }
              {/* Op badges */}
              {msg.ops && msg.ops.length > 0 && (
                <div className="flex flex-wrap gap-1 mt-2 pt-2 border-t border-white/10">
                  {msg.ops.map((op, i) => <OpBadge key={i} op={op} />)}
                </div>
              )}
            </div>
          </div>
        ))}

        {agentStreaming && agentMessages[agentMessages.length - 1]?.role !== 'assistant' && (
          <div className="flex gap-3">
            <div className="w-7 h-7 rounded-full bg-accent/20 flex items-center justify-center">
              <Icon name="robot" className="text-accent w-4 h-4" />
            </div>
            <div className="bg-surface border border-border rounded-2xl rounded-tl-sm px-4 py-3">
              <span className="text-muted text-sm animate-pulse">Thinking...</span>
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="p-3 border-t border-border bg-surface">
        <div className="flex gap-2 items-end">
          <textarea
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() }
            }}
            placeholder="Describe what to build or change..."
            rows={2}
            className="flex-1 bg-surface2 border border-border rounded-xl px-3 py-2 text-sm text-text placeholder:text-muted focus:outline-none focus:border-accent resize-none"
          />
          <button
            onClick={send}
            disabled={agentStreaming || !input.trim()}
            className="p-3 rounded-xl bg-accent text-white hover:bg-accent/80 disabled:opacity-40 disabled:cursor-not-allowed transition-all flex-shrink-0"
          >
            <Icon name="send" />
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Main Layout ───────────────────────────────────────────────────────────────
export default function AgentPage() {
  const [view, setView] = useState('chat') // 'chat' | 'file'

  return (
    <div className="flex h-screen bg-bg overflow-hidden">
      {/* Column 1 — Projects (160px) */}
      <div className="w-40 flex-shrink-0">
        <ProjectSidebar />
      </div>

      {/* Column 2 — File Tree (200px) */}
      <div className="w-52 flex-shrink-0">
        <FileTree />
      </div>

      {/* Column 3 — Main area */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Tab bar */}
        <div className="flex items-center gap-1 px-3 py-2 border-b border-border bg-surface">
          <button
            onClick={() => setView('chat')}
            className={`text-xs px-3 py-1.5 rounded-lg font-medium transition-colors
              ${view === 'chat' ? 'bg-accent/20 text-accent' : 'text-muted hover:text-text'}`}
          >
            Agent Chat
          </button>
          <button
            onClick={() => setView('file')}
            className={`text-xs px-3 py-1.5 rounded-lg font-medium transition-colors
              ${view === 'file' ? 'bg-accent/20 text-accent' : 'text-muted hover:text-text'}`}
          >
            File Viewer
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-hidden">
          {view === 'chat' ? <AgentChat /> : <FileViewer />}
        </div>
      </div>
    </div>
  )
}
