import { useEffect, useState } from 'react'
import { getAuthHeader } from '../api/client.js'

const BASE = 'http://localhost:8000'

function RunSummaryBar({ lastRun }) {
  if (!lastRun) return (
    <div style={{ textAlign: 'center', color: '#475569', fontSize: 12, padding: '10px 0' }}>
      No pipeline runs yet — click Fetch &amp; Analyse to start
    </div>
  )

  const started  = lastRun.started_at  ? new Date(lastRun.started_at).toLocaleString()  : '—'
  const duration = lastRun.started_at && lastRun.completed_at
    ? `${((new Date(lastRun.completed_at) - new Date(lastRun.started_at)) / 1000).toFixed(1)}s` : '—'
  const totalRows = Object.values(lastRun.row_counts || {}).reduce((a, b) => a + b, 0)
  const statusColor = lastRun.status === 'completed' ? '#10b981'
    : lastRun.status === 'failed' ? '#ef4444' : '#f59e0b'

  return (
    <div style={{
      display: 'flex', gap: 24, flexWrap: 'wrap',
      padding: '12px 16px',
      background: 'rgba(15,23,42,0.6)',
      borderTop: '1px solid #1e293b',
      fontSize: 12,
    }}>
      {[
        ['Started',    started],
        ['Duration',   duration],
        ['Tables',     (lastRun.tables_scanned || []).length],
        ['Total rows', totalRows],
      ].map(([label, val]) => (
        <div key={label}>
          <span style={{ color: '#475569' }}>{label}: </span>
          <span style={{ color: '#cbd5e1', fontWeight: 600 }}>{val}</span>
        </div>
      ))}
      <div>
        <span style={{ color: '#475569' }}>Status: </span>
        <span style={{
          color: statusColor, fontWeight: 600,
          background: `${statusColor}18`,
          border: `1px solid ${statusColor}40`,
          borderRadius: 4, padding: '1px 7px', fontSize: 11,
        }}>
          {lastRun.status}
        </span>
      </div>
    </div>
  )
}

export default function LineageGraph({ integrationId }) {
  const [data,    setData]    = useState(null)
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState(null)

  useEffect(() => {
    if (!integrationId) return
    setLoading(true)
    fetch(`${BASE}/lineage/${integrationId}/graph`, {
      headers: getAuthHeader(),
    })
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false) })
      .catch(e => { setError(e.message); setLoading(false) })
  }, [integrationId])

  if (loading) return (
    <div style={{ color: '#475569', fontSize: 13, padding: 20 }}>Loading lineage…</div>
  )
  if (error) return (
    <div style={{ color: '#ef4444', fontSize: 13, padding: 20 }}>Failed to load: {error}</div>
  )
  if (!data) return null

  const lastRun   = data.last_run
  const splineUrl = data.spline_url

  return (
    <div style={{
      background: 'var(--bg-surface, #0f172a)',
      border: '1px solid var(--border, #1e293b)',
      borderRadius: 12,
      overflow: 'hidden',
      marginBottom: 24,
    }}>
      {/* Header */}
      <div style={{
        padding: '14px 20px',
        borderBottom: '1px solid #1e293b',
        display: 'flex', alignItems: 'center', gap: 10,
      }}>
        <span style={{ fontSize: 15 }}>🔀</span>
        <div>
          <div style={{ fontWeight: 600, fontSize: 14, color: '#e2e8f0' }}>Data Lineage — Spline</div>
          <div style={{ fontSize: 11, color: '#475569', marginTop: 2 }}>
            Column-level lineage captured by Apache Spline
          </div>
        </div>
        {splineUrl && (
          <a
            href={splineUrl}
            target="_blank"
            rel="noreferrer"
            style={{
              marginLeft: 'auto', fontSize: 11, color: '#06b6d4',
              textDecoration: 'none',
              background: 'rgba(6,182,212,0.08)',
              border: '1px solid rgba(6,182,212,0.25)',
              borderRadius: 6, padding: '4px 10px',
            }}
          >
            Open in Spline ↗
          </a>
        )}
      </div>

      {/* Spline iframe or status message */}
      <div style={{ background: '#0a0f1d' }}>
        {splineUrl ? (
          <div style={{ height: 560, position: 'relative' }}>
            <iframe
              src={splineUrl}
              style={{ width: '100%', height: '100%', border: 'none' }}
              title="Spline Lineage"
              allowFullScreen
            />
          </div>
        ) : lastRun && lastRun.status === 'completed' ? (
          <div style={{ padding: '52px 40px', textAlign: 'center' }}>
            <div style={{ fontSize: 30, marginBottom: 14 }}>🔄</div>
            <div style={{ color: '#e2e8f0', fontWeight: 600, fontSize: 14, marginBottom: 8 }}>
              Previous run completed without Spline lineage
            </div>
            <div style={{ color: '#475569', fontSize: 12, maxWidth: 420, margin: '0 auto', lineHeight: 1.7 }}>
              DataGuard now auto-injects Spline into your ETL script.<br />
              Click <strong style={{ color: '#14b8a6' }}>Re-fetch Data</strong> to run again — lineage will be captured automatically.
            </div>
          </div>
        ) : (
          <div style={{ padding: '60px 40px', textAlign: 'center' }}>
            <div style={{ fontSize: 32, marginBottom: 12 }}>⏱️</div>
            <div style={{ color: '#475569', fontSize: 14 }}>
              Waiting for a pipeline run to generate Spline lineage…
            </div>
          </div>
        )}
      </div>

      {/* Run summary footer */}
      <RunSummaryBar lastRun={lastRun} />
    </div>
  )
}
