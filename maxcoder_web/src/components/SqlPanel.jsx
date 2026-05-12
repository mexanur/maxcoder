/**
 * SqlPanel — Step 2 redesign
 */
import React, { useState, useEffect } from 'react'
import MonacoEditor from './MonacoEditor'
import { useAgentStore } from '../agentStore'

const BACKEND = '/api'
const DEFAULT_SQL = "SELECT * FROM sqlite_master WHERE type='table';\n"

export default function SqlPanel() {
  const activeProjectId = useAgentStore(s => s.activeProjectId)
  const [sql,     setSql]     = useState(DEFAULT_SQL)
  const [result,  setResult]  = useState(null)
  const [loading, setLoading] = useState(false)
  const [tables,  setTables]  = useState([])

  useEffect(() => {
    if (!activeProjectId) return
    fetch(`${BACKEND}/agent/projects/${activeProjectId}/sql/tables`)
      .then(r => r.json())
      .then(d => setTables(d.tables || []))
      .catch(() => {})
  }, [activeProjectId, result])

  const run = async () => {
    if (!activeProjectId || !sql.trim()) return
    setLoading(true)
    try {
      const r = await fetch(`${BACKEND}/agent/projects/${activeProjectId}/sql`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sql }),
      })
      setResult(await r.json())
    } catch (e) {
      setResult({ ok: false, error: String(e), rows: [], columns: [] })
    } finally {
      setLoading(false)
    }
  }

  if (!activeProjectId) return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%' }}>
      <span style={{ fontSize: 12, color: '#6c7086' }}>Select a project to use the SQL runner.</span>
    </div>
  )

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: '#0d0e14' }}>

      {/* Monaco SQL editor */}
      <div style={{ flexShrink: 0, height: 160 }}>
        <MonacoEditor path="query.sql" value={sql} onChange={v => setSql(v || '')} onSave={run} height="160px" />
      </div>

      {/* Toolbar */}
      <div className="panel-border-t panel-border-b" style={{
        display: 'flex', alignItems: 'center', gap: 8,
        padding: '5px 12px', background: '#12131a', flexShrink: 0,
      }}>
        <button
          onClick={run} disabled={loading}
          style={{
            display: 'flex', alignItems: 'center', gap: 5,
            fontSize: 11, fontWeight: 500, padding: '3px 10px', borderRadius: 4,
            background: loading ? '#1e2030' : '#4f6ef7', color: '#fff',
            border: 'none', cursor: loading ? 'not-allowed' : 'pointer', opacity: loading ? 0.6 : 1,
          }}
        >
          {loading ? 'Running…' : '▶ Run SQL'}
        </button>
        <span style={{ fontSize: 10, color: '#6c7086' }}>Ctrl+S</span>

        {tables.length > 0 && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 5, marginLeft: 'auto' }}>
            <span style={{ fontSize: 10, color: '#6c7086' }}>Tables:</span>
            {tables.map(t => (
              <button
                key={t}
                onClick={() => setSql(`SELECT * FROM ${t} LIMIT 50;\n`)}
                style={{
                  fontSize: 10, fontFamily: 'monospace', padding: '2px 8px', borderRadius: 3,
                  background: '#1a1b26', border: '1px solid #1e1f2e', color: '#6b84ff', cursor: 'pointer',
                }}
                onMouseEnter={e => e.currentTarget.style.borderColor = '#4f6ef750'}
                onMouseLeave={e => e.currentTarget.style.borderColor = '#1e1f2e'}
              >
                {t}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Results */}
      <div style={{ flex: 1, overflow: 'auto', padding: 12 }}>
        {!result && (
          <p style={{ fontSize: 11, color: '#6c7086', textAlign: 'center', paddingTop: 24 }}>
            Run a query to see results. Each project has its own SQLite DB.
          </p>
        )}
        {result && !result.ok && (
          <div style={{ background: '#ef444410', border: '1px solid #ef444425', borderRadius: 6, padding: '10px 12px' }}>
            <p style={{ fontSize: 11, fontWeight: 600, color: '#ef4444', marginBottom: 4 }}>SQL Error</p>
            <pre style={{ fontSize: 11, color: '#fca5a5', whiteSpace: 'pre-wrap' }}>{result.error}</pre>
          </div>
        )}
        {result && result.ok && (
          <>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
              <span style={{ fontSize: 11, color: '#22c55e', fontWeight: 500 }}>
                ✓ {result.statements_run} statement{result.statements_run !== 1 ? 's' : ''} executed
              </span>
              {result.rows?.length > 0 && (
                <span style={{ fontSize: 10, color: '#6c7086' }}>{result.rows.length} rows</span>
              )}
              {result.rowcount > 0 && !result.rows?.length && (
                <span style={{ fontSize: 10, color: '#6c7086' }}>{result.rowcount} rows affected</span>
              )}
            </div>
            {result.rows?.length > 0 && (
              <div style={{ border: '1px solid #1e1f2e', borderRadius: 6, overflow: 'hidden' }}>
                <table className="sql-table" style={{ width: '100%', borderCollapse: 'collapse' }}>
                  <thead>
                    <tr>{result.columns.map(c => <th key={c}>{c}</th>)}</tr>
                  </thead>
                  <tbody>
                    {result.rows.map((row, i) => (
                      <tr key={i}>
                        {result.columns.map(c => (
                          <td key={c}>
                            {row[c] === null
                              ? <span style={{ color: '#6c7086', fontStyle: 'italic' }}>null</span>
                              : String(row[c])
                            }
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {!result.rows?.length && !result.rowcount && (
              <p style={{ fontSize: 11, color: '#6c7086' }}>(no rows returned)</p>
            )}
          </>
        )}
      </div>
    </div>
  )
}
