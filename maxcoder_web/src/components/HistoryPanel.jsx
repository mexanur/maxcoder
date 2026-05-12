/**
 * HistoryPanel — Step 2 redesign
 */
import React, { useState, useEffect } from 'react'
import DiffViewer from './DiffViewer'
import { useAgentStore } from '../agentStore'

const BACKEND = '/api'

export default function HistoryPanel() {
  const { activeProjectId, openFile, openFileByPath, fetchFiles } = useAgentStore()
  const [snapshots, setSnapshots] = useState([])
  const [selected,  setSelected]  = useState(null)
  const [restoring, setRestoring] = useState(false)
  const [msg,       setMsg]       = useState('')

  useEffect(() => {
    setSnapshots([]); setSelected(null); setMsg('')
    if (!activeProjectId || !openFile?.path) return
    fetch(`${BACKEND}/agent/projects/${activeProjectId}/history/${openFile.path}`)
      .then(r => r.json())
      .then(d => setSnapshots(d.snapshots || []))
      .catch(() => {})
  }, [activeProjectId, openFile?.path])

  const loadSnap = async (stamp) => {
    const r = await fetch(`${BACKEND}/agent/projects/${activeProjectId}/history/${openFile.path}/${stamp}`)
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
      if (d.ok) { await openFileByPath(openFile.path); await fetchFiles(activeProjectId) }
    } catch (e) { setMsg(String(e)) }
    finally { setRestoring(false) }
  }

  if (!activeProjectId || !openFile) return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%' }}>
      <span style={{ fontSize: 12, color: '#6c7086' }}>
        {!activeProjectId ? 'Select a project first.' : 'Open a file to view its history.'}
      </span>
    </div>
  )

  return (
    <div style={{ display: 'flex', height: '100%', overflow: 'hidden' }}>

      {/* Version list */}
      <div className="panel-border-r" style={{ width: 168, flexShrink: 0, display: 'flex', flexDirection: 'column', background: '#0d0e14' }}>
        <div className="panel-border-b" style={{ padding: '6px 12px' }}>
          <p className="section-label">Versions</p>
          <p style={{ fontSize: 10, color: '#6c7086', marginTop: 2, fontFamily: 'monospace', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {openFile.path}
          </p>
        </div>
        <div style={{ flex: 1, overflowY: 'auto' }}>
          {snapshots.length === 0 && (
            <p style={{ fontSize: 10, color: '#6c7086', padding: '16px 12px', lineHeight: 1.7, textAlign: 'center' }}>
              No history yet.<br />Auto-saved before every agent edit.
            </p>
          )}
          {snapshots.map(s => (
            <div
              key={s.stamp}
              onClick={() => loadSnap(s.stamp)}
              style={{
                padding: '5px 12px', cursor: 'pointer', fontFamily: 'monospace',
                borderRight: selected?.stamp === s.stamp ? '2px solid #4f6ef7' : '2px solid transparent',
                background: selected?.stamp === s.stamp ? '#1e2030' : 'transparent',
                color: selected?.stamp === s.stamp ? '#cdd6f4' : '#6c7086',
              }}
              onMouseEnter={e => { if (selected?.stamp !== s.stamp) e.currentTarget.style.background = '#12131a' }}
              onMouseLeave={e => { if (selected?.stamp !== s.stamp) e.currentTarget.style.background = 'transparent' }}
            >
              <p style={{ fontSize: 11 }}>{s.stamp.slice(0,4)}-{s.stamp.slice(4,6)}-{s.stamp.slice(6,8)}</p>
              <p style={{ fontSize: 10, opacity: 0.7 }}>{s.stamp.slice(9,11)}:{s.stamp.slice(11,13)}:{s.stamp.slice(13,15)} UTC</p>
            </div>
          ))}
        </div>
      </div>

      {/* Diff + restore */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
        {!selected
          ? <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%' }}>
              <span style={{ fontSize: 12, color: '#6c7086' }}>Select a version to compare</span>
            </div>
          : <>
              <div className="panel-border-b" style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '5px 12px', background: '#12131a', flexShrink: 0 }}>
                <span style={{ fontSize: 11, color: '#6c7086' }}>
                  Comparing <span style={{ color: '#6b84ff', fontFamily: 'monospace' }}>{selected.stamp.slice(0,15)}</span> → current
                </span>
                <button
                  onClick={restore} disabled={restoring}
                  style={{
                    marginLeft: 'auto', fontSize: 11, padding: '3px 10px', borderRadius: 4,
                    background: '#e5c07b10', border: '1px solid #e5c07b25',
                    color: '#e5c07b', cursor: restoring ? 'not-allowed' : 'pointer', opacity: restoring ? 0.5 : 1,
                  }}
                >
                  {restoring ? 'Restoring…' : '↩ Restore'}
                </button>
              </div>
              {msg && (
                <div style={{ padding: '4px 12px', fontSize: 11, color: msg.startsWith('OK') ? '#22c55e' : '#ef4444', background: msg.startsWith('OK') ? '#22c55e08' : '#ef444408', flexShrink: 0 }}>
                  {msg}
                </div>
              )}
              <div style={{ flex: 1, minHeight: 0 }}>
                <DiffViewer path={openFile.path} original={selected.content} modified={openFile.content} height="100%" />
              </div>
            </>
        }
      </div>
    </div>
  )
}
