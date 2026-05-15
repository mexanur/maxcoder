/**
 * MonacoEditor — VS Code's editor embedded in React.
 * Wraps @monaco-editor/react with our dark theme + sensible defaults.
 */
import React, { useEffect, useRef, useState } from 'react'
import Editor from '@monaco-editor/react'

// Map our file extensions to Monaco language IDs
const EXT_LANG = {
  py:   'python',    js:   'javascript', jsx:  'javascript',
  ts:   'typescript',tsx:  'typescript', html: 'html',
  css:  'css',       json: 'json',       md:   'markdown',
  sh:   'shell',     bash: 'shell',      rs:   'rust',
  go:   'go',        java: 'java',       sql:  'sql',
  yaml: 'yaml',      yml:  'yaml',       toml: 'ini',
  txt:  'plaintext', env:  'shell',
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
    base:    'vs-dark',
    inherit: true,
    rules:   [],
    colors: {
      'editor.background':           '#1f2326',
      'editor.foreground':           '#f0f1f2',
      'editorLineNumber.foreground': '#7e858d',
      'editorLineNumber.activeForeground': '#c8cbcf',
      'editor.lineHighlightBackground': '#2f333680',
      'editor.selectionBackground':  '#1473e660',
      'editor.inactiveSelectionBackground': '#1473e630',
      'editorCursor.foreground':     '#7bb7f0',
      'editorWidget.background':     '#26292c',
      'editorWidget.border':         '#4c5054',
      'input.background':            '#393d40',
      'input.foreground':            '#f0f1f2',
      'scrollbarSlider.background':  '#5d626860',
      'scrollbarSlider.hoverBackground': '#7e858d70',
    },
  })

  monaco.editor.defineTheme('maxcoder-light', {
    base:    'vs',
    inherit: true,
    rules:   [],
    colors: {
      'editor.background':           '#ffffff',
      'editor.foreground':           '#1f2328',
      'editorLineNumber.foreground': '#8a95a3',
      'editorLineNumber.activeForeground': '#4f5965',
      'editor.lineHighlightBackground': '#eef4ff',
      'editor.selectionBackground':  '#b8d7ff',
      'editor.inactiveSelectionBackground': '#dbeafe',
      'editorCursor.foreground':     '#1473e6',
      'editorWidget.background':     '#ffffff',
      'editorWidget.border':         '#d4d8dd',
      'input.background':            '#f7f8fa',
      'input.foreground':            '#1f2328',
      'scrollbarSlider.background':  '#c8d0d980',
      'scrollbarSlider.hoverBackground': '#aab4bf90',
    },
  })
}

export default function MonacoEditor({
  path     = '',
  value    = '',
  onChange,
  readOnly = false,
  height   = '100%',
  onSave,            // called with current value on Ctrl+S
}) {
  const editorRef = useRef(null)
  const theme = useEditorTheme()

  function handleMount(editor, monaco) {
    editorRef.current = editor
    defineMaxCoderThemes(monaco)
    monaco.editor.setTheme(currentEditorTheme())

    // Ctrl+S / Cmd+S → save
    if (onSave) {
      editor.addCommand(
        monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS,
        () => onSave(editor.getValue()),
      )
    }
  }

  return (
    <Editor
      height={height}
      language={langFromPath(path)}
      value={value}
      theme={theme}
      onChange={onChange}
      onMount={handleMount}
      options={{
        readOnly,
        fontSize:             13,
        fontFamily:           "'JetBrains Mono', 'Fira Code', monospace",
        fontLigatures:        true,
        minimap:              { enabled: false },
        scrollBeyondLastLine: false,
        lineNumbers:          'on',
        glyphMargin:          false,
        folding:              true,
        wordWrap:             'on',
        tabSize:              2,
        automaticLayout:      true,
        renderLineHighlight:  'line',
        smoothScrolling:      true,
        cursorBlinking:       'smooth',
        cursorSmoothCaretAnimation: 'on',
        padding:              { top: 12, bottom: 12 },
        scrollbar: {
          verticalScrollbarSize:   6,
          horizontalScrollbarSize: 6,
        },
      }}
    />
  )
}
