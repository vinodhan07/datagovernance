/**
 * LineageGraph
 * ─────────────
 * Visualises the data lineage pipeline as an SVG node/edge graph.
 * Data from GET /lineage/{integrationId}/graph
 *
 * Layout: horizontal left-to-right, 6 node positions.
 * Arrows: SVG bezier curves with arrowheads.
 * No external graph library — pure SVG + CSS.
 */

import { useEffect, useState } from 'react'

const BASE = 'http://localhost:8000'

// ── Node colours by type ──────────────────────────────────────────────────────
const NODE_STYLE = {
  source: { border: '#06b6d4', bg: 'rgba(6,182,212,0.08)', icon: '🗄️' },
  process: { border: '#3b82f6', bg: 'rgba(59,130,246,0.08)', icon: '⚙️' },
  destination: { border: '#8b5cf6', bg: 'rgba(139,92,246,0.08)', icon: '🐘' },
  frontend: { border: '#14b8a6', bg: 'rgba(20,184,166,0.08)', icon: '📊' },
}

// Status → colour for edge/node indicators
const STATUS_COLOR = {
  success: '#10b981',
  error: '#ef4444',
  neutral: '#334155',
}

// ── Fixed layout positions (x, y) for each node id ───────────────────────────
const NODE_POS = {
  mariadb: { x: 30, y: 90 },
  extraction: { x: 210, y: 90 },
  quality: { x: 400, y: 90 },
  results_db: { x: 590, y: 90 },
  frontend: { x: 780, y: 90 },
}
const NODE_W = 140
const NODE_H = 64
const SVG_W = 960
const SVG_H = 220

function NodeCard({ node }) {
  const style = NODE_STYLE[node.type] || NODE_STYLE.process
  const statusColor = STATUS_COLOR[node.status] || STATUS_COLOR.neutral
  const pos = NODE_POS[node.id] || { x: 0, y: 0 }

  return (
    <foreignObject
      x={pos.x} y={pos.y}
      width={NODE_W} height={NODE_H}
      style={{ overflow: 'visible' }}
    >
      <div
        xmlns="http://www.w3.org/1999/xhtml"
        style={{
          width: NODE_W, height: NODE_H,
          background: style.bg,
          border: `1.5px solid ${style.border}`,
          borderRadius: 10,
          padding: '8px 12px',
          display: 'flex', flexDirection: 'column', justifyContent: 'center',
          position: 'relative',
        }}
      >
        {/* Status dot */}
        <div style={{
          position: 'absolute', top: 8, right: 8,
          width: 7, height: 7, borderRadius: '50%',
          background: statusColor,
          boxShadow: node.status === 'success' ? `0 0 6px ${statusColor}` : 'none',
        }} />
        <div style={{ fontSize: 11, marginBottom: 2 }}>{style.icon}</div>
        <div style={{
          fontWeight: 600, fontSize: 12, color: '#e2e8f0',
          lineHeight: 1.3,
        }}>
          {node.label}
        </div>
        <div style={{ fontSize: 10, color: '#64748b', marginTop: 2 }}>
          {node.type}
        </div>
      </div>
    </foreignObject>
  )
}

function EdgeArrow({ edge, nodes }) {
  const fromNode = nodes.find(n => n.id === edge.from)
  const toNode = nodes.find(n => n.id === edge.to)
  if (!fromNode || !toNode) return null

  const fromPos = NODE_POS[edge.from]
  const toPos = NODE_POS[edge.to]
  if (!fromPos || !toPos) return null

  const x1 = fromPos.x + NODE_W
  const y1 = fromPos.y + NODE_H / 2
  const x2 = toPos.x
  const y2 = toPos.y + NODE_H / 2
  const cx1 = x1 + (x2 - x1) * 0.5
  const cy1 = y1
  const cx2 = x1 + (x2 - x1) * 0.5
  const cy2 = y2

  const color = STATUS_COLOR[edge.status] || STATUS_COLOR.neutral
  const midX = (x1 + x2) / 2
  const midY = (y1 + y2) / 2 - 10

  return (
    <g>
      <defs>
        <marker
          id={`arrow-${edge.id}`}
          markerWidth="8" markerHeight="8"
          refX="6" refY="3"
          orient="auto"
        >
          <path d="M0,0 L0,6 L8,3 z" fill={color} opacity={0.7} />
        </marker>
      </defs>
      <path
        d={`M ${x1} ${y1} C ${cx1} ${cy1}, ${cx2} ${cy2}, ${x2} ${y2}`}
        stroke={color}
        strokeWidth={1.5}
        fill="none"
        opacity={0.6}
        markerEnd={`url(#arrow-${edge.id})`}
      />
      <text
        x={midX} y={midY}
        textAnchor="middle"
        fill="#475569"
        fontSize={9}
        fontFamily="monospace"
      >
        {edge.label}
      </text>
    </g>
  )
}

function RunSummaryBar({ lastRun }) {
  if (!lastRun) return (
    <div style={{ textAlign: 'center', color: '#475569', fontSize: 12, padding: '10px 0' }}>
      No pipeline runs yet — click Fetch Data to start
    </div>
  )

  const started = lastRun.started_at
    ? new Date(lastRun.started_at).toLocaleString()
    : '—'

  const duration = lastRun.started_at && lastRun.completed_at
    ? `${((new Date(lastRun.completed_at) - new Date(lastRun.started_at)) / 1000).toFixed(1)}s`
    : '—'

  const totalRows = Object.values(lastRun.row_counts || {}).reduce((a, b) => a + b, 0)
  const statusColor = lastRun.status === 'completed' ? '#10b981'
    : lastRun.status === 'failed' ? '#ef4444' : '#f59e0b'

  return (
    <div style={{
      display: 'flex', gap: 24, flexWrap: 'wrap',
      padding: '12px 16px',
      background: 'rgba(15,23,42,0.6)',
      borderTop: '1px solid #1e293b',
      borderRadius: '0 0 10px 10px',
      fontSize: 12,
    }}>
      {[
        ['Started', started],
        ['Duration', duration],
        ['Tables', (lastRun.tables_scanned || []).length],
        ['Total rows', totalRows],
        ['Quality', lastRun.quality_score != null ? `${lastRun.quality_score}%` : '—'],
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
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!integrationId) return
    setLoading(true)
    fetch(`${BASE}/lineage/${integrationId}/graph`)
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false) })
      .catch(e => { setError(e.message); setLoading(false) })
  }, [integrationId])

  if (loading) return (
    <div style={{ color: '#475569', fontSize: 13, padding: 20 }}>Loading lineage graph…</div>
  )
  if (error) return (
    <div style={{ color: '#ef4444', fontSize: 13, padding: 20 }}>Failed to load: {error}</div>
  )
  if (!data) return null

  const nodes = data.nodes || []
  const edges = data.edges || []

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
          <div style={{ fontWeight: 600, fontSize: 14, color: '#e2e8f0' }}>Data Lineage Graph</div>
          <div style={{ fontSize: 11, color: '#475569', marginTop: 2 }}>
            How data flows from MariaDB through DataGuard — read-only at every step
          </div>
        </div>
      </div>

      {/* Spline Visualization Embedded View */}
      <div style={{ padding: data.spline_url ? '0' : '60px 40px', textAlign: 'center', background: '#0a0f1d' }}>
        {data.spline_url ? (
          <div style={{ height: 600, position: 'relative' }}>
            <iframe 
              src={data.spline_url}
              style={{ width: '100%', height: '100%', border: 'none' }}
              title="Spline Lineage"
            />
            <div style={{ 
              position: 'absolute', bottom: 12, right: 12, 
              background: 'rgba(15,23,42,0.85)', padding: '6px 12px', 
              borderRadius: 6, fontSize: 11, color: '#fff', 
              backdropFilter: 'blur(4px)', border: '1px solid rgba(255,255,255,0.1)'
            }}>
              Live Spline View
            </div>
          </div>
        ) : (
          <div style={{ color: '#475569', fontSize: 14 }}>
            <div style={{ fontSize: 32, marginBottom: 12 }}>⏱️</div>
            Waiting for a pipeline run to generate Spline lineage...
          </div>
        )}
      </div>

      {/* Run summary */}
      <RunSummaryBar lastRun={data.last_run} />
    </div>
  )
}
