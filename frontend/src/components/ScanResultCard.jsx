import Badge from './Badge.jsx'
import ScoreRing from './ScoreRing.jsx'

export default function ScanResultCard({
  ruleName,
  table,
  column,
  score,
  status,
  failedRows,
  totalRows,
  reason,
  severity,
}) {
  const scoreColor =
    score >= 80 ? 'var(--success)' :
    score >= 60 ? 'var(--warning)' : 'var(--danger)'

  return (
    <div
      style={{
        background: 'var(--bg-surface)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--radius-sm)',
        padding: '16px 18px',
        marginBottom: 10,
        boxShadow: 'var(--shadow-sm)',
        transition: 'box-shadow 0.2s',
      }}
      onMouseEnter={e => e.currentTarget.style.boxShadow = 'var(--shadow-md)'}
      onMouseLeave={e => e.currentTarget.style.boxShadow = 'var(--shadow-sm)'}
    >
      {/* Top row */}
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 14 }}>
        <ScoreRing score={score} size={52} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <span style={{ fontWeight: 600, color: 'var(--text-primary)', fontSize: 13 }}>
              {ruleName}
            </span>
            <Badge label={status} type={status} />
            <Badge label={severity} type={severity === 'critical' ? 'critical' : severity === 'warning' ? 'warning' : 'info'} />
          </div>
          <div style={{
            color: 'var(--text-muted)',
            fontSize: 12,
            marginTop: 3,
            fontFamily: 'var(--font-mono)',
          }}>
            {table}.{column}
          </div>
          <div style={{ fontSize: 12, marginTop: 5, color: scoreColor, fontWeight: 500 }}>
            {failedRows > 0 ? `${failedRows} of ${totalRows} rows failed` : `All ${totalRows} rows passed`}
          </div>
        </div>
      </div>

      {/* Reason box — only when something failed */}
      {reason && (
        <div
          style={{
            marginTop: 14,
            padding: '12px 14px',
            background: 'var(--danger-bg)',
            borderLeft: '3px solid var(--danger)',
            borderRadius: '0 var(--radius-sm) var(--radius-sm) 0',
            color: '#b91c1c',
            fontSize: 12,
            lineHeight: 1.7,
          }}
        >
          {reason}
        </div>
      )}
    </div>
  )
}
