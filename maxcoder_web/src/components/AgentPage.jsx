/**
 * AgentPage v3 — Phase 3
 * Adds SQL runner tab + File History tab to the editor area.
 * The rest of the layout is unchanged from Phase 2.
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

// ── Icons ─────────────────────────────────────────────────────────────────────
const I = ({ d, className = 'w-4 h-4' }) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8}
       strokeLinecap="round" strokeLinejoin="round" className={className}>
    <path d={d}/>
  </svg>
)
const Icons = {
  folder:  'M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V7z',
  file:    'M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z',
  plus:    'M12 4v16m8-8H4',
  trash:   'M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16',
  send:    'M12 19l9 2-9-18-9 18 9-2zm0 0v-8',
  save:    'M17 21H7a2 2 0 01-2-2V5a2 2 0 012-2h7l5 5v11a2 2 0 01-2 2z',
  eye:     'M15 12a3 3 0 11-6 0 3 3 0 016 0z M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z',
  diff:    'M9 3H5a2 2 0 00-2 2v4m6-6h10a2 2 0 012 2v4M9 3v18m0 0h10a2 2 0 002-2V9M9 21H5a2 2 0 01-2-2V9m0 0h18',
  code:    'M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4',
  play:    'M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z M21 12a9 9 0 11-18 0 9 9 0 0118 0z',
  vscode:  'M17.5 3.5L8 12l-4-3L2 10.5l6 5.5-6 5.5 2 1.5 4-3 9.5 8.5 2-1V4.5l-2-1z',
  chat:    'M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z',
  x:       'M6 18L18 6M6 6l12 12',
  chevron: 'M19 9l-7 7-7-7',
  check:   'M5 13l4 4L19 7',
  robot:   'M12 2a2 2 0 012 2v1h3a2 2 0 012 2v10a2 2 0 01-2 2H7a2 2 0 01-2-2V7a2 2 0 012-2h3V4a2 2 0 012-2zm-2 9a1 1 0 102 0 1 1 0 00-2 0zm5 0a1 1 0 102 0 1 1 0 00-2 0zm-7 3h10',
  sql:     'M4 6h16M4 10h16M4 14h16M4 18h16',
  history: 'M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z',
}
const Ic = ({ name, className = 'w-4 h-4' }) => <I d={Icons[name]} className={className} />

const extColor = (path = '') => {
  const ext = path.split('.').pop().toLowerCase()
  return ({ py:'text-yellow-400', js:'text-yellow-300', jsx:'text-cyan-400',
            ts:'text-blue-400', tsx:'text-cyan-300', html:'text-orange-400',
            css:'text-pink-400', json:'text-green-400', md:'text-slate-300',
            rs:'text-orange-500', go:'text-cyan-500', sh:'text-lime-400',
            sql:'text-purple-400' })[ext] || 'text-slate-400'
}

const MdMsg = ({ content }) => (
  <ReactMarkdown remarkPlugins={[remarkGfm]} components={{
    code({ inline, className, children }) {
      const lang = (className || '').replace('language-', '')
      return !inline && lang
        ? <SyntaxHighlighter style={oneDark} language={lang} PreTag="div"
            className="rounded-lg text-xs my-2 !bg-bg">
            {String(children).replace(/\n$/, '')}
          </SyntaxHighlighter>
        : <code className="bg-white/10 px-1.5 py-0.5 rounded text-xs font-mono">{children}</code>
    }
  }}>{content}</ReactMarkdown>
)

const OpBadge = ({ op }) => {
  const cfg = {
    create: 'bg-emerald-500/15 border-emerald-500/30 text-emerald-400',
    edit:   'bg-blue-500/15 border-blue-500/30 text-blue-400',
    delete: 'bg-red-500/15 border-red-500/30 text-red-400',
    run:    'bg-violet-500/15 border-violet-500/30 text-violet-400',
  }[op.op] || 'bg-slate-500/15 border-slate-500/30 text-slate-400'
  const labels = { create: 'Created', edit: 'Edited', delete: 'Deleted', run: 'Ran' }
  return (
    <span className={`inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded border ${cfg} font-mono`}>
      {op.ok
        ? <><Ic name="check" className="w-3 h-3"/> {labels[op.op]||op.op}: {op.path||op.lang}</>
        : <><Ic name="x"     className="w-3 h-3 text-red-400"/> Failed: {op.path||op.msg}</>}
    </span>
  )
}

// ── Project Sidebar ──────────────────────────────────────────────────────────
function ProjectSidebar() {
  const { projects, activeProjectId, fetchProjects, createProject,
          deleteProject, setActiveProject, clearAgentChat } = useAgentStore()
  const [naming, setNaming] = useState(false)
  const [name,   setName]   = useState('')
  useEffect(() => { fetchProjects() }, [])
  const handleCreate = async () => {
    if (!name.trim()) return
    await createProject(name.trim()); clearAgentChat()
    setNaming(false); setName('')
  }
  return (
    <div className="flex flex-col h-full border-r border-border bg-surface w-44 flex-shrink-0">
      <div className="flex items-center justify-between px-3 py-2.5 border-b border-border">
        <span className="text-[10px] font-bold uppercase tracking-widest text-muted">Projects</span>
        <button onClick={() => setNaming(v=>!v)} className="p-0.5 rounded hover:bg-surface2 text-muted hover:text-text transition-colors">
          <Ic name="plus" className="w-3.5 h-3.5"/>
        </button>
      </div>
      {naming && (
        <div className="p-2 border-b border-border">
          <input autoFocus value={name} onChange={e=>setName(e.target.value)}
            onKeyDown={e=>{if(e.key==='Enter')handleCreate();if(e.key==='Escape')setNaming(false)}}
            placeholder="Project name…"
            className="w-full text-xs bg-surface2 border border-border rounded-lg px-2 py-1.5 text-text placeholder:text-muted focus:outline-none focus:border-accent"/>
        </div>
      )}
      <div className="flex-1 overflow-y-auto py-1">
        {projects.length===0 && <p className="text-[11px] text-muted text-center py-6 px-3 leading-relaxed">No projects.<br/>Click + to start.</p>}
        {projects.map(p=>(
          <div key={p.id} onClick={()=>{setActiveProject(p.id);clearAgentChat()}}
            className={`group flex items-center justify-between px-3 py-2 cursor-pointer transition-colors text-xs
              ${p.id===activeProjectId?'bg-accent/15 text-accent border-r-2 border-accent':'text-text hover:bg-surface2'}`}>
            <span className="truncate leading-tight">{p.name}</span>
            <button onClick={e=>{e.stopPropagation();deleteProject(p.id)}}
              className="opacity-0 group-hover:opacity-100 p-0.5 rounded hover:text-red-400 transition-all text-muted ml-1 flex-shrink-0">
              <Ic name="trash" className="w-3 h-3"/>
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── File Tree ────────────────────────────────────────────────────────────────
function FileTree({ onOpen }) {
  const { files, openFile, openFileByPath, deleteFilePath, activeProjectId } = useAgentStore()
  if (!activeProjectId) return <div className="flex items-center justify-center h-full text-muted text-xs text-center px-3 w-52 flex-shrink-0 border-r border-border">Select a project</div>
  const dirs   = files.filter(f=>f.is_dir)
  const ffiles = files.filter(f=>!f.is_dir)
  return (
    <div className="flex flex-col h-full border-r border-border bg-surface w-52 flex-shrink-0">
      <div className="flex items-center px-3 py-2.5 border-b border-border">
        <span className="text-[10px] font-bold uppercase tracking-widest text-muted">Files</span>
        <span className="ml-auto text-[10px] text-muted">{ffiles.length}</span>
      </div>
      <div className="flex-1 overflow-y-auto py-1 font-mono">
        {files.length===0 && <p className="text-[11px] text-muted text-center py-8 px-3 leading-relaxed">No files yet.<br/><span className="text-accent">Ask the agent.</span></p>}
        {dirs.map(d=>(
          <div key={d.path} className="flex items-center gap-1.5 px-3 py-1 text-muted text-xs">
            <Ic name="folder" className="w-3.5 h-3.5 text-yellow-400 flex-shrink-0"/>
            <span className="truncate">{d.path}</span>
          </div>
        ))}
        {ffiles.map(f=>(
          <div key={f.path} onClick={()=>{openFileByPath(f.path);onOpen&&onOpen(f.path)}}
            className={`group flex items-center gap-1.5 px-3 py-1 cursor-pointer transition-colors text-xs
              ${openFile?.path===f.path?'bg-accent/15 text-accent':'hover:bg-surface2 text-text'}`}>
            <Ic name="file" className={`w-3.5 h-3.5 flex-shrink-0 ${extColor(f.path)}`}/>
            <span className="truncate flex-1">{f.path}</span>
            <button onClick={e=>{e.stopPropagation();deleteFilePath(f.path)}}
              className="opacity-0 group-hover:opacity-100 p-0.5 rounded hover:text-red-400 transition-all text-muted">
              <Ic name="trash" className="w-3 h-3"/>
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Editor Area — NOW WITH SQL + HISTORY TABS ────────────────────────────────
function EditorArea() {
  const { openFile, saveFile, loadingFile, lastOps } = useAgentStore()
  const [tab,      setTab]      = useState('editor')
  const [draft,    setDraft]    = useState('')
  const [dirty,    setDirty]    = useState(false)
  const [prevContent, setPrev]  = useState('')
  const [runResult, setRunResult] = useState(null)

  useEffect(() => {
    setDraft(openFile?.content || '')
    setDirty(false); setRunResult(null)
    if (tab !== 'sql' && tab !== 'history') setTab('editor')
  }, [openFile?.path])

  useEffect(() => {
    if (!openFile || !lastOps?.length) return
    const op = lastOps.find(o=>o.path===openFile.path && o.op==='edit')
    if (op) { setPrev(draft); setDraft(openFile.content); setDirty(false); setTab('diff') }
    const runOp = lastOps.find(o=>o.op==='run')
    if (runOp) setRunResult(runOp)
  }, [lastOps])

  const handleSave = async (value) => {
    if (!openFile) return
    await saveFile(openFile.path, value ?? draft)
    setDirty(false)
  }

  const handleRun = async () => {
    if (!openFile) return
    const lang = openFile.path.split('.').pop().toLowerCase()
    try {
      const r = await fetch('/api/run', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({ code: draft, lang }),
      })
      const d = await r.json()
      setRunResult({...d, lang}); setTab('preview')
    } catch(e) {
      setRunResult({ok:false,stderr:String(e),stdout:'',lang:''}); setTab('preview')
    }
  }

  const lang       = openFile?.path.split('.').pop().toLowerCase() || ''
  const isVisual   = ['html','css','svg','md','markdown'].includes(lang)
  const isRunnable = ['python','javascript','bash','shell','go','rust','java'].includes(lang)

  // Tabs definition — SQL and History are always visible regardless of open file
  const TABS = [
    { id: 'editor',  label: 'Editor',  icon: 'code'    },
    { id: 'diff',    label: 'Diff',    icon: 'diff'    },
    { id: 'preview', label: 'Preview', icon: 'eye'     },
    { id: 'sql',     label: 'SQL',     icon: 'sql'     },
    { id: 'history', label: 'History', icon: 'history' },
  ]

  return (
    <div className="flex-1 flex flex-col min-w-0 min-h-0">
      {/* Toolbar */}
      <div className="flex items-center gap-0.5 px-3 py-1.5 border-b border-border bg-surface flex-shrink-0 flex-wrap">
        {openFile && (
          <span className={`text-xs font-mono mr-2 ${extColor(openFile.path)}`}>
            {openFile.path}{dirty&&<span className="text-accent ml-1">●</span>}
          </span>
        )}
        {TABS.map(t=>(
          <button key={t.id} onClick={()=>setTab(t.id)}
            className={`flex items-center gap-1 text-xs px-2.5 py-1 rounded-lg font-medium transition-colors
              ${tab===t.id?'bg-accent/20 text-accent':'text-muted hover:text-text'}`}>
            <Ic name={t.icon} className="w-3 h-3"/>{t.label}
          </button>
        ))}
        <div className="flex-1"/>
        {openFile && (isRunnable||isVisual) && (
          <button onClick={handleRun}
            className="flex items-center gap-1 text-xs px-2.5 py-1 rounded-lg bg-green-500/15 border border-green-500/30 text-green-400 hover:bg-green-500/25 transition-colors">
            <Ic name="play" className="w-3 h-3"/> Run
          </button>
        )}
        {dirty && (
          <button onClick={()=>handleSave()}
            className="flex items-center gap-1 text-xs px-2.5 py-1 rounded-lg bg-accent/20 border border-accent/30 text-accent hover:bg-accent/30 transition-colors">
            <Ic name="save" className="w-3 h-3"/> Save
          </button>
        )}
        {openFile && (
          <button onClick={()=>window.open(`vscode://file/${encodeURIComponent(openFile.path)}`)}
            className="flex items-center gap-1 text-xs px-2.5 py-1 rounded-lg bg-surface2 border border-border text-muted hover:text-text transition-colors">
            <Ic name="vscode" className="w-3 h-3"/> VS Code
          </button>
        )}
      </div>

      {/* Panel */}
      <div className="flex-1 min-h-0 overflow-hidden">
        {tab==='sql'     && <SqlPanel/>}
        {tab==='history' && <HistoryPanel/>}
        {tab==='editor'  && (
          loadingFile ? <div className="flex items-center justify-center h-full text-muted text-sm">Loading…</div>
          : !openFile  ? <div className="flex flex-col items-center justify-center h-full text-center gap-3 text-muted"><Ic name="code" className="w-10 h-10 opacity-20"/><p className="text-sm">Select a file to edit</p></div>
          : <MonacoEditor path={openFile.path} value={draft} onChange={v=>{setDraft(v);setDirty(true)}} onSave={handleSave} height="100%"/>
        )}
        {tab==='diff' && (
          prevContent && openFile
            ? <DiffViewer path={openFile.path} original={prevContent} modified={draft} height="100%"/>
            : <div className="flex items-center justify-center h-full text-muted text-sm">Diff appears after the agent edits a file.</div>
        )}
        {tab==='preview' && openFile && <LivePreview code={draft} lang={lang} runResult={runResult}/>}
        {tab==='preview' && !openFile && <div className="flex items-center justify-center h-full text-muted text-sm">Open a file first.</div>}
      </div>
    </div>
  )
}

// ── Agent Chat ───────────────────────────────────────────────────────────────
function AgentChat({ collapsed, onToggle }) {
  const { agentMessages, agentStreaming, sendAgentMessage, activeProjectId } = useAgentStore()
  const settings  = useStore(s=>s.settings)
  const bottomRef = useRef(null)
  const [input, setInput] = useState('')
  useEffect(()=>{ bottomRef.current?.scrollIntoView({behavior:'smooth'}) },[agentMessages.length,agentStreaming])
  const send = () => { const t=input.trim(); if(!t||agentStreaming)return; setInput(''); sendAgentMessage(t,settings) }
  return (
    <div className={`flex flex-col border-t border-border bg-surface transition-all duration-300 flex-shrink-0 ${collapsed?'h-10':'h-80'}`}>
      <div onClick={onToggle} className="flex items-center gap-2 px-4 py-2 cursor-pointer hover:bg-surface2 transition-colors select-none flex-shrink-0">
        <Ic name="robot" className="w-3.5 h-3.5 text-accent"/>
        <span className="text-xs font-semibold text-text">Agent Chat</span>
        {activeProjectId&&<span className="text-[10px] text-muted ml-1 font-mono truncate max-w-[120px]">— {activeProjectId.slice(0,8)}…</span>}
        {agentStreaming&&<span className="ml-1 text-[10px] text-accent animate-pulse">● thinking</span>}
        <Ic name="chevron" className={`w-3 h-3 text-muted ml-auto transition-transform ${collapsed?'':' rotate-180'}`}/>
      </div>
      {!collapsed&&(
        <>
          <div className="flex-1 overflow-y-auto px-4 py-2 space-y-3 min-h-0">
            {agentMessages.length===0&&(
              <div className="text-center py-6">
                <p className="text-muted text-xs">Describe what to build or change.</p>
                <div className="mt-3 flex flex-wrap gap-2 justify-center">
                  {['Build a FastAPI todo app','Create a React landing page','Write a Python web scraper'].map(ex=>(
                    <button key={ex} onClick={()=>sendAgentMessage(ex,settings)}
                      className="text-[11px] px-3 py-1.5 rounded-lg bg-surface2 border border-border hover:border-accent/50 text-muted hover:text-text transition-all">{ex}</button>
                  ))}
                </div>
              </div>
            )}
            {agentMessages.map(msg=>(
              <div key={msg.id} className={`flex gap-2 ${msg.role==='user'?'justify-end':'justify-start'}`}>
                {msg.role==='assistant'&&<div className="w-6 h-6 rounded-full bg-accent/20 flex items-center justify-center flex-shrink-0 mt-0.5"><Ic name="robot" className="w-3.5 h-3.5 text-accent"/></div>}
                <div className={`max-w-[80%] rounded-xl px-3 py-2 text-xs ${msg.role==='user'?'bg-accent text-white rounded-tr-sm':'bg-surface2 border border-border rounded-tl-sm text-text'}`}>
                  {msg.role==='assistant'?<MdMsg content={msg.content||'▍'}/>:<span>{msg.content}</span>}
                  {msg.ops?.length>0&&<div className="flex flex-wrap gap-1 mt-1.5 pt-1.5 border-t border-white/10">{msg.ops.map((op,i)=><OpBadge key={i} op={op}/>)}</div>}
                </div>
              </div>
            ))}
            <div ref={bottomRef}/>
          </div>
          <div className="p-2 border-t border-border flex-shrink-0">
            <div className="flex gap-2 items-end">
              <textarea value={input} onChange={e=>setInput(e.target.value)}
                onKeyDown={e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();send()}}}
                placeholder="Describe what to build or change…" rows={1}
                className="flex-1 bg-surface2 border border-border rounded-xl px-3 py-2 text-xs text-text placeholder:text-muted focus:outline-none focus:border-accent resize-none"/>
              <button onClick={send} disabled={agentStreaming||!input.trim()}
                className="p-2 rounded-xl bg-accent text-white hover:bg-accent/80 disabled:opacity-40 disabled:cursor-not-allowed transition-all flex-shrink-0">
                <Ic name="send" className="w-3.5 h-3.5"/>
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  )
}

// ── Root ─────────────────────────────────────────────────────────────────────
export default function AgentPage() {
  const [chatCollapsed, setChatCollapsed] = useState(false)
  return (
    <div className="flex h-full bg-bg overflow-hidden">
      <ProjectSidebar/>
      <FileTree onOpen={()=>setChatCollapsed(true)}/>
      <div className="flex-1 flex flex-col min-w-0 min-h-0">
        <EditorArea/>
        <AgentChat collapsed={chatCollapsed} onToggle={()=>setChatCollapsed(v=>!v)}/>
      </div>
    </div>
  )
}
