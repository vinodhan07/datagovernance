import { useEffect, useState } from 'react'
import { ScanLine, Plus, Loader } from 'lucide-react'
import Badge from '../../components/Badge.jsx'
import Modal from '../../components/Modal.jsx'
import ScanResultCard from '../../components/ScanResultCard.jsx'
import ScoreRing from '../../components/ScoreRing.jsx'
import { getRules, createRule, getScanHistory } from '../../api/client.js'

const RULE_COLORS = {
  null_check:      '#14b8a6',
  range_check:     '#f59e0b',
  format_check:    '#8b5cf6',
  duplicate_check: '#10b981',
}

const iStyle = { 
  flex: 1, 
  background: 'var(--bg-base)', 
  border: '1px solid var(--border)', 
  borderRadius: 8, 
  padding: '10px 12px', 
  color: 'var(--text-primary)', 
  fontSize: 14, 
  fontFamily: 'inherit', 
  outline: 'none', 
  width: '100%',
  transition: 'border-color 0.15s ease'
}

const lStyle = { display: 'flex', flexDirection: 'column', gap: 6, fontSize: 13, fontWeight: 600, color: 'var(--text-secondary)', marginBottom: 16 }
const btnPrimary = { background: 'var(--accent-teal)', color: 'var(--text-inverse)', border: 'none', borderRadius: 8, padding: '10px 20px', fontSize: 14, fontWeight: 700, cursor: 'pointer', fontFamily: 'inherit', transition: 'background 0.2s', boxShadow: '0 2px 8px rgba(20, 184, 166, 0.2)' }
const btnGhost = { background: 'transparent', color: 'var(--text-muted)', border: '1px solid var(--border)', borderRadius: 8, padding: '10px 20px', fontSize: 13, fontWeight: 600, cursor: 'pointer', fontFamily: 'inherit', transition: 'all 0.2s' }

function AddRuleModal({ onClose, onSaved }) {
  const [form, setForm] = useState({ name: '', rule_type: 'null_check', table_name: '', column_name: '', severity: 'warning' })
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)

  const save = async () => {
    setSaving(true); setError(null)
    try { await createRule(form); onSaved(); onClose() }
    catch (e) { setError(e.message) }
    finally { setSaving(false) }
  }

  return (
    <Modal title="Configure Quality Rule" onClose={onClose} width={480}>
      {error && <div style={{ background: 'var(--danger-bg)', color: 'var(--danger)', padding: '10px 14px', borderRadius: 8, border: '1px solid var(--danger-border)', fontSize: 13, marginBottom: 16 }}>{error}</div>}
      
      <label style={lStyle}>Rule Friendly Name
        <input value={form.name} onChange={e => setForm(p => ({ ...p, name: e.target.value }))} style={iStyle} placeholder="e.g. Email Integrity Check" />
      </label>
      
      <div style={{ display: 'flex', gap: 16 }}>
        <label style={lStyle}>Type
          <select value={form.rule_type} onChange={e => setForm(p => ({ ...p, rule_type: e.target.value }))} style={iStyle}>
            <option value="null_check">Null Check</option>
            <option value="range_check">Range Check</option>
            <option value="format_check">Format Check</option>
            <option value="duplicate_check">Duplicate Check</option>
          </select>
        </label>
        <label style={lStyle}>Severity
          <select value={form.severity} onChange={e => setForm(p => ({ ...p, severity: e.target.value }))} style={iStyle}>
            <option value="critical">Critical</option>
            <option value="warning">Warning</option>
            <option value="info">Info</option>
          </select>
        </label>
      </div>

      <div style={{ display: 'flex', gap: 16 }}>
        <label style={lStyle}>Table
          <input value={form.table_name} onChange={e => setForm(p => ({ ...p, table_name: e.target.value }))} style={iStyle} placeholder="e.g. users" />
        </label>
        <label style={lStyle}>Column
          <input value={form.column_name} onChange={e => setForm(p => ({ ...p, column_name: e.target.value }))} style={iStyle} placeholder="e.g. email" />
        </label>
      </div>

      <div style={{ display: 'flex', gap: 12, justifyContent: 'flex-end', marginTop: 12 }}>
        <button onClick={onClose} style={btnGhost} onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-base)'} onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>Cancel</button>
        <button onClick={save} disabled={saving} style={btnPrimary} onMouseEnter={e => e.currentTarget.style.background = 'var(--accent-teal-hover)'} onMouseLeave={e => e.currentTarget.style.background = 'var(--accent-teal)'}>{saving ? 'Provisioning…' : 'Save Rule'}</button>
      </div>
    </Modal>
  )
}

export default function DataQuality({ integrationId, scanTrigger }) {
  const [rules, setRules]       = useState([])
  const [results, setResults]   = useState([])
  const [loadingR, setLoadingR] = useState(false)
  const [loadingS, setLoadingS] = useState(false)
  const [showAdd, setShowAdd]   = useState(false)
  const [error, setError]       = useState(null)

  const loadRules = () => {
    setLoadingR(true)
    getRules().then(setRules).catch(e => setError(e.message)).finally(() => setLoadingR(false))
  }

  const loadHistory = () => {
    if (!integrationId) return
    setLoadingS(true)
    getScanHistory(integrationId)
      .then(setResults)
      .catch(e => setError(e.message))
      .finally(() => setLoadingS(false))
  }

  useEffect(loadRules, [])
  useEffect(loadHistory, [integrationId, scanTrigger])

  const latestBatch = results[0]?.scan_batch_id
  const latestResults = latestBatch ? results.filter(r => r.scan_batch_id === latestBatch) : []
  const overallScore = latestResults.length
    ? Math.round(latestResults.reduce((s, r) => s + r.score, 0) / latestResults.length)
    : null

  return (
    <div style={panelStyle} className="fade-up">
      <div style={headerStyle}>
        <div style={iconBoxStyle}>
          <ScanLine size={15} color="var(--accent-teal)" strokeWidth={2.5} />
        </div>
        <span style={headerTextStyle}>Data Quality</span>
      </div>

      {error && <ErrBox msg={error} />}

      <div style={{ display: 'flex', gap: 32 }}>
        {/* ── LEFT: Rules ── */}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 }}>
            <span style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-hint)', textTransform: 'uppercase', letterSpacing: '1px' }}>Governance Rules</span>
            <button 
                onClick={() => setShowAdd(true)} 
                style={{ 
                    ...btnGhost, 
                    fontSize: 11, 
                    padding: '6px 12px', 
                    display: 'flex', 
                    alignItems: 'center', 
                    gap: 6,
                    borderColor: 'var(--accent-teal-border)',
                    color: 'var(--accent-teal)'
                }}
                onMouseEnter={e => e.currentTarget.style.background = 'var(--accent-teal-soft)'}
                onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
            >
              <Plus size={12} strokeWidth={3} /> Define Rule
            </button>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            {loadingR
                ? <div style={{ color: 'var(--text-hint)', fontSize: 13, display: 'flex', gap: 8, padding: '12px' }}><Loader size={14} className="spin" /> Syncing rules…</div>
                : rules.length === 0
                ? <div style={{ color: 'var(--text-muted)', fontSize: 13, padding: '24px 0', textAlign: 'center', border: '1px dashed var(--border)', borderRadius: 10 }}>No rules defined for this environment.</div>
                : rules.map(r => (
                    <div key={r.id} style={{ 
                        display: 'flex', 
                        alignItems: 'center', 
                        gap: 14, 
                        padding: '12px 14px', 
                        borderRadius: 8,
                        transition: 'background 0.2s' 
                    }}
                    onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-panel)'}
                    onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                    >
                    <div style={{ width: 10, height: 10, borderRadius: '50%', background: RULE_COLORS[r.rule_type] ?? '#94a3b8', flexShrink: 0 }} />
                    <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontWeight: 600, fontSize: 13, color: 'var(--text-primary)', marginBottom: 2 }}>{r.name}</div>
                        <div style={{ fontSize: 11, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontWeight: 500 }}>{r.table_name}.{r.column_name}</div>
                    </div>
                    <Badge label={r.severity} type={r.severity === 'critical' ? 'critical' : r.severity === 'warning' ? 'warning' : 'info'} />
                    </div>
                ))
            }
          </div>
        </div>

        <div style={{ width: 1, background: 'var(--border)', flexShrink: 0, alignSelf: 'stretch' }} />

        {/* ── RIGHT: Results ── */}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-hint)', textTransform: 'uppercase', letterSpacing: '1px', marginBottom: 20 }}>
            Last Scan Findings
          </div>

          {loadingS
            ? <div style={{ color: 'var(--text-hint)', fontSize: 13, display: 'flex', gap: 8, padding: '12px' }}><Loader size={14} className="spin" /> Interrogating database…</div>
            : latestResults.length === 0
              ? (
                <div style={{ textAlign: 'center', padding: '40px 20px', color: 'var(--text-muted)', fontSize: 14, border: '1px dashed var(--border)', borderRadius: 10 }}>
                  <div style={{ fontSize: 24, marginBottom: 12, opacity: 0.5 }}>⚡</div>
                  No active scan results found.<br />
                  <span style={{ fontSize: 12, marginTop: 8, display: 'block' }}>Initiate a <strong>Full Scan</strong> to populate findings.</span>
                </div>
              )
              : (
                <>
                  <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', marginBottom: 28, background: 'var(--bg-base)', padding: '20px', borderRadius: 12, border: '1px solid var(--border-subtle)' }}>
                    <ScoreRing score={overallScore ?? 0} size={120} />
                    <div style={{ marginTop: 12, textAlign: 'center' }}>
                        <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-hint)', textTransform: 'uppercase', letterSpacing: '1px' }}>Aggregate Quality Score</div>
                        <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4 }}>Based on {latestResults.length} interrogation points</div>
                    </div>
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                    {latestResults.map(r => (
                        <ScanResultCard
                        key={r.id}
                        ruleName={r.rule_name}
                        table={r.table_name}
                        column={r.column_name}
                        score={r.score}
                        status={r.status}
                        failedRows={r.failed_rows}
                        totalRows={r.total_rows}
                        reason={r.reason}
                        severity={r.severity}
                        />
                    ))}
                  </div>
                </>
              )
          }
        </div>
      </div>

      {showAdd && <AddRuleModal onClose={() => setShowAdd(false)} onSaved={loadRules} />}
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

const headerStyle = { display: 'flex', alignItems: 'center', gap: 12, marginBottom: 24 }
const headerTextStyle = { 
    fontFamily: 'var(--font-display)', 
    fontSize: 20, 
    fontWeight: 400, 
    color: 'var(--text-primary)',
    letterSpacing: '-0.2px',
}

function ErrBox({ msg }) {
  return <div style={{ background: 'var(--danger-bg)', border: '1px solid var(--danger-border)', borderRadius: 8, padding: '12px 18px', color: 'var(--danger)', fontSize: 13, fontWeight: 500, marginBottom: 20 }}>{msg}</div>
}
