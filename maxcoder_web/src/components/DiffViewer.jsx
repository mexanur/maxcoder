/**
 * DiffViewer — Monaco diffEditor showing old vs new file content.
 * Used when the agent edits an existing file.
 */
import React from 'react'
import { DiffEditor } from '@monaco-editor/react'

const EXT_LANG = {
  py: 'python', js: 'javascript', jsx: 'javascript',
  ts: 'typescript', tsx: 'typescript', html: 'html',
  css: 'css', json: 'json', md: 'markdown', sh: 'shell',
  rs: 'rust', go: 'go', sql: 'sql', yaml: 'yaml', yml: 'yaml',
}

function langFromPath(path = '') {
  const ext = path.split('.').pop().toLowerCase()
  return EXT_LANG[ext] || 'plaintext'
}

function handleMount(editor, monaco) {
  monaco.editor.defineTheme('maxcoder-dark', {
    base: 'vs-dark', inherit: true, rules: [],
    colors: {
      'editor.background':  '#0f1117',
      'editor.foreground':  '#e2e8f0',
      'editorLineNumber.foreground': '#4a5568',
      'editorLineNumber.activeForeground': '#94a3b8',
      'diffEditor.insertedTextBackground': '#22c55e18',
      'diffEditor.removedTextBackground':  '#ef444418',
      'diffEditor.insertedLineBackground': '#22c55e0a',
      'diffEditor.removedLineBackground':  '#ef44440a',
    },
  })
  monaco.editor.setTheme('maxcoder-dark')
}

export default function DiffViewer({ path = '', original = '', modified = '', height = '100%' }) {
  return (
    <DiffEditor
      height={height}
      language={langFromPath(path)}
      original={original}
      modified={modified}
      theme="maxcoder-dark"
      onMount={handleMount}
      options={{
        readOnly:             true,
        fontSize:             13,
        fontFamily:           "'JetBrains Mono', 'Fira Code', monospace",
        minimap:              { enabled: false },
        scrollBeyondLastLine: false,
        wordWrap:             'on',
        renderSideBySide:     true,
        automaticLayout:      true,
        padding:              { top: 12 },
        scrollbar: { verticalScrollbarSize: 6 },
      }}
    />
  )
}