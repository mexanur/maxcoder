/**
 * DiffViewer — Monaco diffEditor showing old vs new file content.
 * Used when the agent edits an existing file.
 */
import React, { useEffect, useState } from 'react'
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

function currentEditorTheme() {
  return document.documentElement.getAttribute('data-theme') === 'light'
    ? 'maxcoder-light'
    : 'maxcoder-dark'
}

function useEditorTheme() {
  const [theme, setTheme] = useState(currentEditorTheme)

  useEffect(() => {
    const observer = new MutationObserver(() => setTheme(currentEditorTheme()))
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    return () => observer.disconnect()
  }, [])

  return theme
}

function defineMaxCoderThemes(monaco) {
  monaco.editor.defineTheme('maxcoder-dark', {
    base: 'vs-dark', inherit: true, rules: [],
    colors: {
      'editor.background':  '#1f2326',
      'editor.foreground':  '#f0f1f2',
      'editorLineNumber.foreground': '#7e858d',
      'editorLineNumber.activeForeground': '#c8cbcf',
      'editor.selectionBackground': '#1473e660',
      'diffEditor.insertedTextBackground': '#22c55e18',
      'diffEditor.removedTextBackground':  '#ef444418',
      'diffEditor.insertedLineBackground': '#22c55e0a',
      'diffEditor.removedLineBackground':  '#ef44440a',
    },
  })

  monaco.editor.defineTheme('maxcoder-light', {
    base: 'vs', inherit: true, rules: [],
    colors: {
      'editor.background':  '#ffffff',
      'editor.foreground':  '#1f2328',
      'editorLineNumber.foreground': '#8a95a3',
      'editorLineNumber.activeForeground': '#4f5965',
      'editor.selectionBackground': '#b8d7ff',
      'diffEditor.insertedTextBackground': '#1f883d22',
      'diffEditor.removedTextBackground':  '#cf222e22',
      'diffEditor.insertedLineBackground': '#1f883d12',
      'diffEditor.removedLineBackground':  '#cf222e12',
    },
  })
}

function handleMount(editor, monaco) {
  defineMaxCoderThemes(monaco)
  monaco.editor.setTheme(currentEditorTheme())
}

export default function DiffViewer({ path = '', original = '', modified = '', height = '100%' }) {
  const theme = useEditorTheme()

  return (
    <DiffEditor
      height={height}
      language={langFromPath(path)}
      original={original}
      modified={modified}
      theme={theme}
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
