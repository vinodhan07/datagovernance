import { useEffect, useState } from 'react'
import { TableProperties, ChevronDown, ChevronRight, Loader, RefreshCw } from 'lucide-react'
import { getTables, getLatestSnapshot, takeSnapshot } from '../../api/client.js'

// ── helpers ───────────────────────────────────────────────────────────────────

function nullBadge(pct) {
  if (pct === undefined || pct === null) return null
  const color = pct === 0 ? 'var(--accent-teal)' : pct < 5 ? 'var(--warning)' : 'var(--danger)'
  return (
    <span style={{
      fontSize: 10, fontWeight: 700, padding: '2px 6px', borderRadius: 4,
      background: pct === 0 ? 'var(--accent-teal-soft)' : pct < 5 ? 'rgba(245,158,11,0.12)' : 'var(--danger-bg)',
      color, fontFamily: 'var(--font-mono)',
    }}>
      {pct}% null
    </span>
  )
}

// ── main component ────────────────────────────────────────────────────────────

export default function Catalog({ integrationId }) {
  const [tables, setTables]         = useState([])   // [{name, columns, column_count, row_count}]
  const [loading, setLoading]       = useState(false)
  const [scanning, setScanning]     = useState(false)
  const [error, setError]           = useState(null)
  const [expanded, setExpanded]     = useState(null)
  const [snapshotAt, setSnapshotAt] = useState(null) // timestamp of stored scan
  const [fromStore, setFromStore]   = useState(false) // true = loaded from catalog_scan_results

  const load = async (forceRescan = false) => {
    if (!integrationId) return
    setLoading(true)
    setError(null)

    try {
      // Try stored catalog_scan_results first (unless forcing a new scan)
      if (!forceRescan) {
        const res = await getLatestSnapshot(integrationId)
        if (res?.snapshot?.tables) {
          const snap = res.snapshot
          // Convert {tableName: {row_count, columns: {colName: {type,nullable,null_pct,unique_count}}}}
          // into the same shape the panel expects
          const parsed = Object.entries(snap.tables).map(([name, meta]) => ({
            name,
            row_count: meta.row_count ?? 0,
            column_count: Object.keys(meta.columns || {}).length,
            columns: Object.entries(meta.columns || {}).map(([col, info]) => ({
              name:         col,
              type:         info.type,
              nullable:     info.nullable,
              is_primary_key: info.is_primary_key,
              null_pct:     info.null_pct,
              unique_count: info.unique_count,
            })),
          }))
          setTables(parsed)
          setSnapshotAt(snap.snapshot_at)
          setFromStore(true)
          return
        }
      }

      // No stored results — fall back to live schema (no stats)
      const live = await getTables(integrationId)
      setTables(live)
      setSnapshotAt(null)
      setFromStore(false)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  const handleScan = async () => {
    setScanning(true)
    setError(null)
    try {
      await takeSnapshot(integrationId)   // POST /catalog/{id}/snapshot → saves to catalog_scan_results
      await load(true)                    // reload from store
    } catch (e) {
      setError(e.message)
    } finally {
      setScanning(false)
    }
  }

  useEffect(() => { load() }, [integrationId])

  const toggle = (name) => setExpanded(p => p === name ? null : name)

  return (
    <div style={panelStyle} className="fade-up">
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 }}>
        <div style={headerStyle}>
          <div style={iconBoxStyle}>
            <TableProperties size={15} color="var(--accent-teal)" strokeWidth={2.5} />
          </div>
          <div>
            <span style={headerTextStyle}>Data Catalog</span>
            {snapshotAt && (
              <div style={{ fontSize: 11, color: 'var(--text-hint)', marginTop: 2, fontWeight: 500 }}>
                Last scan: {new Date(snapshotAt).toLocaleString()}
              </div>
            )}
            {!fromStore && !loading && tables.length > 0 && (
              <div style={{ fontSize: 11, color: 'var(--warning)', marginTop: 2, fontWeight: 600 }}>
                Live schema — run a scan to save stats
              </div>
            )}
          </div>
        </div>
        <button
          onClick={handleScan}
          disabled={scanning || loading}
          style={{
            display: 'flex', alignItems: 'center', gap: 6,
            padding: '7px 14px', borderRadius: 7, fontSize: 12, fontWeight: 600,
            background: 'var(--accent-teal-soft)', color: 'var(--accent-teal)',
            border: '1px solid var(--accent-teal-border)', cursor: scanning ? 'not-allowed' : 'pointer',
            fontFamily: 'inherit', opacity: scanning ? 0.6 : 1, transition: 'all 0.15s',
          }}
        >
          <RefreshCw size={12} style={{ animation: scanning ? 'spin 1s linear infinite' : 'none' }} />
          {scanning ? 'Scanning…' : 'Scan Now'}
        </button>
      </div>

      {loading && <Spinner />}
      {error   && <ErrBox msg={error} />}

      {!loading && !error && tables.length === 0 && (
        <div style={emptyStyle}>No tables found. Run a scan or fetch data first.</div>
      )}

      {!loading && !error && tables.length > 0 && (
        <div>
          {/* Summary row */}
          <div style={{ display: 'flex', gap: 20, marginBottom: 20 }}>
            {[
              { label: 'Tables',  value: tables.length },
              { label: 'Columns', value: tables.reduce((s, t) => s + t.column_count, 0) },
              { label: 'Rows (total)', value: fromStore
                  ? tables.reduce((s, t) => s + (t.row_count || 0), 0).toLocaleString()
                  : '—' },
            ].map(({ label, value }) => (
              <div key={label} style={{
                background: 'var(--bg-base)', border: '1px solid var(--border)',
                borderRadius: 8, padding: '10px 18px', minWidth: 90,
              }}>
                <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>{value}</div>
                <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--text-hint)', textTransform: 'uppercase', letterSpacing: '0.8px', marginTop: 2 }}>{label}</div>
              </div>
            ))}
          </div>

          {/* Table Explorer Grid */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: 12, marginBottom: 20 }}>
            {tables.map(t => (
              <button
                key={t.name}
                onClick={() => toggle(t.name)}
                style={{
                  display: 'flex', flexDirection: 'column', gap: 8,
                  background: expanded === t.name ? 'var(--accent-teal-soft)' : 'var(--bg-surface)',
                  border: `1.5px solid ${expanded === t.name ? 'var(--accent-teal)' : 'var(--border)'}`,
                  borderRadius: 12, padding: '16px', cursor: 'pointer',
                  textAlign: 'left', transition: 'all 0.2s',
                  boxShadow: expanded === t.name ? '0 4px 12px rgba(20, 184, 166, 0.1)' : 'none',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', width: '100%' }}>
                  <span style={{ fontSize: 18 }}>{expanded === t.name ? '📂' : '📁'}</span>
                  {expanded === t.name ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                </div>
                <div style={{ fontWeight: 700, fontSize: 14, color: expanded === t.name ? 'var(--accent-teal)' : 'var(--text-primary)' }}>
                  {t.name}
                </div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', fontWeight: 500 }}>
                  {t.column_count} columns · {fromStore && t.row_count !== undefined ? `${t.row_count.toLocaleString()} rows` : 'Schema only'}
                </div>
              </button>
            ))}
          </div>

          {/* Expanded column view */}
          {expanded && (() => {
            const t = tables.find(x => x.name === expanded)
            if (!t) return null
            const hasStats = fromStore && t.columns.some(c => c.null_pct !== undefined)
            return (
              <div className="fade-up" style={{
                background: 'var(--bg-surface)', border: '1px solid var(--border)',
                borderRadius: 10, overflow: 'hidden', boxShadow: 'var(--shadow-md)',
              }}>
                <div style={{
                  padding: '12px 18px', borderBottom: '1px solid var(--border)',
                  fontSize: 11, fontWeight: 700, color: 'var(--text-hint)',
                  textTransform: 'uppercase', letterSpacing: '1px', background: 'var(--bg-base)',
                  display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                }}>
                  <span>Schema: {t.name}</span>
                  <span style={{ fontWeight: 500 }}>{t.columns.length} Fields</span>
                </div>
                <div style={{ overflowX: 'auto' }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                    <thead>
                      <tr style={{ borderBottom: '1px solid var(--border)' }}>
                        {['Field', 'Data Type', 'Nullable',
                          ...(hasStats ? ['Null %', 'Unique'] : [])
                        ].map(h => (
                          <th key={h} style={{
                            padding: '10px 18px', textAlign: 'left', fontSize: 11,
                            color: 'var(--text-muted)', fontWeight: 600,
                            textTransform: 'uppercase', letterSpacing: '0.8px',
                          }}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {t.columns.map((c, i) => (
                        <tr key={c.name} style={{
                          borderTop: i === 0 ? 'none' : '1px solid var(--border-subtle)',
                          transition: 'background 0.15s',
                        }}>
                          <td style={{ padding: '10px 18px', fontSize: 13, color: 'var(--text-primary)', fontWeight: 600 }}>
                            {c.name}
                            {c.is_primary_key && (
                              <span style={{ marginLeft: 6, fontSize: 9, fontWeight: 700, color: 'var(--accent-teal)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>PK</span>
                            )}
                          </td>
                          <td style={{ padding: '10px 18px', fontSize: 11, color: 'var(--accent-purple)', fontFamily: 'var(--font-mono)', fontWeight: 500 }}>{c.type}</td>
                          <td style={{ padding: '10px 18px', fontSize: 11 }}>
                            <span style={{
                              color: c.nullable ? 'var(--warning)' : 'var(--text-muted)',
                              fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.4px',
                            }}>
                              {c.nullable ? 'Yes' : 'No'}
                            </span>
                          </td>
                          {hasStats && (
                            <>
                              <td style={{ padding: '10px 18px' }}>{nullBadge(c.null_pct)}</td>
                              <td style={{ padding: '10px 18px', fontSize: 12, color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', fontWeight: 500 }}>
                                {c.unique_count?.toLocaleString() ?? '—'}
                              </td>
                            </>
                          )}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )
          })()}

          <p style={{ fontSize: 11, color: 'var(--text-hint)', marginTop: 14, fontWeight: 500, fontStyle: 'italic' }}>
            {fromStore
              ? '* Results from catalog_scan_results — metadata only, no raw row data stored.'
              : '* Live schema from MariaDB — click Scan Now to save stats to catalog_scan_results.'}
          </p>
        </div>
      )}
    </div>
  )
}

// ── styles ────────────────────────────────────────────────────────────────────

const panelStyle = {
  background: 'var(--bg-surface)', border: '1px solid var(--border)',
  borderRadius: 14, padding: '24px 28px', marginBottom: 20,
  boxShadow: 'var(--shadow-card)',
}
const iconBoxStyle = {
  width: 32, height: 32, borderRadius: 8,
  background: 'var(--accent-teal-soft)',
  display: 'flex', alignItems: 'center', justifyContent: 'center',
  flexShrink: 0,
}
const headerStyle  = { display: 'flex', alignItems: 'flex-start', gap: 12 }
const headerTextStyle = {
  fontFamily: 'var(--font-display)', fontSize: 20, fontWeight: 400,
  color: 'var(--text-primary)', letterSpacing: '-0.2px',
}
const emptyStyle   = { color: 'var(--text-muted)', fontSize: 13, padding: '12px 0' }

function Spinner() {
  return (
    <div style={{ display: 'flex', gap: 10, alignItems: 'center', color: 'var(--text-muted)', fontSize: 13, padding: '8px 0', fontWeight: 500 }}>
      <Loader size={14} className="spin" /> Loading catalog data…
    </div>
  )
}
function ErrBox({ msg }) {
  return (
    <div style={{ background: 'var(--danger-bg)', border: '1px solid var(--danger-border)', borderRadius: 8, padding: '12px 18px', color: 'var(--danger)', fontSize: 13, fontWeight: 500 }}>
      {msg}
    </div>
  )
}
