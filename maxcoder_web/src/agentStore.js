/**
 * Agent Store v2 — adds prevFileContents map for diff view.
 */
import { create } from 'zustand'
import { v4 as uuid } from 'uuid'

const BACKEND = '/api'

export const useAgentStore = create((set, get) => ({

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
      set({ activeProjectId: id, files: [], openFile: null, prevFileContents: {} })
      return id
    } catch (e) { console.error('createProject', e); return null }
  },

  deleteProject: async (id) => {
    try {
      await fetch(`${BACKEND}/agent/projects/${id}`, { method: 'DELETE' })
      await get().fetchProjects()
      if (get().activeProjectId === id)
        set({ activeProjectId: null, files: [], openFile: null, prevFileContents: {} })
    } catch (e) { console.error('deleteProject', e) }
  },

  setActiveProject: async (id) => {
    set({ activeProjectId: id, openFile: null, prevFileContents: {} })
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

  // ── Agent chat ────────────────────────────────────────────────────────────
  agentMessages:  [],
  agentStreaming: false,
  lastOps:        [],

  addAgentMessage: (msg) =>
    set(s => ({ agentMessages: [...s.agentMessages, msg] })),

  updateLastAgentAssistant: (content, done = false, ops = null) =>
    set(s => {
      const msgs = [...s.agentMessages]
      const last = msgs[msgs.length - 1]
      if (last?.role === 'assistant')
        msgs[msgs.length - 1] = { ...last, content, done, ops: ops ?? last.ops }
      return { agentMessages: msgs }
    }),

  clearAgentChat: () => set({ agentMessages: [], lastOps: [] }),

  sendAgentMessage: async (content, settings = {}) => {
    const { activeProjectId, createProject, addAgentMessage,
            updateLastAgentAssistant, openFile, files } = get()

    let projectId = activeProjectId
    if (!projectId) projectId = await createProject('New Project')

    addAgentMessage({ id: uuid(), role: 'user',      content, done: true })
    addAgentMessage({ id: uuid(), role: 'assistant', content: '', done: false })
    set({ agentStreaming: true, lastOps: [] })

    try {
      const history = get().agentMessages
        .filter(m => m.done).slice(0, -1)
        .map(m => ({ role: m.role, content: m.content }))

      const res = await fetch(`${BACKEND}/agent/chat`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
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
      updateLastAgentAssistant(displayContent, true, get().lastOps)

    } catch (err) {
      updateLastAgentAssistant(`Error: ${err.message}`, true)
    } finally {
      set({ agentStreaming: false })
    }
  },
}))
