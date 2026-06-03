/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx,ts,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['DM Sans', 'ui-sans-serif', 'system-ui'],
      },
      colors: {
        'bg-base':     '#020817',
        'bg-surface':  '#0a0f1a',
        'bg-elevated': '#0f172a',
        'bg-panel':    '#1e293b',
        'border-col':  '#1e293b',
        'border-active':'#3b82f6',
        'text-primary':'#f1f5f9',
        'text-muted':  '#64748b',
        'text-hint':   '#334155',
        'accent-blue': '#3b82f6',
        'accent-green':'#10b981',
        'accent-red':  '#ef4444',
        'accent-yellow':'#f59e0b',
        'accent-purple':'#8b5cf6',
      },
    },
  },
  plugins: [],
}
