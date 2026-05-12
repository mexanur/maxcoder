/**
 * HistoryPanel — view & restore previous versions of a file.
 * Shows snapshots from core/file_history.py (auto-saved before every write).
 */
import React, { useState, useEffect } from 'react'
import DiffViewer from './DiffViewer'
import { useAgentStore } from '../agentStore'

const BACKEND = '/api'

export default function HistoryPanel() {
  const activeProjectId = useAgentStore(s => s.activeProjectId)
  const openFile        = useAgentStore(s => s.openFile)
  const openFileByPath  = useAgentStore(s => s.openFileByPath)
  const fetchFiles      = useAgentStore(s => s.fetchFiles)

  const [snapshots,  setSnapshots]  = useState([])
  const [selected,   setSelected]   = useState(null)   // {stamp, content}
  const [restoring,  setRestoring]  = useState(false)
  const [msg,        setMsg]        = useState('')

  useEffect(() => {
    setSnapshots([]); setSelected(null); setMsg('')
    if (!activeProjectId || !openFile?.path) return
    fetch(`${BACKEND}/agent/projects/${activeProjectId}/history/${openFile.path}`)
      .then(r => r.json())
      .then(d => setSnapshots(d.snapshots || []))
      .catch(() => {})
  }, [activeProjectId, openFile?.path])

  const loadSnapshot = async (stamp) => {
    const r = await fetch(
      `${BACKEND}/agent/projects/${activeProjectId}/history/${openFile.path}/${stamp}`
    )
    const d = await r.json()
    setSelected({ stamp, content: d.content })
  }

  const restore = async () => {
    if (!selected) return
    setRestoring(true)
    try {
      const r = await fetch(
        `${BACKEND}/agent/projects/${activeProjectId}/history/${openFile.path}/${selected.stamp}/restore`,
        { method: 'POST' }
      )
      const d = await r.json()
      setMsg(d.msg)
      if (d.ok) {
        await openFileByPath(openFile.path)
        await fetchFiles(activeProjectId)
      }
    } catch (e) {
      setMsg(String(e))
    } finally {
      setRestoring(false)
    }
  }

  if (!activeProjectId) return (
    <div className="flex items-center justify-center h-full text-muted text-sm">
      Select a project first.
    </div>
  )
  if (!openFile) return (
    <div className="flex items-center justify-center h-full text-muted text-sm">
      Open a file to view its history.
    </div>
  )

  return (
    <div className="flex h-full bg-bg overflow-hidden">
      {/* Snapshot list */}
      <div className="w-52 flex-shrink-0 border-r border-border bg-surface flex flex-col">
        <div className="px-3 py-2.5 border-b border-border">
          <p className="text-[10px] font-bold uppercase tracking-widest text-muted">Versions</p>
          <p className="text-[10px] text-muted mt-0.5 font-mono truncate">{openFile.path}</p>
        </div>
        <div className="flex-1 overflow-y-auto py-1">
          {snapshots.length === 0 && (
            <p className="text-xs text-muted text-center py-6 px-3 leading-relaxed">
              No history yet.<br/>Versions are saved automatically when the agent edits files.
            </p>
          )}
          {snapshots.map(s => (
            <div key={s.stamp}
              onClick={() => loadSnapshot(s.stamp)}
              className={`px-3 py-2 cursor-pointer text-xs font-mono transition-colors
                ${selected?.stamp === s.stamp
                  ? 'bg-accent/15 text-accent border-r-2 border-accent'
                  : 'text-text hover:bg-surface2'}`}
            >
              <p className="text-[11px] font-semibold">
                {s.stamp.slice(0, 4)}-{s.stamp.slice(4,6)}-{s.stamp.slice(6,8)}
              </p>
              <p className="text-muted text-[10px]">
                {s.stamp.slice(9,11)}:{s.stamp.slice(11,13)}:{s.stamp.slice(13,15)} UTC
              </p>
            </div>
          ))}
        </div>
      </div>

      {/* Diff + restore */}
      <div className="flex-1 flex flex-col min-w-0">
        {!selected ? (
          <div className="flex items-center justify-center h-full text-muted text-sm">
            Select a version to compare
          </div>
        ) : (
          <>
            <div className="flex items-center gap-3 px-4 py-2 border-b border-border bg-surface flex-shrink-0">
              <span className="text-xs text-muted font-mono">
                Comparing: <span className="text-accent">{selected.stamp.slice(0,15)}</span> → current
              </span>
              <button
                onClick={restore}
                disabled={restoring}
                className="ml-auto flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg
                           bg-amber-500/15 border border-amber-500/30 text-amber-400
                           hover:bg-amber-500/25 disabled:opacity-40 transition-colors font-semibold"
              >
                {restoring ? 'Restoring…' : '↩ Restore this version'}
              </button>
            </div>
            {msg && (
              <div className={`px-4 py-2 text-xs flex-shrink-0
                ${msg.startsWith('OK') ? 'text-green-400 bg-green-500/5' : 'text-red-400 bg-red-500/5'}`}>
                {msg}
              </div>
            )}
            <div className="flex-1 min-h-0">
              <DiffViewer
                path={openFile.path}
                original={selected.content}
                modified={openFile.content}
                height="100%"
              />
            </div>
          </>
        )}
      </div>
    </div>
  )
}
