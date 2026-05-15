import { create } from 'zustand'
import { v4 as uuid } from 'uuid'

const defaultSettings = {
  model:     'maxcoder-fast',
  useWeb:    true,
  useRag:    true,
  useMem:    true,
  useRew:    true,
  useCritic: false,
  autoRun:   true,
}

// Detect language of first code block
function detectLang(text) {
  const m = text.match(/```(\w+)[^\n]*\n/)
  return (m?.[1] || '').toLowerCase()
}

// Extract first code block content
function extractCode(text) {
  const m = text.match(/```(?:\w+)[^\n]*\n([\s\S]*?)```/)
  return m ? m[1].trim() : null
}

// Languages that can be run/previewed
const RUNNABLE = ['python','javascript','bash','html','css','svg']

export const useStore = create((set, get) => ({
  chats:        [],
  activeChatId: null,

  newChat: () => {
    const id = uuid()
    set(s => ({
      chats: [{ id, title: 'New chat', messages: [] }, ...s.chats],
      activeChatId: id,
    }))
    return id
  },

  deleteChat: (id) => set(s => {
    const chats = s.chats.filter(c => c.id !== id)
    return {
      chats,
      activeChatId: s.activeChatId === id ? (chats[0]?.id || null) : s.activeChatId,
    }
  }),

  activeChat: () => {
    const { chats, activeChatId } = get()
    return chats.find(c => c.id === activeChatId) || null
  },

  addMessage: (chatId, msg) => set(s => ({
    chats: s.chats.map(c =>
      c.id === chatId
        ? { ...c,
            messages: [...c.messages, msg],
            title: c.messages.length === 0
              ? msg.content.slice(0, 40)
              : c.title }
        : c
    )
  })),

  updateLastAssistant: (chatId, content, done = false, patch = {}) => set(s => ({
    chats: s.chats.map(c => {
      if (c.id !== chatId) return c
      const msgs = [...c.messages]
      const last = msgs[msgs.length - 1]
      if (last?.role === 'assistant') {
        msgs[msgs.length - 1] = { ...last, content, done, ...patch }
      }
      return { ...c, messages: msgs }
    })
  })),

  settings:    defaultSettings,
  setSettings: (patch) => set(s => ({ settings: { ...s.settings, ...patch } })),
  streaming:   false,
  setStreaming: (v) => set({ streaming: v }),
  codeOutput:  null,
  setCodeOutput: (v) => set({ codeOutput: v }),

  sendMessage: async (content, attachedFiles = []) => {
    const { activeChatId, newChat, addMessage,
            updateLastAssistant, settings,
            setStreaming, setCodeOutput } = get()

    let chatId = activeChatId
    if (!chatId || !get().chats.find(c => c.id === chatId)) {
      chatId = newChat()
    }

    // Build augmented content: file context prepended to user message
    let augmented = content
    if (attachedFiles.length > 0) {
      const ctx = attachedFiles
        .map(f => `[ATTACHED FILE: ${f.name}]\n\n${f.text}`)
        .join('\n\n---\n\n')
      augmented = `${ctx}\n\n---\n\nUser request: ${content}`
    }

    // Store file metadata + extracted text so chips are viewable/downloadable in history
    const fileMeta = attachedFiles.map(f => ({ name: f.name, chars: f.chars, text: f.text }))
    // Store augmented so history rebuilds carry file context into follow-up messages
    addMessage(chatId, { id: uuid(), role: 'user', content, augmented, files: fileMeta, done: true })
    const startedAt = Date.now()
    addMessage(chatId, { id: uuid(), role: 'assistant', content: '', done: false, startedAt })
    setStreaming(true)
    setCodeOutput(null)

    try {
      const chat    = get().chats.find(c => c.id === chatId)
      const history = chat.messages
        .filter(m => m.done)
        .slice(0, -1)
        .map(m => ({ role: m.role, content: m.augmented || m.content }))

      const res = await fetch('/api/chat', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          messages:       [...history, { role: 'user', content: augmented }],
          model:          settings.model,
          use_rag:        settings.useRag,
          use_memory:     settings.useMem,
          use_rewriter:   settings.useRew,
          use_critic:     settings.useCritic,
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
      updateLastAssistant(chatId, full, true, { durationMs: Date.now() - startedAt })

      // Auto-run if enabled
      if (settings.autoRun) {
        const lang = detectLang(full)
        const code = extractCode(full)
        if (code && RUNNABLE.includes(lang)) {
          const r = await fetch('/api/run', {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ code, lang }),
          })
          const d = await r.json()
          setCodeOutput({ code, lang, ...d })
        }
      }

    } catch (err) {
      updateLastAssistant(chatId, `Error: ${err.message}`, true, { durationMs: Date.now() - startedAt })
    } finally {
      setStreaming(false)
    }
  },

  runCode: async (code, lang) => {
    const { setCodeOutput } = get()
    try {
      const r = await fetch('/api/run', {
        method:  'POST',
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
