import React, { useState } from 'react'
import { useStore } from '../store'

export default function CodeOutputPanel() {
  const { codeOutput, setCodeOutput, runCode } = useStore(s => ({
    codeOutput:    s.codeOutput,
    setCodeOutput: s.setCodeOutput,
    runCode:       s.runCode,
  }))

  const [editedCode, setEditedCode] = useState(codeOutput?.code || '')
  const [lang, setLang]             = useState(codeOutput?.lang || 'python')

  if (!codeOutput) return null

  const ok      = codeOutput.ok
  const stdout  = codeOutput.stdout?.trim()
  const stderr  = codeOutput.stderr?.trim()

  return (
    <div className="border-t border-border bg-surface mx-0 flex-shrink-0">
      {/* Header */}
      <div className="flex items-center gap-3 px-4 py-2.5 border-b border-border">
        <div className="flex items-center gap-2">
          <i className="fa-solid fa-terminal text-xs text-slate-400"/>
          <span className="text-xs font-semibold text-slate-300 uppercase tracking-wider">
            Code Output
          </span>
        </div>

        {/* Status badge */}
        <span className={`flex items-center gap-1.5 text-xs font-semibold
                          px-2.5 py-0.5 rounded-full border
                          ${ok
                            ? 'bg-green-500/10 text-green-400 border-green-500/30'
                            : 'bg-red-500/10 text-red-400 border-red-500/30'}`}>
          <i className={`fa-solid fa-${ok ? 'circle-check' : 'circle-xmark'} text-[10px]`}/>
          {ok ? 'exit 0' : `exit ${codeOutput.code ?? '?'}`}
        </span>

        <div className="ml-auto flex items-center gap-2">
          <select
            value={lang}
            onChange={e => setLang(e.target.value)}
            className="bg-surface2 border border-border rounded-lg text-xs
                       text-slate-300 px-2 py-1 outline-none"
          >
            <option value="python">Python</option>
            <option value="javascript">JavaScript</option>
            <option value="bash">Bash</option>
          </select>
          <button
            onClick={() => runCode(editedCode, lang)}
            className="flex items-center gap-1.5 px-3 py-1 bg-accent/20
                       border border-accent/40 rounded-lg text-xs text-accent2
                       hover:bg-accent/30 transition-colors"
          >
            <i className="fa-solid fa-rotate-right text-[10px]"/>
            Re-run
          </button>
          <button
            onClick={() => setCodeOutput(null)}
            className="text-slate-500 hover:text-slate-300 transition-colors"
          >
            <i className="fa-solid fa-xmark text-sm"/>
          </button>
        </div>
      </div>

      {/* Output */}
      <div className="max-h-40 overflow-y-auto px-4 py-3 space-y-2">
        {stdout && (
          <pre className="text-xs font-mono text-green-300 bg-green-500/5
                          border-l-2 border-green-500/40 pl-3 py-1
                          whitespace-pre-wrap">
            {stdout}
          </pre>
        )}
        {stderr && (
          <pre className="text-xs font-mono text-red-300 bg-red-500/5
                          border-l-2 border-red-500/40 pl-3 py-1
                          whitespace-pre-wrap">
            {stderr}
          </pre>
        )}
        {!stdout && !stderr && (
          <p className="text-xs text-slate-500 italic">No output</p>
        )}
      </div>
    </div>
  )
}
