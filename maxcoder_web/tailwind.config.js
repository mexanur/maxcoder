/** @type {import('tailwindcss').Config} */
// Mirrors the CSS variables in src/index.css so Tailwind utilities resolve to
// the same tokens the app actually uses. Edit colors in index.css :root, not here.
export default {
  content: ['./index.html','./src/**/*.{js,jsx,ts,tsx}'],
  darkMode: ['class', "[data-theme='dark']"],
  theme: {
    extend: {
      colors: {
        chrome:    { deep: 'var(--chrome-deep)', DEFAULT: 'var(--chrome-bg)', secondary: 'var(--chrome-secondary)' },
        sidebar:   'var(--sidebar-bg)',
        content:   'var(--content-bg)',
        surface:   'var(--surface-low)',
        border:    { DEFAULT: 'var(--border)', light: 'var(--border-light)', dim: 'var(--border-dim)' },
        text:      { primary: 'var(--text-primary)', secondary: 'var(--text-secondary)', muted: 'var(--text-muted)', dim: 'var(--text-dim)' },
        accent:    { DEFAULT: 'var(--accent)', hover: 'var(--accent-hover)' },
        success:   'var(--success)',
        danger:    'var(--danger)',
        warn:      'var(--warn)',
        info:      'var(--info)',
      },
      fontFamily: {
        sans: ['Inter','-apple-system','BlinkMacSystemFont','Segoe UI','sans-serif'],
        mono: ['JetBrains Mono','ui-monospace','Menlo','Consolas','monospace'],
      },
      fontSize: {
        xs:   ['11px', { lineHeight: '1.5' }],
        sm:   ['12px', { lineHeight: '1.55' }],
        base: ['13px', { lineHeight: '1.55' }],
        body: ['15px', { lineHeight: '1.65' }],
        h:    ['22px', { lineHeight: '1.2',  letterSpacing: '-0.01em' }],
        display: ['32px', { lineHeight: '1.1', letterSpacing: '-0.018em' }],
      },
      borderRadius: {
        sm: '3px',
        md: '6px',
        lg: '10px',
      },
    },
  },
  plugins: [],
}
