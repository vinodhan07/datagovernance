import { useState, useEffect, useRef } from 'react'
import { Loader, Play, RotateCcw, GitBranch, BookOpen, ShieldCheck, CheckCircle, XCircle, AlertCircle, Database } from 'lucide-react'
import LineageGraph from '../components/LineageGraph.jsx'
import AuditTimeline from '../components/AuditTimeline.jsx'
import PipelineTerminal from '../components/PipelineTerminal.jsx'
import {
  getIntegrations, getCapabilities, getLatestPipelineRun,
  getCatalogTables, getQualityScore, getQualityScans, getQualityScanDetail, qualityScanUrl
} from '../api/client.js'

const TABS = [
  { id: 'lineage',  label: 'Lineage',  icon: GitBranch },
  { id: 'catalog',  label: 'Catalog',  icon: BookOpen },
  { id: 'quality',  label: 'Quality',  icon: ShieldCheck },
]

// ── Module-level run cache — survives page navigation ─────────────────────────
// Keyed by integration_id. Stores { done, caps, catalogTables, qualityScore, qualityFindings }
const _cache = {}

// ── Feature status badge ──────────────────────────────────────────────────────
function FeatureBadge({ available, reason }) {
  const color = available === true ? '#10b981' : available === false ? '#ef4444' : '#f59e0b'
  const Icon  = available === true ? CheckCircle : available === false ? XCircle : AlertCircle
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 11, color, fontWeight: 600 }}>
      <Icon size={12} /> {reason || (available ? 'Available' : 'Not available')}
    </span>
  )
}

// ── Catalog tab ───────────────────────────────────────────────────────────────
function CatalogTab({ tables, loading }) {
  if (loading) return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--text-hint)', fontSize: 13, padding: 24 }}>
      <Loader size={14} className="spin" /> Loading catalog tables…
    </div>
  )
  if (!tables?.length) return (
    <div style={{ textAlign: 'center', padding: 40 }}>
      <BookOpen size={32} color="var(--text-hint)" style={{ marginBottom: 10 }} />
      <div style={{ fontSize: 13, color: 'var(--text-muted)', fontWeight: 500 }}>No tables in catalog yet</div>
      <div style={{ fontSize: 12, color: 'var(--text-hint)', marginTop: 6 }}>Run the pipeline to push table metadata to OpenMetadata.</div>
    </div>
  )
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
      <div style={{ background: 'rgba(16,185,129,0.06)', border: '1px solid rgba(16,185,129,0.2)', borderRadius: 8, padding: '12px 16px', fontSize: 12, color: '#10b981', display: 'flex', alignItems: 'center', gap: 8 }}>
        <CheckCircle size={14} /> {tables.length} table(s) synced with OpenMetadata
      </div>

      {tables.map((t, i) => (
        <div key={i} style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)', borderRadius: 10, overflow: 'hidden', boxShadow: 'var(--shadow-card)' }}>
          <div style={{ padding: '14px 20px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', background: 'var(--bg-base)' }}>
            <div>
              <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: 6 }}>
                <Database size={15} color="var(--accent-teal)" />
                {t.name}
              </div>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4, display: 'flex', alignItems: 'center', gap: 4 }}>
                <BookOpen size={11} /> {t.fqn || t.name}
              </div>
            </div>
            <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-muted)', background: 'var(--bg-surface)', padding: '4px 10px', borderRadius: 20, border: '1px solid var(--border)' }}>
              {t.columns?.length || 0} columns
            </div>
          </div>
          
          {t.columns?.length > 0 && (
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid var(--border)', background: 'var(--bg-base)' }}>
                    <th style={{ padding: '10px 20px', fontSize: 11, fontWeight: 600, color: 'var(--text-hint)', textTransform: 'uppercase' }}>Column Name</th>
                    <th style={{ padding: '10px 20px', fontSize: 11, fontWeight: 600, color: 'var(--text-hint)', textTransform: 'uppercase' }}>Data Type</th>
                  </tr>
                </thead>
                <tbody>
                  {t.columns.map((col, cIdx) => (
                    <tr key={cIdx} style={{ borderBottom: cIdx < t.columns.length - 1 ? '1px solid var(--border)' : 'none' }}>
                      <td style={{ padding: '10px 20px', fontSize: 13, fontWeight: 500, color: 'var(--text-primary)' }}>{col.name}</td>
                      <td style={{ padding: '10px 20px' }}>
                        <span style={{ fontSize: 11, fontFamily: 'monospace', background: 'rgba(20,184,166,0.1)', color: 'var(--accent-teal)', padding: '2px 6px', borderRadius: 4 }}>
                          {col.data_type || col.dataType || 'VARCHAR'}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

// ── Quality tab ───────────────────────────────────────────────────────────────
function QualityTab({ score, findings, loading, onRunScan }) {
  if (loading) return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--text-hint)', fontSize: 13, padding: 24 }}>
      <Loader size={14} className="spin" /> Loading quality data…
    </div>
  )

  const color = score === null ? '#94a3b8' : score >= 80 ? '#10b981' : score >= 60 ? '#f59e0b' : '#ef4444'

  const findingsByTable = findings.reduce((acc, f) => {
    if (!acc[f.table_name]) acc[f.table_name] = []
    acc[f.table_name].push(f)
    return acc
  }, {})

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 20, marginBottom: 24, flexWrap: 'wrap' }}>
        <div style={{
          display: 'flex', alignItems: 'center', gap: 14,
          background: 'var(--bg-surface)', border: '1px solid var(--border)',
          borderRadius: 12, padding: '16px 22px', boxShadow: 'var(--shadow-card)',
        }}>
          <div style={{
            width: 60, height: 60, borderRadius: '50%', flexShrink: 0,
            background: `conic-gradient(${color} ${(score ?? 0) * 3.6}deg, var(--bg-base) 0deg)`,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
            <div style={{ width: 44, height: 44, borderRadius: '50%', background: 'var(--bg-surface)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 12, fontWeight: 700, color }}>
              {score !== null ? `${Math.round(score)}%` : '—'}
            </div>
          </div>
          <div>
            <div style={{ fontSize: 16, fontWeight: 700, color }}>
              {score !== null ? `${score.toFixed(1)}% Quality Score` : 'No scans yet'}
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 3 }}>
              {findings.length > 0 ? `${findings.filter(f => f.status === 'pass').length}/${findings.length} checks passed` : 'Run a scan from the Quality page'}
            </div>
          </div>
        </div>
        <div style={{ marginLeft: 'auto' }}>
          <button onClick={onRunScan} disabled={loading} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '9px 16px', borderRadius: 8, fontSize: 13, fontWeight: 600, background: loading ? 'var(--bg-surface)' : 'var(--accent-teal)', color: loading ? 'var(--text-hint)' : '#fff', border: loading ? '1px solid var(--border)' : 'none', cursor: loading ? 'not-allowed' : 'pointer' }}>
            {loading ? <Loader size={14} className="spin" /> : <Play size={14} />} 
            {findings.length > 0 ? 'Run Quality Scan' : 'Auto-Generate Rules & Scan'}
          </button>
        </div>
      </div>

      {findings.length > 0 ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
          {Object.entries(findingsByTable).map(([tableName, tableFindings]) => (
            <div key={tableName} style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)', borderRadius: 10, overflow: 'hidden', boxShadow: 'var(--shadow-card)' }}>
              <div style={{ padding: '14px 20px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', gap: 8, background: 'var(--bg-base)' }}>
                <Database size={15} color="var(--accent-teal)" />
                <span style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-primary)' }}>{tableName}</span>
                <span style={{ fontSize: 11, color: 'var(--text-muted)', marginLeft: 'auto' }}>
                  {tableFindings.filter(f => f.status === 'pass').length} / {tableFindings.length} checks passed
                </span>
              </div>
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
                  <thead>
                    <tr style={{ borderBottom: '1px solid var(--border)', background: 'var(--bg-base)' }}>
                      <th style={{ padding: '10px 20px', fontSize: 11, fontWeight: 600, color: 'var(--text-hint)', textTransform: 'uppercase' }}>Column / Scope</th>
                      <th style={{ padding: '10px 20px', fontSize: 11, fontWeight: 600, color: 'var(--text-hint)', textTransform: 'uppercase' }}>Check Type</th>
                      <th style={{ padding: '10px 20px', fontSize: 11, fontWeight: 600, color: 'var(--text-hint)', textTransform: 'uppercase' }}>Value</th>
                      <th style={{ padding: '10px 20px', fontSize: 11, fontWeight: 600, color: 'var(--text-hint)', textTransform: 'uppercase' }}>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {tableFindings.map((f, i) => {
                      const fc    = f.status === 'pass' ? '#10b981' : f.status === 'fail' ? '#ef4444' : '#f59e0b'
                      const FIcon = f.status === 'pass' ? CheckCircle : f.status === 'fail' ? XCircle : AlertCircle
                      return (
                        <tr key={i} style={{ borderBottom: i < tableFindings.length - 1 ? '1px solid var(--border)' : 'none' }}>
                          <td style={{ padding: '10px 20px', fontSize: 13, fontWeight: 500, color: 'var(--text-primary)' }}>
                            {f.column_name || <span style={{ color: 'var(--text-muted)', fontStyle: 'italic' }}>Table-level check</span>}
                          </td>
                          <td style={{ padding: '10px 20px' }}>
                            <span style={{ fontSize: 11, fontFamily: 'monospace', background: 'rgba(20,184,166,0.1)', color: 'var(--accent-teal)', padding: '2px 6px', borderRadius: 4 }}>
                              {f.check_type}
                            </span>
                          </td>
                          <td style={{ padding: '10px 20px', fontSize: 13, fontWeight: 700, color: fc }}>{f.value}</td>
                          <td style={{ padding: '10px 20px' }}>
                            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 10, fontWeight: 700, background: `${fc}18`, color: fc, borderRadius: 20, padding: '2px 8px' }}>
                              <FIcon size={10} /> {f.status?.toUpperCase()}
                            </span>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div style={{ padding: '40px 24px', textAlign: 'center', background: 'var(--bg-base)', borderRadius: 8, border: '1px solid var(--border)' }}>
          <ShieldCheck size={32} color="var(--text-hint)" style={{ marginBottom: 12 }} />
          <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 6 }}>No Quality Checks Found</div>
          <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
            No quality rules defined or scan hasn't been run yet. Click the button above to auto-generate default rules and run a scan.
          </div>
        </div>
      )}
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────
export default function DataGovernance({ onNavigate }) {
  const [integrations,   setIntegrations]   = useState([])
  const [loadingList,    setLoadingList]     = useState(true)
  const [selected,       setSelected]       = useState(null)
  const [activeTab,      setActiveTab]      = useState('lineage')

  // Per-run state — initialised from cache if available
  const [capabilities,   setCapabilities]   = useState(null)
  const [capsLoading,    setCapsLoading]    = useState(false)
  const [pipelineDone,   setPipelineDone]   = useState(false)
  const [pipelineFailed, setPipelineFailed] = useState(false)
  const [terminalKey,    setTerminalKey]    = useState(0)
  const [terminalOpen,   setTerminalOpen]   = useState(false)
  const [fetching,       setFetching]       = useState(false)

  // Cached data loaded after pipeline completes
  const [catalogTables,  setCatalogTables]  = useState([])
  const [catalogLoading, setCatalogLoading] = useState(false)
  const [qualityScore,   setQualityScore]   = useState(null)
  const [qualityFindings,setQualityFindings]= useState([])
  const [qualityLoading, setQualityLoading] = useState(false)

  const selectedId = selected?.id

  // ── Load integrations once ──────────────────────────────────────────────────
  useEffect(() => {
    getIntegrations()
      .then(list => {
        setIntegrations(list)
        if (list.length > 0) setSelected(list[0])
      })
      .catch(() => {})
      .finally(() => setLoadingList(false))
  }, [])

  // ── When integration changes: restore from cache or fetch caps + detect prior run ──
  useEffect(() => {
    if (!selectedId) return

    const cached = _cache[selectedId]
    if (cached) {
      setCapabilities(cached.caps)
      setPipelineDone(cached.done)
      setPipelineFailed(false)
      setCatalogTables(cached.catalogTables || [])
      setQualityScore(cached.qualityScore ?? null)
      setQualityFindings(cached.qualityFindings || [])
      return
    }

    // Reset state for new selection
    setCapabilities(null)
    setPipelineDone(false)
    setPipelineFailed(false)
    setCatalogTables([])
    setQualityScore(null)
    setQualityFindings([])

    const init = async () => {
      // Load capabilities
      setCapsLoading(true)
      let caps = null
      try {
        caps = await getCapabilities(selectedId)
        setCapabilities(caps)
      } catch {}
      setCapsLoading(false)

      // Auto-detect prior completed run — show results without needing a new pipeline run
      try {
        const latest = await getLatestPipelineRun(selectedId)
        if (latest?.status === 'completed' || latest?.status === 'running') {
          setPipelineDone(true)
          await _loadResultData(selectedId, caps)
        }
      } catch {}
    }

    init()
  }, [selectedId])

  // ── Load post-pipeline data and persist in cache ────────────────────────────
  const _loadResultData = async (integrationId, caps) => {
    // Catalog
    setCatalogLoading(true)
    const tables = await getCatalogTables().catch(() => [])
    const tableList = Array.isArray(tables) ? tables : []
    setCatalogTables(tableList)
    setCatalogLoading(false)

    // Quality
    setQualityLoading(true)
    let qScore    = null
    let qFindings = []
    try {
      const [scoreData, scans] = await Promise.all([
        getQualityScore(integrationId).catch(() => null),
        getQualityScans(integrationId).catch(() => []),
      ])
      qScore = scoreData?.score ?? null
      const latest = Array.isArray(scans) ? scans[0] : null
      if (latest?.id) {
        const detail = await getQualityScanDetail(latest.id).catch(() => null)
        qFindings = detail?.findings || []
      }
    } catch {}
    setQualityScore(qScore)
    setQualityFindings(qFindings)
    setQualityLoading(false)

    // Write to cache
    _cache[integrationId] = {
      done: true,
      caps,
      catalogTables: tableList,
      qualityScore:  qScore,
      qualityFindings: qFindings,
    }
  }

  const handleFetch = () => {
    if (!selected) return
    // Clear cache so next run refreshes
    delete _cache[selected.id]
    setPipelineDone(false)
    setPipelineFailed(false)
    setCatalogTables([])
    setQualityScore(null)
    setQualityFindings([])
    setTerminalKey(k => k + 1)
    setTerminalOpen(true)
    setFetching(true)
  }

  const handleComplete = async (lastEntry) => {
    setFetching(false)
    setTerminalOpen(false)
    if (lastEntry?.level === 'ERROR') {
      setPipelineFailed(true)
      return
    }
    // Re-fetch capabilities now that pipeline has run
    let newCaps = capabilities
    try {
      newCaps = await getCapabilities(selected.id)
      setCapabilities(newCaps)
    } catch {}

    setPipelineDone(true)
    await _loadResultData(selected.id, newCaps)
  }

  const handleRunQualityScan = async () => {
    if (!selectedId) return
    setQualityLoading(true)
    try {
      await fetch(qualityScanUrl(selectedId))
    } catch (e) {
      console.error('Scan failed', e)
    }
    await _loadResultData(selectedId, capabilities)
  }

  const handleSelectIntegration = (ig) => {
    if (selected?.id === ig.id) return
    setSelected(ig)
    setTerminalOpen(false)
    setFetching(false)
    // State for the new integration is restored by the useEffect above
  }

  const currentCap = capabilities?.[activeTab]

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>

      {/* ── Header toolbar ── */}
      <div style={{
        background: 'var(--bg-surface)', borderBottom: '1px solid var(--border)',
        padding: '14px 28px', flexShrink: 0,
        display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap',
      }}>
        <div>
          <div style={{ fontFamily: 'var(--font-display)', fontSize: 20, fontWeight: 400, color: 'var(--text-primary)', letterSpacing: '-0.2px' }}>
            Data Governance
          </div>
          <div style={{ fontSize: 11, color: 'var(--text-hint)', marginTop: 2 }}>Lineage · Catalog · Quality — unified view per connector</div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          {/* Integration selector */}
          {loadingList ? (
            <div style={{ fontSize: 12, color: 'var(--text-hint)', display: 'flex', alignItems: 'center', gap: 6 }}>
              <Loader size={12} className="spin" /> Loading…
            </div>
          ) : (
            <select
              value={selected?.id || ''}
              onChange={e => {
                const ig = integrations.find(i => i.id === e.target.value)
                if (ig) handleSelectIntegration(ig)
              }}
              style={{
                padding: '8px 12px', borderRadius: 8, fontSize: 12, fontFamily: 'inherit',
                background: 'var(--bg-base)', color: 'var(--text-primary)',
                border: '1px solid var(--border)', cursor: 'pointer', outline: 'none',
              }}
            >
              {integrations.map(ig => (
                <option key={ig.id} value={ig.id}>{ig.name} ({ig.provider_name})</option>
              ))}
              {integrations.length === 0 && <option disabled>No connectors — add one in Connectors</option>}
            </select>
          )}

          {/* Fetch button */}
          {selected?.status === 'active' && (
            <button
              onClick={fetching ? undefined : handleFetch}
              disabled={fetching}
              style={{
                display: 'flex', alignItems: 'center', gap: 7,
                padding: '9px 18px', borderRadius: 8, fontSize: 12, fontWeight: 700,
                fontFamily: 'inherit',
                background: fetching ? 'var(--bg-panel)' : 'var(--accent-teal)',
                color: fetching ? 'var(--text-muted)' : '#fff',
                border: '1px solid transparent', cursor: fetching ? 'not-allowed' : 'pointer',
                transition: 'all 0.18s',
              }}
            >
              {fetching
                ? <><Loader size={13} className="spin" /> Running…</>
                : pipelineDone
                  ? <><RotateCcw size={13} /> Re-fetch Data</>
                  : <><Play size={13} /> Fetch & Analyse</>
              }
            </button>
          )}
        </div>
      </div>

      {/* ── Tab bar ── */}
      <div style={{
        background: 'var(--bg-surface)', borderBottom: '1px solid var(--border)',
        padding: '0 28px', display: 'flex', gap: 0, flexShrink: 0,
      }}>
        {TABS.map(({ id, label, icon: Icon }) => {
          const cap      = capabilities?.[id]
          const isActive = activeTab === id
          return (
            <button key={id} onClick={() => setActiveTab(id)}
              style={{
                display: 'flex', alignItems: 'center', gap: 7,
                padding: '12px 16px', fontSize: 13, fontWeight: isActive ? 700 : 500,
                color: isActive ? 'var(--accent-teal)' : 'var(--text-muted)',
                background: 'none', border: 'none',
                borderBottom: isActive ? '2px solid var(--accent-teal)' : '2px solid transparent',
                cursor: 'pointer', fontFamily: 'inherit', transition: 'all 0.18s', marginBottom: -1,
              }}>
              <Icon size={14} />
              {label}
              {capsLoading && <Loader size={10} className="spin" color="var(--text-hint)" />}
              {!capsLoading && cap && (
                <span style={{ fontSize: 10, fontWeight: 700, borderRadius: 20, padding: '1px 7px',
                  background: cap.available ? '#10b98118' : '#ef444418',
                  color: cap.available ? '#10b981' : '#ef4444',
                }}>
                  {cap.available ? '✓' : '✗'}
                </span>
              )}
            </button>
          )
        })}
      </div>

      {/* ── Scrollable content ── */}
      <main style={{ flex: 1, overflowY: 'auto', padding: '28px 32px' }}>

        {!selected ? (
          <div style={{ textAlign: 'center', color: 'var(--text-hint)', fontSize: 13, padding: '60px 0' }}>
            No connectors found — go to <strong>Connectors</strong> to add one.
          </div>
        ) : (
          <>
            {/* ── Pipeline terminal ── */}
            {terminalOpen && (
              <div style={{ marginBottom: 28 }}>
                <PipelineTerminal
                  key={terminalKey}
                  integrationId={selected.id}
                  isOpen={true}
                  onClose={() => { setTerminalOpen(false); setFetching(false) }}
                  onComplete={handleComplete}
                />
              </div>
            )}

            {/* ── Idle prompt ── */}
            {!terminalOpen && !pipelineDone && !pipelineFailed && selected.status === 'active' && (
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '60px 0', gap: 14 }}>
                <div style={{ width: 64, height: 64, borderRadius: '50%', background: 'var(--accent-teal-soft)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                  {activeTab === 'lineage' ? <GitBranch size={28} color="var(--accent-teal)" /> :
                   activeTab === 'catalog' ? <BookOpen   size={28} color="var(--accent-teal)" /> :
                                             <ShieldCheck size={28} color="var(--accent-teal)" />}
                </div>
                <div style={{ textAlign: 'center' }}>
                  <div style={{ fontSize: 15, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 6 }}>
                    Ready to analyse <strong>{selected.name}</strong>
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 20 }}>
                    Click <strong>Fetch & Analyse</strong> to run the pipeline and populate Lineage, Catalog, and Quality.
                  </div>
                  {currentCap && <div style={{ marginBottom: 16 }}><FeatureBadge available={currentCap.available} reason={currentCap.reason} /></div>}
                  <button onClick={handleFetch}
                    style={{ display: 'inline-flex', alignItems: 'center', gap: 8, padding: '10px 22px', borderRadius: 8, fontSize: 13, fontWeight: 700, fontFamily: 'inherit', background: 'var(--accent-teal)', color: '#fff', border: 'none', cursor: 'pointer' }}>
                    <Play size={14} /> Fetch & Analyse
                  </button>
                </div>
              </div>
            )}

            {/* ── Pipeline failed ── */}
            {pipelineFailed && !terminalOpen && (
              <div style={{ background: 'rgba(239,68,68,0.06)', border: '1px solid rgba(239,68,68,0.2)', borderRadius: 10, padding: '20px 24px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 24 }}>
                <div>
                  <div style={{ fontWeight: 600, fontSize: 14, color: '#ef4444', marginBottom: 4 }}>Pipeline failed</div>
                  <div style={{ fontSize: 12, color: '#94a3b8' }}>Check connection settings and try again.</div>
                </div>
                <button onClick={handleFetch}
                  style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '9px 18px', borderRadius: 8, fontSize: 12, fontWeight: 600, fontFamily: 'inherit', background: 'var(--accent-teal)', color: '#fff', border: 'none', cursor: 'pointer' }}>
                  <RotateCcw size={13} /> Retry
                </button>
              </div>
            )}

            {/* ── Tab content — always rendered, shown/hidden via CSS to avoid remount ── */}
            {pipelineDone && (
              <div>
                {/* Capability status for current tab */}
                {currentCap && !currentCap.available && (
                  <div style={{ background: 'rgba(239,68,68,0.06)', border: '1px solid rgba(239,68,68,0.2)', borderRadius: 8, padding: '12px 16px', fontSize: 12, color: '#ef4444', marginBottom: 20, display: 'flex', alignItems: 'center', gap: 8 }}>
                    <XCircle size={14} /> {currentCap.reason}
                  </div>
                )}
                {currentCap?.available && (
                  <div style={{ background: 'rgba(16,185,129,0.06)', border: '1px solid rgba(16,185,129,0.2)', borderRadius: 8, padding: '12px 16px', fontSize: 12, color: '#10b981', marginBottom: 20, display: 'flex', alignItems: 'center', gap: 8 }}>
                    <CheckCircle size={14} /> {currentCap.reason}
                  </div>
                )}

                {/* Each tab is always mounted but shown/hidden — prevents remount & data loss */}
                <div style={{ display: activeTab === 'lineage' ? 'block' : 'none' }}>
                  <LineageGraph integrationId={selected.id} />
                </div>
                <div style={{ display: activeTab === 'catalog' ? 'block' : 'none' }}>
                  <CatalogTab
                    tables={catalogTables}
                    loading={catalogLoading}
                  />
                </div>
                <div style={{ display: activeTab === 'quality' ? 'block' : 'none' }}>
                  <QualityTab
                    score={qualityScore}
                    findings={qualityFindings}
                    loading={qualityLoading}
                    onRunScan={handleRunQualityScan}
                  />
                </div>

                {/* Audit always visible */}
                <div style={{ marginTop: 40 }}>
                  <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-hint)', textTransform: 'uppercase', letterSpacing: '1px', marginBottom: 16 }}>Governance Audit History</div>
                  <AuditTimeline integrationId={selected.id} />
                </div>
              </div>
            )}
          </>
        )}
      </main>
    </div>
  )
}
