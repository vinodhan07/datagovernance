const STYLES = {
  passed:    { bg: 'var(--success-bg)',  color: 'var(--success)',  border: 'var(--success-border)' },
  failed:    { bg: 'var(--danger-bg)',   color: 'var(--danger)',   border: 'var(--danger-border)' },
  warning:   { bg: 'var(--warning-bg)',  color: 'var(--warning)',  border: 'var(--warning-border)' },
  draft:     { bg: 'rgba(100,116,139,0.06)', color: '#64748b', border: 'rgba(100,116,139,0.12)' },
  published: { bg: 'var(--success-bg)',  color: 'var(--success)',  border: 'var(--success-border)' },
  active:    { bg: 'var(--success-bg)',  color: 'var(--success)',  border: 'var(--success-border)' },
  inactive:  { bg: 'rgba(100,116,139,0.06)', color: '#94a3b8', border: 'rgba(100,116,139,0.12)' },
  info:      { bg: 'var(--info-bg)',     color: 'var(--info)',     border: 'var(--info-border)' },
  critical:  { bg: 'var(--danger-bg)',   color: 'var(--danger)',   border: 'var(--danger-border)' },
}

export default function Badge({ label, type = 'info' }) {
  const s = STYLES[type] ?? STYLES.info
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        padding: '2px 8px',
        borderRadius: 5,
        fontSize: 11,
        fontWeight: 600,
        letterSpacing: '0.3px',
        background: s.bg,
        color: s.color,
        border: `1px solid ${s.border}`,
        whiteSpace: 'nowrap',
        textTransform: 'capitalize',
      }}
    >
      {label}
    </span>
  )
}
