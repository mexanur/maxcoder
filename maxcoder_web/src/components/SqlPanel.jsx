/**
 * SqlPanel — run SQL against the per-project SQLite DB.
 * Accessible from the Agent IDE as a tab in the editor area.
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
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ sql }),
      })
      setResult(await r.json())
    } catch (e) {
      setResult({ ok: false, error: String(e), rows: [], columns: [] })
    } finally {
      setLoading(false)
    }
  }

  if (!activeProjectId) return (
    <div className="flex items-center justify-center h-full text-muted text-sm">
      Select a project to use the SQL runner.
    </div>
  )

  return (
    <div className="flex flex-col h-full bg-bg">
      {/* Editor */}
      <div className="flex-shrink-0" style={{ height: '180px' }}>
        <MonacoEditor
          path="query.sql"
          value={sql}
          onChange={v => setSql(v || '')}
          onSave={run}
          height="180px"
        />
      </div>

      {/* Toolbar */}
      <div className="flex items-center gap-3 px-4 py-2 border-t border-b border-border bg-surface flex-shrink-0">
        <button
          onClick={run}
          disabled={loading}
          className="flex items-center gap-1.5 text-xs px-4 py-1.5 rounded-lg font-semibold
                     bg-accent text-white hover:bg-accent/80 disabled:opacity-40 transition-colors"
        >
          {loading ? 'Running…' : '▶ Run SQL'}
        </button>
        <span className="text-xs text-muted">Ctrl+S to run</span>

        {tables.length > 0 && (
          <div className="flex items-center gap-1.5 ml-auto flex-wrap">
            <span className="text-xs text-muted">Tables:</span>
            {tables.map(t => (
              <button
                key={t}
                onClick={() => setSql(`SELECT * FROM ${t} LIMIT 50;\n`)}
                className="text-xs px-2 py-0.5 rounded bg-surface2 border border-border
                           text-accent hover:bg-accent/10 transition-colors font-mono"
              >
                {t}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Results */}
      <div className="flex-1 overflow-auto p-4">
        {!result && (
          <p className="text-muted text-xs text-center py-8">
            Run a query to see results. Each project has its own SQLite DB.
          </p>
        )}

        {result && !result.ok && (
          <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-4">
            <p className="text-red-400 text-xs font-semibold mb-1">SQL Error</p>
            <pre className="text-red-300 text-xs whitespace-pre-wrap">{result.error}</pre>
          </div>
        )}

        {result && result.ok && (
          <div>
            <div className="flex items-center gap-3 mb-3">
              <span className="text-xs font-semibold text-green-400">
                ✓ {result.statements_run} statement{result.statements_run !== 1 ? 's' : ''} executed
              </span>
              {result.rows?.length > 0 && (
                <span className="text-xs text-muted">
                  {result.rows.length} row{result.rows.length !== 1 ? 's' : ''}
                </span>
              )}
              {result.rowcount > 0 && result.rows?.length === 0 && (
                <span className="text-xs text-muted">
                  {result.rowcount} row{result.rowcount !== 1 ? 's' : ''} affected
                </span>
              )}
            </div>

            {result.rows?.length > 0 && (
              <div className="overflow-auto rounded-xl border border-border">
                <table className="w-full text-xs font-mono">
                  <thead className="bg-surface sticky top-0">
                    <tr>
                      {result.columns.map(col => (
                        <th
                          key={col}
                          className="text-left px-3 py-2 text-muted font-semibold uppercase
                                     tracking-wider border-b border-border whitespace-nowrap"
                        >
                          {col}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {result.rows.map((row, i) => (
                      <tr
                        key={i}
                        className={`border-b border-border/50 ${i % 2 === 0 ? 'bg-bg' : 'bg-surface/50'}`}
                      >
                        {result.columns.map(col => (
                          <td
                            key={col}
                            className="px-3 py-1.5 text-text whitespace-nowrap max-w-xs truncate"
                          >
                            {row[col] === null
                              ? <span className="text-muted italic">null</span>
                              : String(row[col])
                            }
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {result.rows?.length === 0 && result.rowcount === 0 && (
              <p className="text-muted text-xs">(no rows returned)</p>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
