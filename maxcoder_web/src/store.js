import { create } from 'zustand'
import { v4 as uuid } from 'uuid'

const BACKEND = '/api'

const defaultSettings = {
  model:      'maxcoder-fast',
  useWeb:     true,
  useRag:     true,
  useMem:     true,
  useRew:     true,
  useCritic:  false,
  autoRun:    true,
}

export const useStore = create((set, get) => ({
  // ── chats ──────────────────────────────────
  chats: [],
  activeChatId: null,

  newChat: () => {
    const id = uuid()
    set(s => ({
      chats: [{ id, title: 'New chat', messages: [] }, ...s.chats],
      activeChatId: id,
    }))
    return id
  },

  deleteChat: (id) => {
    set(s => {
      const chats = s.chats.filter(c => c.id !== id)
      return {
        chats,
        activeChatId: s.activeChatId === id
          ? (chats[0]?.id || null)
          : s.activeChatId,
      }
    })
  },

  activeChat: () => {
    const { chats, activeChatId } = get()
    return chats.find(c => c.id === activeChatId) || null
  },

  addMessage: (chatId, msg) => {
    set(s => ({
      chats: s.chats.map(c =>
        c.id === chatId
          ? { ...c, messages: [...c.messages, msg],
              title: c.messages.length === 0 ? msg.content.slice(0,40) : c.title }
          : c
      )
    }))
  },

  updateLastAssistant: (chatId, content, done = false) => {
    set(s => ({
      chats: s.chats.map(c => {
        if (c.id !== chatId) return c
        const msgs = [...c.messages]
        const last = msgs[msgs.length - 1]
        if (last?.role === 'assistant') {
          msgs[msgs.length - 1] = { ...last, content, done }
        }
        return { ...c, messages: msgs }
      })
    }))
  },

  // ── settings ───────────────────────────────
  settings: defaultSettings,
  setSettings: (patch) => set(s => ({ settings: { ...s.settings, ...patch } })),

  // ── streaming ──────────────────────────────
  streaming: false,
  setStreaming: (v) => set({ streaming: v }),

  // ── code output ────────────────────────────
  codeOutput: null,   // { code, lang, result, ok }
  setCodeOutput: (v) => set({ codeOutput: v }),

  // ── send message ───────────────────────────
  sendMessage: async (content) => {
    const { activeChatId, newChat, addMessage,
            updateLastAssistant, settings, setStreaming, setCodeOutput } = get()

    let chatId = activeChatId
    if (!chatId) chatId = newChat()
    else if (!get().chats.find(c => c.id === chatId)) chatId = newChat()

    // user message
    addMessage(chatId, { id: uuid(), role: 'user', content, done: true })

    // placeholder assistant message
    const aId = uuid()
    addMessage(chatId, { id: aId, role: 'assistant', content: '', done: false })
    setStreaming(true)
    setCodeOutput(null)

    try {
      const chat = get().chats.find(c => c.id === chatId)
      const history = chat.messages
        .filter(m => m.done)
        .slice(0, -1)
        .map(m => ({ role: m.role, content: m.content }))

      const res = await fetch(`${BACKEND}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          messages:     [...history, { role: 'user', content }],
          model:        settings.model,
          use_rag:      settings.useRag,
          use_memory:   settings.useMem,
          use_rewriter: settings.useRew,
          use_critic:   settings.useCritic,
          use_web_search: settings.useWeb,
        }),
      })

      const reader  = res.body.getReader()
      const decoder = new TextDecoder()
      let full = ''

      while (true) {
        const { value, done } = await reader.read()
        if (done) break
        full += decoder.decode(value, { stream: true })
        updateLastAssistant(chatId, full, false)
      }
      updateLastAssistant(chatId, full, true)

      // auto-run first code block
      if (settings.autoRun) {
        const match = full.match(/```(\w*)[^\n]*\n([\s\S]*?)```/)
        if (match) {
          const lang = (match[1] || 'python').toLowerCase()
          const code = match[2].trim()
          if (['python','javascript','bash'].includes(lang)) {
            try {
              const r = await fetch(`${BACKEND}/run`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ code, lang }),
              })
              const d = await r.json()
              setCodeOutput({ code, lang, ...d })
            } catch (e) {
              setCodeOutput({ code, lang, ok: false, stderr: String(e) })
            }
          }
        }
      }

    } catch (err) {
      updateLastAssistant(chatId, `Error: ${err.message}`, true)
    } finally {
      setStreaming(false)
    }
  },

  // ── run code manually ──────────────────────
  runCode: async (code, lang) => {
    const { setCodeOutput } = get()
    try {
      const r = await fetch('/api/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code, lang }),
      })
      const d = await r.json()
      setCodeOutput({ code, lang, ...d })
    } catch (e) {
      setCodeOutput({ code, lang, ok: false, stderr: String(e) })
    }
  },
}))
