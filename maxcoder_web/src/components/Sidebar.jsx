import React, { useState } from 'react'
import { useStore } from '../store'

export default function Sidebar() {
  const chats        = useStore(s => s.chats)
  const activeChatId = useStore(s => s.activeChatId)
  const newChat      = useStore(s => s.newChat)
  const deleteChat   = useStore(s => s.deleteChat)
  const settings     = useStore(s => s.settings)
  const setSettings  = useStore(s => s.setSettings)
  const setActiveChatId = useStore(s => s.setActiveChatId ||
    ((id) => useStore.setState({ activeChatId: id })))

  const [showSettings, setShowSettings] = useState(false)

  const toggle = (key) => setSettings({ [key]: !settings[key] })

  return (
    <aside className="w-64 flex-shrink-0 flex flex-col h-full
                      bg-surface border-r border-border">

      {/* Logo */}
      <div className="flex items-center gap-3 px-4 py-5
                      border-b border-border">
        <div className="w-8 h-8 rounded-lg bg-accent flex items-center
                        justify-center text-white text-sm font-bold">
          <i className="fa-solid fa-code"/>
        </div>
        <span className="font-semibold text-white text-base">MaxCoder</span>
        <span className="ml-auto text-xs text-accent2 bg-surface2
                         px-2 py-0.5 rounded-full border border-border">
          v2.1
        </span>
      </div>

      {/* New chat button */}
      <div className="px-3 pt-3">
        <button
          onClick={newChat}
          className="w-full flex items-center gap-2 px-3 py-2 rounded-lg
                     text-sm font-medium text-slate-300 hover:text-white
                     hover:bg-surface2 border border-border
                     transition-all duration-150"
        >
          <i className="fa-solid fa-plus text-xs"/>
          New chat
        </button>
      </div>

      {/* Chat list */}
      <div className="flex-1 overflow-y-auto px-2 py-2 space-y-0.5">
        {chats.length === 0 && (
          <p className="text-xs text-slate-500 px-2 pt-2">No chats yet</p>
        )}
        {chats.map(chat => (
          <div
            key={chat.id}
            onClick={() => useStore.setState({ activeChatId: chat.id })}
            className={`group flex items-center gap-2 px-3 py-2 rounded-lg
                        cursor-pointer text-sm transition-all duration-150
                        ${activeChatId === chat.id
                          ? 'bg-surface2 text-white'
                          : 'text-slate-400 hover:bg-surface2 hover:text-white'}`}
          >
            <i className="fa-regular fa-message text-xs opacity-60 flex-shrink-0"/>
            <span className="truncate flex-1">{chat.title || 'New chat'}</span>
            <button
              onClick={e => { e.stopPropagation(); deleteChat(chat.id) }}
              className="opacity-0 group-hover:opacity-100 text-slate-500
                         hover:text-red-400 transition-all ml-auto flex-shrink-0"
            >
              <i className="fa-solid fa-trash text-xs"/>
            </button>
          </div>
        ))}
      </div>

      {/* Settings panel */}
      {showSettings && (
        <div className="border-t border-border px-4 py-3 space-y-3">
          <p className="text-xs font-semibold text-slate-400 uppercase
                        tracking-wider mb-2">Settings</p>

          {/* Model picker */}
          <div>
            <label className="text-xs text-slate-400 block mb-1">Model</label>
            <select
              value={settings.model}
              onChange={e => setSettings({ model: e.target.value })}
              className="w-full bg-surface2 border border-border rounded-lg
                         text-sm text-white px-2 py-1.5 outline-none
                         focus:border-accent"
            >
              <option value="maxcoder-fast">maxcoder-fast (3B)</option>
              <option value="maxcoder">maxcoder (7B)</option>
            </select>
          </div>

          {/* Toggles */}
          {[
            ['useWeb',   'fa-globe',            'Web Search'],
            ['useRag',   'fa-database',         'RAG'],
            ['useMem',   'fa-brain',            'Memory'],
            ['useRew',   'fa-wand-magic-sparkles','Rewriter'],
            ['useCritic','fa-magnifying-glass', 'Critic (slow)'],
            ['autoRun',  'fa-play',             'Auto-run code'],
          ].map(([key, icon, label]) => (
            <label key={key}
              className="flex items-center gap-2 cursor-pointer group">
              <div
                onClick={() => toggle(key)}
                className={`w-8 h-4 rounded-full transition-colors duration-200
                            flex items-center px-0.5 flex-shrink-0
                            ${settings[key] ? 'bg-accent' : 'bg-surface2 border border-border'}`}
              >
                <div className={`w-3 h-3 rounded-full bg-white transition-transform
                                 duration-200 ${settings[key] ? 'translate-x-4' : ''}`}/>
              </div>
              <i className={`fa-solid fa-${icon} text-xs text-slate-400
                             group-hover:text-slate-200 w-3`}/>
              <span className="text-xs text-slate-400 group-hover:text-slate-200">
                {label}
              </span>
            </label>
          ))}
        </div>
      )}

      {/* Bottom bar */}
      <div className="border-t border-border px-3 py-3">
        <button
          onClick={() => setShowSettings(v => !v)}
          className={`w-full flex items-center gap-2 px-3 py-2 rounded-lg
                      text-sm transition-all duration-150
                      ${showSettings
                        ? 'bg-surface2 text-white'
                        : 'text-slate-400 hover:bg-surface2 hover:text-white'}`}
        >
          <i className="fa-solid fa-sliders text-xs"/>
          Settings
        </button>
      </div>
    </aside>
  )
}
