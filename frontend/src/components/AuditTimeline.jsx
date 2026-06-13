/**
 * AuditTimeline
 * ──────────────
 * Vertical timeline of governance events for a given integration.
 * Data from GET /audit/logs/{integrationId}
 * Auto-refreshes every 30 seconds.
 *
 * Props:
 *   integrationId  — string (optional — if omitted, shows all events)
 */

import { useEffect, useState, useRef } from 'react'
import { RefreshCw, ChevronDown, ChevronRight } from 'lucide-react'
import { getAuditLogs, getIntegrationAuditLog, auditExportUrl } from '../api/client.js'

// ── Event type → dot colour ───────────────────────────────────────────────────
function dotColor(event_type, status) {
  if (status === 'failure' || event_type?.includes('FAIL') || event_type?.includes('ERROR')) {
    return '#ef4444'
  }
  const map = {
    CONNECT:          '#3b82f6',
    FETCH_STARTED:    '#f59e0b',
    FETCH_COMPLETED:  '#10b981',
    SCAN_TRIGGERED:   '#8b5cf6',
    SCAN_COMPLETED:   '#10b981',
    SCAN_FAILED:      '#ef4444',
    RULE_CREATED:     '#06b6d4',
    POLICY_CREATED:   '#6366f1',
    POLICY_PUBLISHED: '#10b981',
    TEMPLATE_CREATED: '#94a3b8',
  }
  return map[event_type] || '#475569'
}

function relativeTime(isoString) {
  if (!isoString) return '—'
  const diff = Date.now() - new Date(isoString).getTime()
  const secs = Math.floor(diff / 1000)
  if (secs < 5)   return 'just now'
  if (secs < 60)  return `${secs}s ago`
  const mins = Math.floor(secs / 60)
  if (mins < 60)  return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24)   return `${hrs}h ago`
  return new Date(isoString).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

function absoluteTime(isoString) {
  if (!isoString) return '—'
  return new Date(isoString).toLocaleString('en-US', {
    month: 'short', day: 'numeric',
    hour: 'numeric', minute: '2-digit',
  })
}

function MetadataBox({ metadata }) {
  if (!metadata || Object.keys(metadata).length === 0) return null
  return (
    <pre style={{
      background: '#0d1626',
      border: '1px solid #1e293b',
      borderRadius: 6,
      padding: '8px 12px',
      marginTop: 8,
      fontSize: 11,
      color: '#94a3b8',
      fontFamily: '"JetBrains Mono", Consolas, monospace',
      overflowX: 'auto',
      whiteSpace: 'pre-wrap',
      wordBreak: 'break-word',
    }}>
      {Object.entries(metadata).map(([k, v]) => (
        `${k}: ${typeof v === 'object' ? JSON.stringify(v) : v}\n`
      ))}
    </pre>
  )
}

function TimelineEntry({ entry, isLast }) {
  const [expanded, setExpanded] = useState(false)
  const color = dotColor(entry.event_type, entry.status)
  const hasMetadata = entry.metadata && Object.keys(entry.metadata).length > 0

  return (
    <div style={{ display: 'flex', gap: 14, position: 'relative' }}>
      {/* Left: dot + line */}
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', width: 16 }}>
        <div style={{
          width: 11, height: 11, borderRadius: '50%',
          background: color,
          flexShrink: 0,
          boxShadow: `0 0 6px ${color}60`,
          marginTop: 3,
          zIndex: 1,
        }} />
        {!isLast && (
          <div style={{
            width: 1.5,
            flex: 1,
            background: 'linear-gradient(to bottom, #1e293b, #0f172a)',
            minHeight: 20,
            marginTop: 4,
          }} />
        )}
      </div>

      {/* Right: content */}
      <div style={{ flex: 1, paddingBottom: isLast ? 0 : 18 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }}>
          {/* Event type badge */}
          <div>
            <span style={{
              fontSize: 11, fontWeight: 700,
              color: color,
              background: `${color}18`,
              border: `1px solid ${color}30`,
              borderRadius: 4, padding: '2px 7px',
              letterSpacing: '0.3px',
            }}>
              {entry.event_type}
            </span>
          </div>

          {/* Timestamp */}
          <div style={{ textAlign: 'right', flexShrink: 0 }}>
            <div style={{ fontSize: 11, color: '#64748b' }} title={absoluteTime(entry.created_at)}>
              {relativeTime(entry.created_at)}
            </div>
            <div style={{ fontSize: 10, color: '#334155', marginTop: 1 }}>
              {absoluteTime(entry.created_at)}
            </div>
          </div>
        </div>

        {/* Description */}
        <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 5, lineHeight: 1.5 }}>
          {entry.description}
        </div>

        {/* Expand toggle */}
        {hasMetadata && (
          <button
            onClick={() => setExpanded(x => !x)}
            style={{
              display: 'flex', alignItems: 'center', gap: 4,
              marginTop: 6, background: 'none', border: 'none',
              color: '#475569', fontSize: 11, cursor: 'pointer',
              padding: 0, fontFamily: 'inherit',
            }}
          >
            {expanded ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
            {expanded ? 'Hide' : 'Show'} details
          </button>
        )}
        {expanded && <MetadataBox metadata={entry.metadata} />}
      </div>
    </div>
  )
}

export default function AuditTimeline({ integrationId }) {
  const [logs, setLogs]         = useState([])
  const [loading, setLoading]   = useState(true)
  const [error, setError]       = useState(null)
  const [total, setTotal]       = useState(0)
  const [offset, setOffset]     = useState(0)
  const limit = 50
  const timerRef                = useRef(null)

  const fetchLogs = (off = 0, append = false) => {
    const call = integrationId
      ? getIntegrationAuditLog(integrationId, limit)
      : getAuditLogs({ limit, offset: off })

    call
      .then(data => {
        const incoming = data.logs || []
        setLogs(prev => append ? [...prev, ...incoming] : incoming)
        setTotal(data.total ?? incoming.length)
        setLoading(false)
        setError(null)
      })
      .catch(e => {
        setError(e.message)
        setLoading(false)
      })
  }

  useEffect(() => {
    fetchLogs(0)
    timerRef.current = setInterval(() => fetchLogs(0), 30_000)
    return () => clearInterval(timerRef.current)
  }, [integrationId]) // eslint-disable-line react-hooks/exhaustive-deps

  const loadMore = () => {
    const next = offset + limit
    setOffset(next)
    fetchLogs(next, true)
  }

  const handleExport = () => {
    window.open(auditExportUrl(integrationId), '_blank')
  }

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
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ fontSize: 15 }}>📋</span>
          <div>
            <div style={{ fontWeight: 600, fontSize: 14, color: '#e2e8f0' }}>Audit Log</div>
            <div style={{ fontSize: 11, color: '#475569', marginTop: 2 }}>
              Append-only governance event trail
              {total > 0 && ` · ${total} events`}
            </div>
          </div>
        </div>

        <div style={{ display: 'flex', gap: 8 }}>
          <button
            onClick={() => { setOffset(0); fetchLogs(0) }}
            style={{
              background: 'transparent', border: '1px solid #1e293b',
              borderRadius: 6, padding: '5px 10px',
              color: '#64748b', cursor: 'pointer', fontSize: 11,
              display: 'flex', alignItems: 'center', gap: 5,
              fontFamily: 'inherit',
            }}
          >
            <RefreshCw size={11} /> Refresh
          </button>
          <button
            onClick={handleExport}
            style={{
              background: 'transparent', border: '1px solid #1e293b',
              borderRadius: 6, padding: '5px 10px',
              color: '#64748b', cursor: 'pointer', fontSize: 11,
              fontFamily: 'inherit',
            }}
          >
            Export CSV
          </button>
        </div>
      </div>

      {/* Timeline */}
      <div style={{ padding: '20px 24px' }}>
        {loading && (
          <div style={{ color: '#475569', fontSize: 13 }}>Loading audit log…</div>
        )}
        {error && (
          <div style={{ color: '#ef4444', fontSize: 13 }}>Error: {error}</div>
        )}
        {!loading && !error && logs.length === 0 && (
          <div style={{ textAlign: 'center', color: '#334155', fontSize: 13, padding: '24px 0' }}>
            No audit events yet.<br />
            <span style={{ fontSize: 12, color: '#1e3a5f' }}>
              Connect a database and run a fetch to start the trail.
            </span>
          </div>
        )}

        {logs.map((entry, i) => (
          <TimelineEntry
            key={entry.id}
            entry={entry}
            isLast={i === logs.length - 1 && logs.length >= total}
          />
        ))}

        {/* Load more */}
        {logs.length < total && (
          <div style={{ textAlign: 'center', marginTop: 12 }}>
            <div style={{ fontSize: 11, color: '#475569', marginBottom: 8 }}>
              Showing {logs.length} of {total} events
            </div>
            <button
              onClick={loadMore}
              style={{
                background: 'transparent', border: '1px solid #1e293b',
                borderRadius: 6, padding: '6px 16px',
                color: '#64748b', cursor: 'pointer', fontSize: 12,
                fontFamily: 'inherit',
              }}
            >
              Load more
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
