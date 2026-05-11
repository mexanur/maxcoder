import React, { useState, useRef, useEffect } from 'react'
import { useStore } from '../store'

export default function InputBar() {
  const [input, setInput]   = useState('')
  const sendMessage         = useStore(s => s.sendMessage)
  const streaming           = useStore(s => s.streaming)
  const settings            = useStore(s => s.settings)
  const setSettings         = useStore(s => s.setSettings)
  const taRef               = useRef(null)

  // Auto-grow textarea
  useEffect(() => {
    const ta = taRef.current
    if (!ta) return
    ta.style.height = 'auto'
    ta.style.height = Math.min(ta.scrollHeight, 200) + 'px'
  }, [input])

  const submit = () => {
    const trimmed = input.trim()
    if (!trimmed || streaming) return
    setInput('')
    sendMessage(trimmed)
  }

  const onKey = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
    }
  }

  return (
    <div className="border-t border-border bg-bg px-4 py-4">
      <div className="max-w-3xl mx-auto">

        {/* Quick toggles */}
        <div className="flex items-center gap-1 mb-2 flex-wrap">
          {[
            ['useWeb',  'fa-globe',              'Web'],
            ['useRag',  'fa-database',           'RAG'],
            ['useMem',  'fa-brain',              'Memory'],
            ['autoRun', 'fa-play',               'Auto-run'],
          ].map(([key, icon, label]) => (
            <button
              key={key}
              onClick={() => setSettings({ [key]: !settings[key] })}
              className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full
                          text-xs font-medium transition-all duration-150
                          ${settings[key]
                            ? 'bg-accent/20 text-accent2 border border-accent/40'
                            : 'bg-surface border border-border text-slate-500 hover:text-slate-300'}`}
            >
              <i className={`fa-solid fa-${icon} text-[10px]`}/>
              {label}
            </button>
          ))}

          {/* Model badge */}
          <div className="ml-auto flex items-center gap-1.5 text-xs text-slate-500">
            <i className="fa-solid fa-microchip text-[10px]"/>
            <select
              value={settings.model}
              onChange={e => setSettings({ model: e.target.value })}
              className="bg-transparent text-xs text-slate-400 outline-none
                         cursor-pointer hover:text-slate-200 transition-colors"
            >
              <option value="maxcoder-fast">3B fast</option>
              <option value="maxcoder">7B quality</option>
            </select>
          </div>
        </div>

        {/* Input box */}
        <div className="relative flex items-end gap-2 bg-surface border border-border
                        rounded-2xl px-4 py-3 focus-within:border-accent
                        transition-colors duration-150">
          <textarea
            ref={taRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={onKey}
            placeholder="Ask MaxCoder to build anything... (Shift+Enter for new line)"
            rows={1}
            className="flex-1 bg-transparent text-sm text-white placeholder-slate-500
                       outline-none leading-relaxed max-h-48 overflow-y-auto"
          />
          <button
            onClick={submit}
            disabled={!input.trim() || streaming}
            className={`flex-shrink-0 w-8 h-8 rounded-xl flex items-center
                        justify-center transition-all duration-150
                        ${input.trim() && !streaming
                          ? 'bg-accent hover:bg-accent2 text-white shadow-lg shadow-accent/30'
                          : 'bg-surface2 text-slate-600 cursor-not-allowed'}`}
          >
            {streaming
              ? <i className="fa-solid fa-circle-notch fa-spin text-xs"/>
              : <i className="fa-solid fa-arrow-up text-xs"/>}
          </button>
        </div>

        <p className="text-center text-xs text-slate-600 mt-2">
          MaxCoder runs locally — no data leaves your machine.
        </p>
      </div>
    </div>
  )
}
