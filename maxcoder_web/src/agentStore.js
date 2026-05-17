/**
 * Agent Store v2 — adds prevFileContents map for diff view.
 */
import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'
import { v4 as uuid } from 'uuid'

const BACKEND = '/api'

export const useAgentStore = create(
  persist(
  (set, get) => ({

  // ── Projects ──────────────────────────────────────────────────────────────
  projects:        [],
  activeProjectId: null,
  files:           [],
  openFile:        null,
  loadingFile:     false,
  prevFileContents: {},   // { [path]: contentBeforeLastAgentEdit }

  fetchProjects: async () => {
    try {
      const r = await fetch(`${BACKEND}/agent/projects`)
      const d = await r.json()
      set({ projects: d.projects || [] })
    } catch (e) { console.error('fetchProjects', e) }
  },

  createProject: async (name) => {
    const id = uuid()
    try {
      await fetch(`${BACKEND}/agent/projects`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_id: id, project_name: name }),
      })
      await get().fetchProjects()
      set({
        activeProjectId:  id,
        files:            [],
        openFile:         null,
        prevFileContents: {},
        agentMessages:    [],     // fresh chat for new project
        lastOps:          [],
      })
      return id
    } catch (e) { console.error('createProject', e); return null }
  },

  deleteProject: async (id) => {
    try {
      await fetch(`${BACKEND}/agent/projects/${id}`, { method: 'DELETE' })
      await get().fetchProjects()
      // Drop the project's chat history too
      set(s => {
        const map = { ...s.agentChatsByProject }
        delete map[id]
        const wasActive = s.activeProjectId === id
        return {
          agentChatsByProject: map,
          ...(wasActive ? {
            activeProjectId: null, files: [], openFile: null,
            prevFileContents: {}, agentMessages: [], lastOps: [],
          } : {}),
        }
      })
    } catch (e) { console.error('deleteProject', e) }
  },

  setActiveProject: async (id) => {
    // Load this project's saved chat into the active view
    const saved = get().agentChatsByProject[id] || []
    set({
      activeProjectId:  id,
      openFile:         null,
      prevFileContents: {},
      agentMessages:    saved,
      lastOps:          [],
    })
    await get().fetchFiles(id)
  },

  // ── Files ─────────────────────────────────────────────────────────────────
  fetchFiles: async (projectId) => {
    const id = projectId || get().activeProjectId
    if (!id) return
    try {
      const r = await fetch(`${BACKEND}/agent/projects/${id}/files`)
      const d = await r.json()
      set({ files: d.files || [] })
    } catch (e) { console.error('fetchFiles', e) }
  },

  openFileByPath: async (path) => {
    const id = get().activeProjectId
    if (!id) return
    set({ loadingFile: true })
    try {
      const r = await fetch(`${BACKEND}/agent/projects/${id}/files/${path}`)
      const d = await r.json()
      set({ openFile: { path: d.path, content: d.content }, loadingFile: false })
    } catch (e) { console.error('openFile', e); set({ loadingFile: false }) }
  },

  saveFile: async (path, content) => {
    const id = get().activeProjectId
    if (!id) return
    try {
      const r = await fetch(`${BACKEND}/agent/projects/${id}/files/${path}`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content }),
      })
      const d = await r.json()
      set({ files: d.files || [], openFile: { path, content } })
    } catch (e) { console.error('saveFile', e) }
  },

  deleteFilePath: async (path) => {
    const id = get().activeProjectId
    if (!id) return
    try {
      const r = await fetch(`${BACKEND}/agent/projects/${id}/files/${path}`, { method: 'DELETE' })
      const d = await r.json()
      set({ files: d.files || [] })
      if (get().openFile?.path === path) set({ openFile: null })
    } catch (e) { console.error('deleteFile', e) }
  },

  setFiles:    (files)    => set({ files }),
  setOpenFile: (openFile) => set({ openFile }),

  // ── Agent chat (per-project history) ──────────────────────────────────────
  // agentChatsByProject is the persistent source of truth: { [projectId]: [msgs] }
  // agentMessages mirrors agentChatsByProject[activeProjectId] for easy reading.
  agentChatsByProject: {},
  agentMessages:       [],
  agentStreaming:      false,
  lastOps:             [],

  // AbortController for the in-flight agent request, used by stopAgentGeneration.
  agentAbortCtrl: null,
  stopAgentGeneration: () => {
    const { agentAbortCtrl } = get()
    if (agentAbortCtrl) {
      try { agentAbortCtrl.abort() } catch {}
    }
    set({ agentAbortCtrl: null, agentStreaming: false })
  },

  // Internal helper — write the current agentMessages back to the per-project map
  _syncAgentChat: () => set(s => {
    const pid = s.activeProjectId
    if (!pid) return {}
    return {
      agentChatsByProject: { ...s.agentChatsByProject, [pid]: s.agentMessages }
    }
  }),

  addAgentMessage: (msg) =>
    set(s => {
      const newMsgs = [...s.agentMessages, msg]
      const pid     = s.activeProjectId
      const map     = pid
        ? { ...s.agentChatsByProject, [pid]: newMsgs }
        : s.agentChatsByProject
      return { agentMessages: newMsgs, agentChatsByProject: map }
    }),

  updateLastAgentAssistant: (content, done = false, ops = null, patch = {}) =>
    set(s => {
      const msgs = [...s.agentMessages]
      const last = msgs[msgs.length - 1]
      if (last?.role === 'assistant')
        msgs[msgs.length - 1] = { ...last, content, done, ops: ops ?? last.ops, ...patch }
      const pid = s.activeProjectId
      const map = pid
        ? { ...s.agentChatsByProject, [pid]: msgs }
        : s.agentChatsByProject
      return { agentMessages: msgs, agentChatsByProject: map }
    }),

  clearAgentChat: () =>
    set(s => {
      const pid = s.activeProjectId
      const map = pid
        ? { ...s.agentChatsByProject, [pid]: [] }
        : s.agentChatsByProject
      return { agentMessages: [], lastOps: [], agentChatsByProject: map }
    }),

  sendAgentMessage: async (content, settings = {}) => {
    const { activeProjectId, createProject, addAgentMessage,
            updateLastAgentAssistant, openFile, files } = get()

    let projectId = activeProjectId
    if (!projectId) projectId = await createProject('New Project')

    const startedAt = Date.now()
    addAgentMessage({ id: uuid(), role: 'user',      content, done: true })
    addAgentMessage({ id: uuid(), role: 'assistant', content: '', done: false, startedAt })

    // Create abort controller so user can stop generation via stop button
    const ctrl = new AbortController()
    set({ agentStreaming: true, lastOps: [], agentAbortCtrl: ctrl })

    try {
      const history = get().agentMessages
        .filter(m => m.done).slice(0, -1)
        .map(m => ({ role: m.role, content: m.content }))

      const res = await fetch(`${BACKEND}/agent/chat`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        signal: ctrl.signal,
        body: JSON.stringify({
          project_id:  projectId,
          messages:    [...history, { role: 'user', content }],
          model:       settings.model     || 'maxcoder-fast',
          use_memory:  settings.useMem    ?? true,
          auto_run:    settings.autoRun   ?? true,
        }),
      })

      const reader  = res.body.getReader()
      const decoder = new TextDecoder()
      let full = ''

      while (true) {
        const { value, done } = await reader.read()
        if (done) break
        full += decoder.decode(value, { stream: true })

        const eventIdx = full.indexOf('\n\n@@EVENT:')
        if (eventIdx !== -1) {
          const chatPart = full.slice(0, eventIdx)
          const eventStr = full.slice(eventIdx + 10)
          updateLastAgentAssistant(chatPart, false)
          try {
            const event = JSON.parse(eventStr)
            if (event.event === 'ops') {
              // Snapshot current open file content for diff BEFORE refreshing
              const prevMap = {}
              if (openFile) prevMap[openFile.path] = openFile.content
              set({
                lastOps:          event.applied,
                files:            event.files || [],
                prevFileContents: prevMap,
              })
              // Refresh open file if it was modified
              if (openFile) {
                const edited = event.applied.find(
                  o => (o.op === 'create' || o.op === 'edit') && o.path === openFile.path
                )
                if (edited) {
                  const id = get().activeProjectId
                  const r  = await fetch(`${BACKEND}/agent/projects/${id}/files/${openFile.path}`)
                  const d  = await r.json()
                  set({ openFile: { path: d.path, content: d.content } })
                }
              }
            }
          } catch (_) {}
        } else {
          updateLastAgentAssistant(full, false)
        }
      }

      const finalEventIdx  = full.indexOf('\n\n@@EVENT:')
      const displayContent = finalEventIdx !== -1 ? full.slice(0, finalEventIdx) : full
      updateLastAgentAssistant(displayContent, true, get().lastOps, { durationMs: Date.now() - startedAt })

    } catch (err) {
      if (err.name === 'AbortError') {
        const msgs = get().agentMessages
        const last = msgs[msgs.length - 1]
        const partial = last?.content || ''
        const tail = partial ? '\n\n*(stopped by user)*' : '*(stopped by user before any output)*'
        updateLastAgentAssistant(partial + tail, true, null, {
          durationMs: Date.now() - startedAt,
          interrupted: true,
        })
      } else {
        updateLastAgentAssistant(`Error: ${err.message}`, true, null, { durationMs: Date.now() - startedAt })
      }
    } finally {
      set({ agentStreaming: false, agentAbortCtrl: null })
    }
  },
}),
  {
    name:    'maxcoder-agent-store',
    version: 1,
    storage: createJSONStorage(() => localStorage),
    // Persist only data that should survive refresh — files/openFile come from server
    partialize: (state) => ({
      activeProjectId:     state.activeProjectId,
      agentChatsByProject: state.agentChatsByProject,
    }),
    // On rehydrate, swap any half-streamed messages to done and load the
    // active project's chat into the live agentMessages view.
    onRehydrateStorage: () => (state) => {
      if (!state) return
      Object.values(state.agentChatsByProject || {}).forEach(msgs => {
        if (!Array.isArray(msgs)) return
        msgs.forEach(m => {
          if (m.role === 'assistant' && m.done === false) {
            m.done = true
            if (!m.content) m.content = '*(interrupted — refresh occurred during streaming)*'
          }
        })
      })
      // Hydrate agentMessages from the active project's saved chat
      const pid = state.activeProjectId
      state.agentMessages = (pid && state.agentChatsByProject?.[pid]) || []
    },
  }
))
