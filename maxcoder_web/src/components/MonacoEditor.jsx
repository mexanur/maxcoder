/**
 * MonacoEditor — VS Code's editor embedded in React.
 * Wraps @monaco-editor/react with our dark theme + sensible defaults.
 */
import React, { useRef } from 'react'
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

export default function MonacoEditor({
  path     = '',
  value    = '',
  onChange,
  readOnly = false,
  height   = '100%',
  onSave,            // called with current value on Ctrl+S
}) {
  const editorRef = useRef(null)

  function handleMount(editor, monaco) {
    editorRef.current = editor

    // Define MaxCoder dark theme (matches our CSS variables)
    monaco.editor.defineTheme('maxcoder-dark', {
      base:    'vs-dark',
      inherit: true,
      rules:   [],
      colors: {
        'editor.background':           '#0f1117',
        'editor.foreground':           '#e2e8f0',
        'editorLineNumber.foreground': '#4a5568',
        'editorLineNumber.activeForeground': '#94a3b8',
        'editor.lineHighlightBackground': '#1a1d2780',
        'editor.selectionBackground':  '#5b6af040',
        'editorCursor.foreground':     '#7c8aff',
        'editorWidget.background':     '#1a1d27',
        'editorWidget.border':         '#2e3250',
        'input.background':            '#22263a',
        'input.foreground':            '#e2e8f0',
        'scrollbarSlider.background':  '#2e325060',
        'scrollbarSlider.hoverBackground': '#5b6af060',
      },
    })
    monaco.editor.setTheme('maxcoder-dark')

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
      theme="maxcoder-dark"
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
