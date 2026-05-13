/**
 * LivePreview — renders code output based on language.
 *
 *  HTML / CSS / SVG / Markdown  →  live iframe preview
 *  Python / JS / Bash           →  terminal stdout/stderr panel
 *  Other                        →  "no runtime" info panel
 */
import React, { useEffect, useRef, useState } from 'react'

const VISUAL_LANGS  = new Set(['html', 'css', 'svg', 'markdown', 'md', ''])
const TERMINAL_LANGS = new Set(['python', 'javascript', 'bash', 'shell', 'go', 'rust', 'java'])
const NO_RUN_LANGS  = new Set(['sql', 'solidity', 'dockerfile', 'yaml', 'toml', 'json', 'terraform', 'prisma'])

// ── Helpers ───────────────────────────────────────────────────────────────────
function mdToHtml(md) {
  // Very minimal Markdown → HTML (headings, bold, italic, code, links)
  return md
    .replace(/^### (.+)$/gm, '<h3>$1</h3>')
    .replace(/^## (.+)$/gm,  '<h2>$1</h2>')
    .replace(/^# (.+)$/gm,   '<h1>$1</h1>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g,    '<em>$1</em>')
    .replace(/`(.+?)`/g,     '<code>$1</code>')
    .replace(/\n/g,          '<br/>')
}

function buildPreviewHtml(code, lang) {
  if (lang === 'html')                    return code
  if (lang === 'css')
    return `<!DOCTYPE html><html><head><style>${code}</style></head><body>
      <div style="font-family:sans-serif;padding:16px">
        <h1>Heading 1</h1><h2>Heading 2</h2>
        <p>Paragraph. <a href="#">Link</a>. <strong>Bold</strong>. <em>Italic</em>.</p>
        <button>Button</button>
        <input type="text" placeholder="Input field" style="margin-left:8px"/>
        <ul><li>List item one</li><li>List item two</li></ul>
      </div></body></html>`
  if (lang === 'svg')
    return `<!DOCTYPE html><html><body style="margin:0;background:#0f1117">${code}</body></html>`
  if (lang === 'markdown' || lang === 'md')
    return `<!DOCTYPE html><html><head><style>
      body{font-family:'Inter',sans-serif;max-width:720px;margin:32px auto;color:#e2e8f0;background:#0f1117;padding:0 24px}
      h1,h2,h3{color:#fff;margin-top:1.5em}code{background:#22263a;padding:2px 6px;border-radius:4px;font-size:.85em}
    </style></head><body>${mdToHtml(code)}</body></html>`
  return code
}

// ── Iframe Preview ────────────────────────────────────────────────────────────
function IframePreview({ code, lang }) {
  const iframeRef  = useRef(null)
  const [key, setKey] = useState(0)

  useEffect(() => {
    setKey(k => k + 1)
  }, [code, lang])

  const html = buildPreviewHtml(code, lang)

  return (
    <iframe
      key={key}
      ref={iframeRef}
      srcDoc={html}
      sandbox="allow-scripts allow-same-origin"
      className="w-full h-full border-0 bg-white"
      title="Live Preview"
    />
  )
}

// ── Terminal Panel ────────────────────────────────────────────────────────────
function TerminalPanel({ result }) {
  if (!result) {
    return (
      <div className="flex items-center justify-center h-full text-muted text-sm">
        Run result will appear here
      </div>
    )
  }

  const { ok, stdout, stderr, code: exitCode, lang } = result

  return (
    <div className="flex flex-col h-full bg-bg font-mono text-xs">
      {/* Status bar */}
      <div className={`flex items-center gap-2 px-4 py-2 border-b border-border text-xs font-semibold
        ${ok ? 'text-green-400 bg-green-500/5' : 'text-red-400 bg-red-500/5'}`}>
        <span className={`w-2 h-2 rounded-full ${ok ? 'bg-green-400' : 'bg-red-400'}`} />
        {ok ? 'Process exited 0' : `Process exited ${exitCode}`}
        {lang && <span className="ml-auto text-muted font-normal">{lang}</span>}
      </div>

      {/* Output */}
      <div className="flex-1 overflow-auto p-4 space-y-3">
        {stdout && (
          <div>
            <div className="text-muted text-[10px] uppercase tracking-widest mb-1">stdout</div>
            <pre className="text-green-300 whitespace-pre-wrap break-all leading-relaxed">{stdout}</pre>
          </div>
        )}
        {stderr && (
          <div>
            <div className="text-muted text-[10px] uppercase tracking-widest mb-1">stderr</div>
            <pre className="text-red-400 whitespace-pre-wrap break-all leading-relaxed">{stderr}</pre>
          </div>
        )}
        {!stdout && !stderr && (
          <p className="text-muted">(no output)</p>
        )}
      </div>
    </div>
  )
}

// ── No-Runtime Panel ──────────────────────────────────────────────────────────
function NoRuntimePanel({ lang }) {
  const tips = {
    sql:        'SQL runner against a local SQLite DB is coming in Phase 3.',
    dockerfile: 'Dockerfile cannot be run in-browser. Use: docker build .',
    yaml:       'YAML/TOML files are config — no runtime needed.',
    toml:       'YAML/TOML files are config — no runtime needed.',
    json:       'JSON is data — no runtime needed.',
    solidity:   'Solidity requires Hardhat or Foundry. Coming in Phase 3.',
    terraform:  'Terraform requires the tf CLI. Run: terraform plan',
    default:    `'${lang}' has no direct runtime. View the code and run it manually.`,
  }

  return (
    <div className="flex flex-col items-center justify-center h-full text-center px-8 gap-3">
      <div className="text-4xl">📄</div>
      <p className="text-text font-semibold text-sm">{lang ? lang.toUpperCase() : 'Unknown'} file</p>
      <p className="text-muted text-xs max-w-xs leading-relaxed">
        {tips[lang] || tips.default}
      </p>
    </div>
  )
}

// ── Main LivePreview ──────────────────────────────────────────────────────────
export default function LivePreview({ code = '', lang = '', runResult = null }) {
  const l = lang.toLowerCase()

  if (VISUAL_LANGS.has(l)) {
    return <IframePreview code={code} lang={l} />
  }
  if (TERMINAL_LANGS.has(l)) {
    return <TerminalPanel result={runResult} />
  }
  return <NoRuntimePanel lang={l} />
}