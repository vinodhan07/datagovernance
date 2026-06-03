/**
 * CatalogSnapshot
 * ────────────────
 * Shows the most recent catalog snapshot with per-column statistics.
 * Data from GET /catalog/{integrationId}/latest
 *
 * Features:
 *  - "Take Snapshot" button → POST /catalog/{id}/snapshot
 *  - Per-table cards with column stats (type, null %, unique count)
 *  - Schema change banner if diff detected
 *  - Colour-coded null % badges
 *
 * Props:
 *   integrationId — string
 */

import { useEffect, useState } from 'react'
import { RefreshCw, Camera } from 'lucide-react'

const BASE = 'http://localhost:8000'

// Null % → badge colour
function nullBadge(null_pct) {
  if (null_pct === 0)    return { bg: 'rgba(16,185,129,0.12)', color: '#10b981', border: 'rgba(16,185,129,0.2)' }
  if (null_pct <= 5)     return { bg: 'rgba(245,158,11,0.10)', color: '#f59e0b', border: 'rgba(245,158,11,0.2)' }
  return                        { bg: 'rgba(239,68,68,0.10)',  color: '#ef4444', border: 'rgba(239,68,68,0.2)' }
}

function ColTable({ columns }) {
  const cols = Object.entries(columns || {})
  if (cols.length === 0) return (
    <div style={{ fontSize: 12, color: '#475569', padding: '8px 0' }}>No columns found</div>
  )

  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{
        width: '100%', borderCollapse: 'collapse',
        fontSize: 12, fontFamily: 'inherit',
      }}>
        <thead>
          <tr style={{ borderBottom: '1px solid #1e293b' }}>
            {['Column', 'Type', 'PK', 'Null %', 'Null count', 'Unique'].map(h => (
              <th key={h} style={{
                textAlign: 'left', padding: '6px 10px',
                color: '#475569', fontWeight: 600, fontSize: 11,
                whiteSpace: 'nowrap',
              }}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {cols.map(([col, meta]) => {
            const nb = nullBadge(meta.null_pct ?? 0)
            return (
              <tr key={col} style={{ borderBottom: '1px solid #0f172a' }}
                onMouseEnter={e => e.currentTarget.style.background = '#0d1626'}
                onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
              >
                <td style={{ padding: '7px 10px', color: '#cbd5e1', fontWeight: 500 }}>
                  {col}
                </td>
                <td style={{ padding: '7px 10px', color: '#64748b', fontFamily: 'monospace', fontSize: 11 }}>
                  {meta.type}
                </td>
                <td style={{ padding: '7px 10px', textAlign: 'center' }}>
                  {meta.is_primary_key
                    ? <span style={{ color: '#f59e0b', fontSize: 13 }}>🔑</span>
                    : <span style={{ color: '#1e293b' }}>—</span>
                  }
                </td>
                <td style={{ padding: '7px 10px' }}>
                  <span style={{
                    background: nb.bg, color: nb.color,
                    border: `1px solid ${nb.border}`,
                    borderRadius: 4, padding: '1px 7px', fontSize: 11,
                    fontWeight: 600,
                  }}>
                    {(meta.null_pct ?? 0).toFixed(1)}%
                  </span>
                </td>
                <td style={{ padding: '7px 10px', color: '#64748b', textAlign: 'center' }}>
                  {meta.null_count ?? '—'}
                </td>
                <td style={{ padding: '7px 10px', color: '#64748b', textAlign: 'center' }}>
                  {meta.unique_count ?? '—'}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function ChangeBanner({ changes }) {
  if (!changes || !changes.has_changes) return null

  const items = [
    ...( changes.new_tables || []).map(t => `New table: ${t}`),
    ...(changes.dropped_tables || []).map(t => `Dropped table: ${t}`),
    ...(changes.new_columns || []).map(c => `New column: ${c.table}.${c.column} (${c.type})`),
    ...(changes.changed_columns || []).map(c =>
      `Type change: ${c.table}.${c.column} ${c.old_type} → ${c.new_type}`
    ),
  ]

  return (
    <div style={{
      background: 'rgba(245,158,11,0.07)',
      border: '1px solid rgba(245,158,11,0.2)',
      borderRadius: 8, padding: '10px 14px',
      marginBottom: 16,
    }}>
      <div style={{ fontWeight: 600, fontSize: 12, color: '#f59e0b', marginBottom: 6 }}>
        ⚠ Schema changes detected since last snapshot
      </div>
      {items.map((item, i) => (
        <div key={i} style={{ fontSize: 12, color: '#94a3b8', lineHeight: 1.7, paddingLeft: 2 }}>
          • {item}
        </div>
      ))}
    </div>
  )
}

function TableCard({ tableName, tableMeta }) {
  const [open, setOpen] = useState(true)
  const rowCount = tableMeta.row_count ?? 0
  const colCount = Object.keys(tableMeta.columns || {}).length

  return (
    <div style={{
      background: '#0a1020',
      border: '1px solid #1e293b',
      borderRadius: 10,
      marginBottom: 12,
      overflow: 'hidden',
    }}>
      {/* Table header */}
      <button
        onClick={() => setOpen(x => !x)}
        style={{
          width: '100%', background: 'none', border: 'none',
          padding: '12px 16px', cursor: 'pointer', textAlign: 'left',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          fontFamily: 'inherit',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ fontSize: 14 }}>📋</span>
          <span style={{ fontWeight: 700, fontSize: 13, color: '#e2e8f0' }}>{tableName}</span>
          <span style={{
            background: 'rgba(59,130,246,0.1)', color: '#60a5fa',
            border: '1px solid rgba(59,130,246,0.2)',
            borderRadius: 4, padding: '1px 7px', fontSize: 11,
          }}>
            {rowCount.toLocaleString()} rows
          </span>
          <span style={{ color: '#475569', fontSize: 11 }}>{colCount} columns</span>
        </div>
        <span style={{ color: '#475569', fontSize: 14 }}>{open ? '▲' : '▼'}</span>
      </button>

      {open && (
        <div style={{ borderTop: '1px solid #1e293b', padding: '4px 0 8px' }}>
          <ColTable columns={tableMeta.columns} />
        </div>
      )}
    </div>
  )
}

export default function CatalogSnapshot({ integrationId }) {
  const [snapshot, setSnapshot]     = useState(null)
  const [loading, setLoading]       = useState(true)
  const [snapshotting, setSnapping] = useState(false)
  const [error, setError]           = useState(null)

  const loadLatest = () => {
    setLoading(true)
    fetch(`${BASE}/catalog/${integrationId}/latest`)
      .then(r => r.json())
      .then(data => {
        setSnapshot(data.snapshot || null)
        setLoading(false)
        setError(null)
      })
      .catch(e => {
        setError(e.message)
        setLoading(false)
      })
  }

  useEffect(() => {
    if (integrationId) loadLatest()
  }, [integrationId]) // eslint-disable-line react-hooks/exhaustive-deps

  const takeSnapshot = () => {
    setSnapping(true)
    fetch(`${BASE}/catalog/${integrationId}/snapshot`, { method: 'POST' })
      .then(r => r.json())
      .then(data => {
        setSnapshot(data)
        setSnapping(false)
      })
      .catch(e => {
        setError(e.message)
        setSnapping(false)
      })
  }

  const tables = snapshot?.tables || {}
  const tableEntries = Object.entries(tables)

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
          <span style={{ fontSize: 15 }}>🗂️</span>
          <div>
            <div style={{ fontWeight: 600, fontSize: 14, color: '#e2e8f0' }}>
              Data Catalog Snapshot
            </div>
            <div style={{ fontSize: 11, color: '#475569', marginTop: 2 }}>
              Schema metadata + column statistics — no raw values stored
              {snapshot?.snapshot_at && (
                <> · last snapshot {new Date(snapshot.snapshot_at).toLocaleString()}</>
              )}
            </div>
          </div>
        </div>

        <div style={{ display: 'flex', gap: 8 }}>
          <button
            onClick={loadLatest}
            disabled={loading}
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
            onClick={takeSnapshot}
            disabled={snapshotting}
            style={{
              background: 'var(--accent-teal, #14b8a6)',
              border: 'none', borderRadius: 6, padding: '5px 12px',
              color: '#fff', cursor: snapshotting ? 'not-allowed' : 'pointer',
              fontSize: 11, fontWeight: 600,
              display: 'flex', alignItems: 'center', gap: 5,
              opacity: snapshotting ? 0.7 : 1,
              fontFamily: 'inherit',
            }}
          >
            <Camera size={11} />
            {snapshotting ? 'Taking snapshot…' : 'Take Snapshot'}
          </button>
        </div>
      </div>

      {/* Body */}
      <div style={{ padding: '20px 20px' }}>
        {loading && (
          <div style={{ color: '#475569', fontSize: 13 }}>Loading catalog…</div>
        )}
        {error && (
          <div style={{ color: '#ef4444', fontSize: 13 }}>Error: {error}</div>
        )}

        {!loading && !error && !snapshot && (
          <div style={{ textAlign: 'center', color: '#334155', fontSize: 13, padding: '24px 0' }}>
            No snapshot yet.<br />
            <span style={{ fontSize: 12, color: '#1e3a5f' }}>
              Click "Take Snapshot" to capture the current schema with statistics.
            </span>
          </div>
        )}

        {snapshot && (
          <>
            {/* Stats bar */}
            <div style={{
              display: 'flex', gap: 20, marginBottom: 16,
              padding: '10px 14px',
              background: 'rgba(15,23,42,0.5)',
              borderRadius: 8, border: '1px solid #1e293b',
            }}>
              {[
                ['Tables', snapshot.table_count ?? tableEntries.length],
                ['Columns', snapshot.column_count ?? 0],
              ].map(([label, val]) => (
                <div key={label} style={{ fontSize: 12 }}>
                  <span style={{ color: '#475569' }}>{label}: </span>
                  <span style={{ color: '#e2e8f0', fontWeight: 700 }}>{val}</span>
                </div>
              ))}
            </div>

            {/* Change banner */}
            <ChangeBanner changes={snapshot.changes_detected} />

            {/* Table cards */}
            {tableEntries.map(([tbl, meta]) => (
              <TableCard key={tbl} tableName={tbl} tableMeta={meta} />
            ))}

            {tableEntries.length === 0 && (
              <div style={{ color: '#475569', fontSize: 13 }}>
                No tables found in this snapshot.
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
