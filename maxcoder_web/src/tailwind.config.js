/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx,ts,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        // ── Core backgrounds ──────────────────────────────────────────────
        bg:       '#0d0e14',   // near-black — main canvas (was #0f1117)
        surface:  '#12131a',   // panels, sidebars
        surface2: '#1a1b26',   // hover states, inputs
        surface3: '#1e2030',   // active/selected items

        // ── Borders ───────────────────────────────────────────────────────
        border:   '#1e1f2e',   // ultra-thin, almost invisible (was #2e3250)
        borderHi: '#2e3250',   // highlighted border (focus rings etc.)

        // ── Accent ────────────────────────────────────────────────────────
        accent:   '#4f6ef7',   // pure blue — Cursor-like (was #5b6af0)
        accentHi: '#6b84ff',   // hover / brighter accent

        // ── Text ──────────────────────────────────────────────────────────
        text:     '#cdd6f4',   // primary text — slightly cooler white
        muted:    '#6c7086',   // labels, placeholders, secondary
        subtle:   '#313244',   // very faint text, dividers
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', '"Fira Code"', 'monospace'],
      },
      fontSize: {
        '2xs': ['10px', { lineHeight: '14px' }],
        xs:    ['11px', { lineHeight: '16px' }],
        sm:    ['12px', { lineHeight: '18px' }],
        base:  ['13px', { lineHeight: '20px' }],
      },
      borderRadius: {
        sm:  '4px',
        md:  '6px',
        lg:  '8px',
        xl:  '10px',
        '2xl': '12px',
      },
      boxShadow: {
        panel:  '0 0 0 1px #1e1f2e',
        focus:  '0 0 0 2px #4f6ef740',
        glow:   '0 0 12px #4f6ef730',
      },
    },
  },
  plugins: [],
}
