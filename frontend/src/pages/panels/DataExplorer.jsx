import { useEffect, useState } from 'react'
import { Eye, Loader } from 'lucide-react'
import { getTables, getTableData } from '../../api/client.js'

function isNull(v) { return v === null || v === undefined || v === 'None' }
function isNegative(v) { return typeof v === 'number' && v < 0 }

function CellValue({ value }) {
  if (isNull(value)) {
    return <span style={{ 
      color: 'var(--danger)', 
      fontStyle: 'italic', 
      fontSize: 10, 
      fontWeight: 600,
      background: 'var(--danger-bg)',
      padding: '1px 4px',
      borderRadius: 4
    }}>NULL</span>
  }
  if (isNegative(value)) {
    return <span style={{ color: 'var(--danger)', fontWeight: 500 }}>{String(value)}</span>
  }
  return <span>{String(value)}</span>
}

export default function DataExplorer({ integrationId }) {
  const [tables, setTables] = useState([])
  const [selectedTable, setSelectedTable] = useState(null)
  const [rows, setRows] = useState([])
  const [columns, setColumns] = useState([])
  const [loadingTables, setLoadingTables] = useState(false)
  const [loadingData, setLoadingData] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!integrationId) return
    setLoadingTables(true)
    getTables(integrationId)
      .then(t => { setTables(t); if (t.length > 0) setSelectedTable(t[0].name) })
      .catch(e => setError(e.message))
      .finally(() => setLoadingTables(false))
  }, [integrationId])

  useEffect(() => {
    if (!integrationId || !selectedTable) return
    setLoadingData(true); setError(null)
    getTableData(integrationId, selectedTable, 100)
      .then(data => {
        setRows(data.rows || [])
        setColumns(data.rows?.length > 0 ? Object.keys(data.rows[0]) : [])
      })
      .catch(e => setError(e.message))
      .finally(() => setLoadingData(false))
  }, [integrationId, selectedTable])

  return (
    <div style={panelStyle} className="fade-up">
      <div style={headerStyle}>
        <div style={iconBoxStyle}>
          <Eye size={15} color="var(--accent-teal)" strokeWidth={2.5} />
        </div>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
          <span style={headerTextStyle}>Data Explorer</span>
          <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-hint)', textTransform: 'uppercase', letterSpacing: '0.8px' }}>Read-Only Preview</span>
        </div>
      </div>
      
      <p style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 20, marginTop: -8 }}>
        Visualizing first 100 entries. Data processed in-memory for security.
      </p>

      {error && <ErrBox msg={error} />}

      <div style={{ display: 'flex', gap: 20, minHeight: 400 }}>
        {/* Table list side selector */}
        <div style={{ width: 180, flexShrink: 0, borderRight: '1px solid var(--border)', paddingRight: 10 }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-hint)', textTransform: 'uppercase', letterSpacing: '1px', marginBottom: 12, paddingLeft: 8 }}>
            Available Tables
          </div>
          {loadingTables
            ? <div style={{ color: 'var(--text-muted)', fontSize: 12, display: 'flex', gap: 8, alignItems: 'center', padding: '8px' }}><Loader size={12} className="spin" /> Syncing…</div>
            : tables.map(t => (
              <button
                key={t.name}
                onClick={() => setSelectedTable(t.name)}
                style={{
                  width: '100%', textAlign: 'left', padding: '8px 12px',
                  background: selectedTable === t.name ? 'var(--bg-panel)' : 'transparent',
                  color: selectedTable === t.name ? 'var(--text-primary)' : 'var(--text-muted)',
                  border: 'none', borderRadius: 6, cursor: 'pointer',
                  fontSize: 12, fontFamily: 'inherit', marginBottom: 2,
                  fontWeight: selectedTable === t.name ? 600 : 500,
                  transition: 'all 0.15s',
                }}
                onMouseEnter={e => { if (selectedTable !== t.name) e.currentTarget.style.background = 'var(--bg-base)' }}
                onMouseLeave={e => { if (selectedTable !== t.name) e.currentTarget.style.background = 'transparent' }}
              >
                {t.name}
              </button>
            ))
          }
        </div>

        {/* Data scrollable grid */}
        <div style={{ flex: 1, overflow: 'auto', background: 'var(--bg-base)', borderRadius: 8, border: '1px solid var(--border-subtle)' }}>
          {loadingData
            ? <div style={{ color: 'var(--text-muted)', fontSize: 13, display: 'flex', gap: 10, alignItems: 'center', height: '100%', justifyContent: 'center' }}><Loader size={16} className="spin" /> Interrogating data source…</div>
            : rows.length === 0
              ? <div style={{ color: 'var(--text-muted)', fontSize: 13, display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%' }}>No records found in {selectedTable}.</div>
              : (
                <table style={{ borderCollapse: 'collapse', fontSize: 12, minWidth: '100%', fontFamily: 'var(--font-body)' }}>
                  <thead style={{ position: 'sticky', top: 0, zIndex: 1, background: 'var(--bg-panel)' }}>
                    <tr>
                      {columns.map(col => (
                        <th key={col} style={{ 
                          padding: '10px 16px', textAlign: 'left', fontSize: 11, 
                          color: 'var(--text-primary)', fontWeight: 700, textTransform: 'uppercase', 
                          letterSpacing: '0.6px', borderBottom: '1px solid var(--border)',
                          whiteSpace: 'nowrap', fontFamily: 'var(--font-mono)'
                        }}>
                          {col}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((row, i) => (
                      <tr key={i} style={{ 
                        background: i % 2 === 0 ? 'var(--bg-surface)' : 'var(--bg-base)', 
                        borderBottom: '1px solid var(--border-subtle)',
                        transition: 'background 0.1s'
                      }}>
                        {columns.map(col => (
                          <td key={col} style={{ padding: '8px 16px', color: 'var(--text-secondary)', whiteSpace: 'nowrap', fontWeight: 500 }}>
                            <CellValue value={row[col]} />
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              )
          }
        </div>
      </div>
    </div>
  )
}

const panelStyle = { 
  background: 'var(--bg-surface)', 
  border: '1px solid var(--border)', 
  borderRadius: 14, 
  padding: '24px 28px', 
  marginBottom: 20,
  boxShadow: 'var(--shadow-card)',
}

const iconBoxStyle = {
  width: 32, height: 32, borderRadius: 8,
  background: 'var(--accent-teal-soft)',
  display: 'flex', alignItems: 'center', justifyContent: 'center',
}

const headerStyle = { display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }
const headerTextStyle = { 
  fontFamily: 'var(--font-display)', 
  fontSize: 20, 
  fontWeight: 400, 
  color: 'var(--text-primary)',
  letterSpacing: '-0.2px',
}

function ErrBox({ msg }) {
  return <div style={{ background: 'var(--danger-bg)', border: '1px solid var(--danger-border)', borderRadius: 8, padding: '12px 18px', color: 'var(--danger)', fontSize: 13, fontWeight: 500, marginBottom: 16 }}>{msg}</div>
}
