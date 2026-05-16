import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'
import { v4 as uuid } from 'uuid'

const defaultSettings = {
  model:        'maxcoder-fast',
  useWeb:       true,
  useRag:       true,
  useMem:       true,
  useRew:       true,
  useCritic:    false,
  useReasoning: false,   // MaxThink reasoning pipeline
  autoRun:      true,
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

export const useStore = create(
  persist(
  (set, get) => ({
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

  // Re-issue the previous user query with web search forced on.
  // Used by the "Verify with web" button when an answer was low-confidence.
  verifyWithWeb: async () => {
    const { activeChatId, chats, sendMessage } = get()
    const chat = chats.find(c => c.id === activeChatId)
    if (!chat) return
    // Find the most recent user message
    const lastUser = [...chat.messages].reverse().find(m => m.role === 'user')
    if (!lastUser) return
    // Re-send it with an explicit web-search hint baked into the query
    await sendMessage(`(Verify with the latest web info) ${lastUser.content}`)
  },

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
          use_reasoning:  settings.useReasoning,
          use_web_search: settings.useWeb,
        }),
      })

      const reader  = res.body.getReader()
      const decoder = new TextDecoder()
      let full   = ''      // user-visible answer
      let buffer = ''      // for parsing event lines

      // Reasoning chain accumulator
      const reasoning = { task_type: '', plan: '', thinking: '', visible: false }
      // Skill progress accumulator — updated live as @@SKILL_EVENT lines stream in
      let skillProgress = null
      // Live task previews (per task index) — accumulates content/thinking deltas
      // so the UI can show generation happening in real time
      const liveTasks = {}   // { [taskIndex]: { fmt, title, content, thinking, complete } }

      while (true) {
        const { value, done } = await reader.read()
        if (done) break
        const chunk = decoder.decode(value, { stream: true })

        // ── Unified parser: handles raw text, @@THINK_EVENT, @@SKILL_EVENT ──
        // Both reasoning and non-reasoning streams now go through this same
        // parser. Skills can fire during either mode.
        buffer += chunk
        let nl
        while ((nl = buffer.indexOf('\n')) >= 0) {
          const line = buffer.slice(0, nl)
          buffer = buffer.slice(nl + 1)
          const trimmed = line.trim()

          if (trimmed.startsWith('@@THINK_EVENT:')) {
            try {
              const ev = JSON.parse(trimmed.slice('@@THINK_EVENT:'.length))
              if (ev.event === 'classify')            reasoning.task_type = ev.task_type
              else if (ev.event === 'plan')           reasoning.plan      = ev.content
              else if (ev.event === 'thinking_start') reasoning.thinking  = ''
              else if (ev.event === 'thinking_chunk') reasoning.thinking += ev.content
              else if (ev.event === 'thinking_done')  reasoning.thinking  = ev.content
              else if (ev.event === 'answer_chunk')   full += ev.content
              else if (ev.event === 'uncertainty') {
                updateLastAssistant(chatId, full, false, { reasoning, uncertainty: ev.content, skillProgress })
                continue
              }
            } catch {}
          } else if (trimmed.startsWith('@@SKILL_EVENT:')) {
            // Parse the skill event LIVE so the badge + previews update in real time
            try {
              const ev = JSON.parse(trimmed.slice('@@SKILL_EVENT:'.length))
              const c  = ev.content || {}
              // Always update overall badge state
              skillProgress = { ...skillProgress, ...c }

              // Per-task live preview accumulation
              if (c.index !== undefined && c.stage) {
                const idx = c.index
                const cur = liveTasks[idx] || {
                  fmt: c.fmt, title: c.title, content: '', thinking: '', complete: false,
                }
                if (c.fmt)   cur.fmt   = c.fmt
                if (c.title) cur.title = c.title
                if (c.stage === 'task_content_delta'  && c.delta)    cur.content  += c.delta
                if (c.stage === 'task_thinking_delta' && c.delta)    cur.thinking += c.delta
                if (c.stage === 'task_thinking_done'  && c.thinking) cur.thinking  = c.thinking
                if (c.stage === 'task_complete')                     cur.complete  = true
                liveTasks[idx] = cur
              }
            } catch {}
          } else if (line.length > 0 || full.length > 0) {
            // Non-event content — preserve newlines so @@GENERATE blocks parse
            full += line + '\n'
          }
          updateLastAssistant(chatId, full, false, {
            reasoning,
            skill: skillProgress,
            liveTasks: { ...liveTasks },
          })
        }
      }
      // Flush any trailing buffer that didn't end with a newline
      if (buffer.length > 0) {
        const trimmed = buffer.trim()
        if (trimmed.startsWith('@@THINK_EVENT:')) {
          try {
            const ev = JSON.parse(trimmed.slice('@@THINK_EVENT:'.length))
            if (ev.event === 'answer_chunk')          full += ev.content
            else if (ev.event === 'uncertainty')      updateLastAssistant(chatId, full, false, { reasoning, uncertainty: ev.content, skillProgress })
          } catch {}
        } else if (trimmed.startsWith('@@SKILL_EVENT:')) {
          try {
            const ev = JSON.parse(trimmed.slice('@@SKILL_EVENT:'.length))
            skillProgress = { ...skillProgress, ...ev.content }
          } catch {}
        } else {
          full += buffer
        }
        buffer = ''
      }

      // Extract @@UNCERTAINTY:<json>\n marker — line-bounded match, safe with nested braces
      let uncertainty = null
      const um = full.match(/@@UNCERTAINTY:([^\n]+)/)
      if (um) {
        try { uncertainty = JSON.parse(um[1]) } catch {}
        full = full.replace(/\n?@@UNCERTAINTY:[^\n]+\n?/g, '').trimEnd()
      }

      // Strip any remaining @@SKILL_EVENT markers from visible text (the live
      // parser may have missed trailing ones)
      full = full.replace(/\n?@@SKILL_EVENT:[^\n]+\n?/g, '').trimEnd()

      // Only show reasoning panel if reasoning actually ran (not just enabled
      // but bypassed by a skill match)
      const reasoningRan = settings.useReasoning && (reasoning.plan || reasoning.thinking)
      // Clear live previews for tasks that completed (file cards take over)
      Object.keys(liveTasks).forEach(k => {
        if (liveTasks[k].complete) delete liveTasks[k]
      })

      updateLastAssistant(chatId, full, true, {
        durationMs: Date.now() - startedAt,
        reasoning:  reasoningRan ? reasoning : undefined,
        uncertainty,
        skill:      skillProgress,
        liveTasks:  Object.keys(liveTasks).length ? liveTasks : undefined,
      })

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
}),
  {
    name:    'maxcoder-store',                  // localStorage key
    version: 2,                                  // bump when schema changes
    storage: createJSONStorage(() => localStorage),
    // Only persist data that should survive refresh — skip transient runtime state
    partialize: (state) => ({
      chats:        state.chats,
      activeChatId: state.activeChatId,
      settings:     state.settings,
    }),
    // On rehydrate, force any half-streamed assistant message to "done" so
    // it doesn't render with a blinking cursor forever after refresh.
    onRehydrateStorage: () => (state) => {
      if (!state?.chats) return
      state.chats.forEach(chat => {
        chat.messages.forEach(m => {
          if (m.role === 'assistant' && m.done === false) {
            m.done = true
            // If the streamed answer was completely empty, mark it as interrupted
            if (!m.content) m.content = '*(interrupted — refresh occurred during streaming)*'
          }
        })
      })
    },
    // Migration: handle older schema versions
    migrate: (persisted, version) => {
      if (version < 2 && persisted) {
        // v1 -> v2: nothing schema-breaking, just bump
        return persisted
      }
      return persisted
    },
  }
))
