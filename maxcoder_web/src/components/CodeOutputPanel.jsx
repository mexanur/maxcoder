import React, { useState, useEffect } from 'react'
import { useStore } from '../store'

export default function CodeOutputPanel() {
  const codeOutput    = useStore(s => s.codeOutput)
  const setCodeOutput = useStore(s => s.setCodeOutput)
  const runCode       = useStore(s => s.runCode)

  const [editedCode, setEditedCode] = useState('')
  const [lang, setLang]             = useState('python')
  const [tab, setTab]               = useState('output') // 'output' | 'preview'

  useEffect(() => {
    if (codeOutput) {
      setEditedCode(codeOutput.code || '')
      setLang(codeOutput.lang || 'python')
      // Auto-switch to preview for HTML
      if (codeOutput.preview_html && codeOutput.lang === 'html') {
        setTab('preview')
      } else {
        setTab('output')
      }
    }
  }, [codeOutput])

  if (!codeOutput) return null

  const ok           = codeOutput.ok
  const stdout       = codeOutput.stdout?.trim()
  const stderr       = codeOutput.stderr?.trim()
  const previewHtml  = codeOutput.preview_html
  const isPreviewLang = ['html','css','svg'].includes(lang)

  return (
    <div className="border-t border-border bg-[#13161f] flex-shrink-0">

      {/* ── Header ── */}
      <div className="flex items-center gap-3 px-4 py-2 border-b border-border">

        {/* Title */}
        <i className="fa-solid fa-terminal text-xs text-slate-400"/>
        <span className="text-xs font-semibold text-slate-300 uppercase tracking-wider">
          Code Output
        </span>

        {/* Status badge */}
        {!isPreviewLang && (
          <span className={`flex items-center gap-1.5 text-xs font-semibold
                            px-2.5 py-0.5 rounded-full border
                            ${ok
                              ? 'bg-green-500/10 text-green-400 border-green-500/30'
                              : 'bg-red-500/10 text-red-400 border-red-500/30'}`}>
            <i className={`fa-solid fa-${ok ? 'circle-check' : 'circle-xmark'} text-[10px]`}/>
            {ok ? 'exit 0' : `exit ${codeOutput.code ?? '?'}`}
          </span>
        )}

        {/* Tabs — only show if HTML preview available */}
        {previewHtml && (
          <div className="flex items-center gap-1 ml-2 bg-surface2 rounded-lg p-0.5">
            <button
              onClick={() => setTab('output')}
              className={`px-3 py-1 text-xs rounded-md transition-colors
                          ${tab === 'output'
                            ? 'bg-surface text-white'
                            : 'text-slate-400 hover:text-white'}`}
            >
              <i className="fa-solid fa-terminal text-[10px] mr-1.5"/>
              Output
            </button>
            <button
              onClick={() => setTab('preview')}
              className={`px-3 py-1 text-xs rounded-md transition-colors
                          ${tab === 'preview'
                            ? 'bg-surface text-white'
                            : 'text-slate-400 hover:text-white'}`}
            >
              <i className="fa-solid fa-eye text-[10px] mr-1.5"/>
              Preview
            </button>
          </div>
        )}

        {/* Right controls */}
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
            <option value="html">HTML</option>
            <option value="css">CSS</option>
          </select>

          {!isPreviewLang && (
            <button
              onClick={() => runCode(editedCode, lang)}
              className="flex items-center gap-1.5 px-3 py-1 bg-accent/20
                         border border-accent/40 rounded-lg text-xs text-accent2
                         hover:bg-accent/30 transition-colors"
            >
              <i className="fa-solid fa-rotate-right text-[10px]"/>
              Re-run
            </button>
          )}

          {isPreviewLang && (
            <button
              onClick={() => runCode(editedCode, lang)}
              className="flex items-center gap-1.5 px-3 py-1 bg-accent/20
                         border border-accent/40 rounded-lg text-xs text-accent2
                         hover:bg-accent/30 transition-colors"
            >
              <i className="fa-solid fa-rotate-right text-[10px]"/>
              Refresh
            </button>
          )}

          <button
            onClick={() => setCodeOutput(null)}
            className="text-slate-500 hover:text-slate-300 transition-colors"
          >
            <i className="fa-solid fa-xmark text-sm"/>
          </button>
        </div>
      </div>

      {/* ── Content ── */}
      <div className="max-h-64 overflow-hidden">

        {/* HTML Preview */}
        {tab === 'preview' && previewHtml && (
          <iframe
            srcDoc={previewHtml}
            className="w-full h-60 border-0 bg-white"
            sandbox="allow-scripts"
            title="Preview"
          />
        )}

        {/* Terminal output */}
        {tab === 'output' && (
          <div className="max-h-60 overflow-y-auto px-4 py-3 space-y-2">
            {stdout && (
              <pre className="text-xs font-mono text-green-300 bg-green-500/5
                              border-l-2 border-green-500/40 pl-3 py-2
                              whitespace-pre-wrap rounded">
                {stdout}
              </pre>
            )}
            {stderr && (
              <pre className="text-xs font-mono text-red-300 bg-red-500/5
                              border-l-2 border-red-500/40 pl-3 py-2
                              whitespace-pre-wrap rounded">
                {stderr}
              </pre>
            )}
            {!stdout && !stderr && (
              <p className="text-xs text-slate-500 italic py-2">
                {isPreviewLang
                  ? 'Switch to Preview tab to see the rendered output.'
                  : 'No output'}
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  )
}