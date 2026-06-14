import { useState, useEffect, useCallback } from 'react'
import {
  Brain, Loader, Plus, Trash2, ShieldAlert, CheckCircle,
  XCircle, AlertCircle, Clock, RefreshCw, Database, User,
  Activity, ChevronDown, ChevronUp, Edit2,
} from 'lucide-react'
import {
  getAiModels, createAiModel, updateAiModel, deleteAiModel,
  getModelCompliance, addComplianceCheck, updateComplianceCheck,
  deleteComplianceCheck, getAiGovernanceSummary,
} from '../../core/api.js'

const TABS = [
  { id: 'models',     label: 'Model Registry',    icon: Brain },
  { id: 'risk',       label: 'Risk & Compliance',  icon: ShieldAlert },
  { id: 'audit',      label: 'Governance Audit',   icon: Activity },
]

const RISK_CONFIG = {
  minimal:       { color: '#10b981', bg: 'rgba(16,185,129,0.1)',  label: 'Minimal' },
  limited:       { color: '#f59e0b', bg: 'rgba(245,158,11,0.1)',  label: 'Limited' },
  high:          { color: '#ef4444', bg: 'rgba(239,68,68,0.1)',   label: 'High' },
  unacceptable:  { color: '#7c3aed', bg: 'rgba(124,58,237,0.1)', label: 'Unacceptable' },
}

const STATUS_CONFIG = {
  active:       { color: '#10b981', label: 'Active' },
  deprecated:   { color: '#94a3b8', label: 'Deprecated' },
  under_review: { color: '#f59e0b', label: 'Under Review' },
}

const CHECK_CONFIG = {
  pass:    { color: '#10b981', Icon: CheckCircle,  label: 'Pass' },
  fail:    { color: '#ef4444', Icon: XCircle,      label: 'Fail' },
  pending: { color: '#94a3b8', Icon: Clock,        label: 'Pending' },
}

const EU_AI_ACT = {
  minimal:      'Minimal Risk — No specific obligations. Free to operate.',
  limited:      'Limited Risk — Transparency obligations required (users must know they interact with AI).',
  high:         'High Risk — Conformity assessment, documentation, human oversight mandatory.',
  unacceptable: 'Unacceptable Risk — Prohibited by EU AI Act. Must not be deployed.',
}

const DEFAULT_CHECKS = [
  'Privacy Impact Assessment (PIA) completed',
  'Bias testing performed on training data',
  'Human oversight mechanism defined',
  'Incident response plan documented',
  'Model owner / responsible team assigned',
]

// ── Shared badge ──────────────────────────────────────────────────────────────
function RiskBadge({ level }) {
  const cfg = RISK_CONFIG[level] || RISK_CONFIG.minimal
  return (
    <span style={{ fontSize: 11, fontWeight: 700, padding: '3px 9px', borderRadius: 20,
      background: cfg.bg, color: cfg.color, border: `1px solid ${cfg.color}40` }}>
      {cfg.label}
    </span>
  )
}

function StatusBadge({ status }) {
  const cfg = STATUS_CONFIG[status] || STATUS_CONFIG.active
  return (
    <span style={{ fontSize: 11, fontWeight: 600, padding: '3px 9px', borderRadius: 20,
      background: `${cfg.color}15`, color: cfg.color }}>
      {cfg.label}
    </span>
  )
}

// ── Register Model Modal ───────────────────────────────────────────────────────
function RegisterModelModal({ integrations, onSave, onClose, editModel }) {
  const [form, setForm] = useState(editModel ? {
    name: editModel.name, provider: editModel.provider || '',
    model_type: editModel.model_type || '', version: editModel.version || '',
    purpose: editModel.purpose || '', owner: editModel.owner || '',
    risk_level: editModel.risk_level || 'minimal',
    status: editModel.status || 'active',
    uses_pii: editModel.uses_pii || false,
    autonomous: editModel.autonomous || false,
    integration_id: editModel.integration_id || '',
  } : {
    name: '', provider: '', model_type: 'LLM', version: '',
    purpose: '', owner: '', risk_level: 'minimal', status: 'active',
    uses_pii: false, autonomous: false, integration_id: '',
  })
  const [saving, setSaving] = useState(false)

  const set = (k, v) => setForm(f => ({ ...f, [k]: v }))
  const inp = { background: 'var(--bg-base)', border: '1px solid var(--border)', borderRadius: 8,
    padding: '8px 12px', fontSize: 13, color: 'var(--text-primary)', fontFamily: 'inherit',
    width: '100%', outline: 'none', boxSizing: 'border-box' }
  const lbl = { fontSize: 11, fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase',
    letterSpacing: '0.6px', marginBottom: 5, display: 'block' }

  const handleSave = async () => {
    if (!form.name.trim()) return
    setSaving(true)
    try { await onSave(form) } finally { setSaving(false) }
  }

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', zIndex: 1000,
      display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)',
        borderRadius: 14, padding: 28, width: 560, maxHeight: '90vh', overflowY: 'auto',
        boxShadow: '0 24px 60px rgba(0,0,0,0.2)' }}>
        <div style={{ fontSize: 17, fontWeight: 700, color: 'var(--text-primary)', marginBottom: 22 }}>
          {editModel ? 'Edit AI Model' : 'Register AI Model'}
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
          <div style={{ gridColumn: '1/-1' }}>
            <label style={lbl}>Model Name *</label>
            <input style={inp} placeholder="e.g. GPT-4o, Claude 3.5 Sonnet" value={form.name} onChange={e => set('name', e.target.value)} />
          </div>
          <div>
            <label style={lbl}>Provider</label>
            <select style={inp} value={form.provider} onChange={e => set('provider', e.target.value)}>
              <option value="">Select provider</option>
              {['OpenAI','Anthropic','Google','Meta','HuggingFace','Mistral','Cohere','Custom'].map(p => (
                <option key={p} value={p}>{p}</option>
              ))}
            </select>
          </div>
          <div>
            <label style={lbl}>Model Type</label>
            <select style={inp} value={form.model_type} onChange={e => set('model_type', e.target.value)}>
              {['LLM','ML','CV','NLP','Multimodal','Custom'].map(t => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
          <div>
            <label style={lbl}>Version</label>
            <input style={inp} placeholder="e.g. gpt-4o-2024-11" value={form.version} onChange={e => set('version', e.target.value)} />
          </div>
          <div>
            <label style={lbl}>Owner / Team</label>
            <input style={inp} placeholder="e.g. Data Science Team" value={form.owner} onChange={e => set('owner', e.target.value)} />
          </div>
          <div>
            <label style={lbl}>EU AI Act Risk Level</label>
            <select style={inp} value={form.risk_level} onChange={e => set('risk_level', e.target.value)}>
              {Object.entries(RISK_CONFIG).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
            </select>
          </div>
          <div>
            <label style={lbl}>Status</label>
            <select style={inp} value={form.status} onChange={e => set('status', e.target.value)}>
              {Object.entries(STATUS_CONFIG).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
            </select>
          </div>
          <div style={{ gridColumn: '1/-1' }}>
            <label style={lbl}>Purpose / Use Case</label>
            <textarea style={{ ...inp, height: 72, resize: 'vertical' }} placeholder="Describe what this model is used for…"
              value={form.purpose} onChange={e => set('purpose', e.target.value)} />
          </div>
          <div style={{ gridColumn: '1/-1' }}>
            <label style={lbl}>Linked Data Source (optional)</label>
            <select style={inp} value={form.integration_id} onChange={e => set('integration_id', e.target.value)}>
              <option value="">None — not linked to a data source</option>
              {(integrations || []).map(ig => <option key={ig.id} value={ig.id}>{ig.name}</option>)}
            </select>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <input type="checkbox" id="uses_pii" checked={form.uses_pii}
              onChange={e => set('uses_pii', e.target.checked)} style={{ width: 16, height: 16 }} />
            <label htmlFor="uses_pii" style={{ fontSize: 13, color: 'var(--text-primary)', cursor: 'pointer' }}>
              Uses PII / sensitive data
            </label>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <input type="checkbox" id="autonomous" checked={form.autonomous}
              onChange={e => set('autonomous', e.target.checked)} style={{ width: 16, height: 16 }} />
            <label htmlFor="autonomous" style={{ fontSize: 13, color: 'var(--text-primary)', cursor: 'pointer' }}>
              Fully autonomous (no human review)
            </label>
          </div>
        </div>

        {form.risk_level !== 'minimal' && (
          <div style={{ marginTop: 14, padding: '10px 14px', borderRadius: 8, fontSize: 12,
            background: `${RISK_CONFIG[form.risk_level]?.color}10`,
            border: `1px solid ${RISK_CONFIG[form.risk_level]?.color}30`,
            color: RISK_CONFIG[form.risk_level]?.color }}>
            <strong>EU AI Act:</strong> {EU_AI_ACT[form.risk_level]}
          </div>
        )}

        <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', marginTop: 22 }}>
          <button onClick={onClose}
            style={{ padding: '9px 18px', borderRadius: 8, fontSize: 13, fontWeight: 600,
              border: '1px solid var(--border)', background: 'transparent', color: 'var(--text-muted)',
              cursor: 'pointer', fontFamily: 'inherit' }}>
            Cancel
          </button>
          <button onClick={handleSave} disabled={saving || !form.name.trim()}
            style={{ padding: '9px 20px', borderRadius: 8, fontSize: 13, fontWeight: 700,
              border: 'none', background: 'var(--accent-teal)', color: '#fff',
              cursor: saving || !form.name.trim() ? 'not-allowed' : 'pointer', fontFamily: 'inherit' }}>
            {saving ? 'Saving…' : editModel ? 'Update Model' : 'Register Model'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Tab 1: Model Registry ─────────────────────────────────────────────────────
function ModelsTab({ models, integrations, loading, onRefresh }) {
  const [showModal, setShowModal] = useState(false)
  const [editModel, setEditModel] = useState(null)
  const [deleting, setDeleting] = useState(null)

  const handleSave = async (form) => {
    if (editModel) {
      await updateAiModel(editModel.id, form)
    } else {
      await createAiModel(form)
    }
    setShowModal(false)
    setEditModel(null)
    onRefresh()
  }

  const handleDelete = async (id) => {
    if (!window.confirm('Remove this AI model and all its compliance checks?')) return
    setDeleting(id)
    try { await deleteAiModel(id); onRefresh() } finally { setDeleting(null) }
  }

  if (loading) return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--text-hint)', fontSize: 13, padding: 24 }}>
      <Loader size={14} className="spin" /> Loading models…
    </div>
  )

  return (
    <div>
      {(showModal || editModel) && (
        <RegisterModelModal
          integrations={integrations}
          editModel={editModel}
          onSave={handleSave}
          onClose={() => { setShowModal(false); setEditModel(null) }}
        />
      )}

      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 16 }}>
        <button onClick={() => setShowModal(true)}
          style={{ display: 'flex', alignItems: 'center', gap: 7, padding: '9px 18px',
            borderRadius: 8, fontSize: 13, fontWeight: 700, border: 'none',
            background: 'var(--accent-teal)', color: '#fff', cursor: 'pointer', fontFamily: 'inherit' }}>
          <Plus size={14} /> Register Model
        </button>
      </div>

      {!models.length ? (
        <div style={{ textAlign: 'center', padding: '60px 0' }}>
          <Brain size={40} color="var(--text-hint)" style={{ marginBottom: 12 }} />
          <div style={{ fontSize: 15, fontWeight: 600, color: 'var(--text-muted)', marginBottom: 6 }}>No AI models registered yet</div>
          <div style={{ fontSize: 12, color: 'var(--text-hint)' }}>Register the AI/GenAI models your organisation uses to start governing them.</div>
        </div>
      ) : (
        <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)', borderRadius: 12, overflow: 'hidden' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid var(--border)', background: 'var(--bg-base)' }}>
                {['Model','Provider','Type','Owner','Risk Level','Status','Data Source','Actions'].map(h => (
                  <th key={h} style={{ padding: '11px 16px', fontSize: 11, fontWeight: 700,
                    color: 'var(--text-hint)', textTransform: 'uppercase', letterSpacing: '0.6px' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {models.map((m, i) => (
                <tr key={m.id} style={{ borderBottom: i < models.length-1 ? '1px solid var(--border)' : 'none',
                  transition: 'background 0.15s' }}
                  onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-base)'}
                  onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>
                  <td style={{ padding: '12px 16px' }}>
                    <div style={{ fontWeight: 700, fontSize: 13, color: 'var(--text-primary)' }}>{m.name}</div>
                    <div style={{ display: 'flex', gap: 6, marginTop: 3 }}>
                      {m.uses_pii && <span style={{ fontSize: 10, background: '#ef444415', color: '#ef4444', borderRadius: 4, padding: '1px 6px', fontWeight: 600 }}>PII</span>}
                      {m.autonomous && <span style={{ fontSize: 10, background: '#f59e0b15', color: '#f59e0b', borderRadius: 4, padding: '1px 6px', fontWeight: 600 }}>Auto</span>}
                    </div>
                  </td>
                  <td style={{ padding: '12px 16px', fontSize: 13, color: 'var(--text-muted)' }}>{m.provider || '—'}</td>
                  <td style={{ padding: '12px 16px' }}>
                    <span style={{ fontSize: 11, fontFamily: 'monospace', background: 'var(--bg-panel)',
                      color: 'var(--accent-teal)', padding: '2px 8px', borderRadius: 4 }}>{m.model_type || '—'}</span>
                  </td>
                  <td style={{ padding: '12px 16px', fontSize: 13, color: 'var(--text-muted)' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                      <User size={12} /> {m.owner || '—'}
                    </div>
                  </td>
                  <td style={{ padding: '12px 16px' }}><RiskBadge level={m.risk_level} /></td>
                  <td style={{ padding: '12px 16px' }}><StatusBadge status={m.status} /></td>
                  <td style={{ padding: '12px 16px', fontSize: 12, color: 'var(--text-hint)' }}>
                    {m.integration_id ? <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}><Database size={11} /> Linked</span> : '—'}
                  </td>
                  <td style={{ padding: '12px 16px' }}>
                    <div style={{ display: 'flex', gap: 6 }}>
                      <button onClick={() => setEditModel(m)}
                        style={{ padding: '5px 8px', borderRadius: 6, border: '1px solid var(--border)',
                          background: 'transparent', cursor: 'pointer', color: 'var(--text-muted)', display: 'flex' }}>
                        <Edit2 size={13} />
                      </button>
                      <button onClick={() => handleDelete(m.id)} disabled={deleting === m.id}
                        style={{ padding: '5px 8px', borderRadius: 6, border: '1px solid rgba(239,68,68,0.3)',
                          background: 'transparent', cursor: 'pointer', color: '#ef4444', display: 'flex' }}>
                        {deleting === m.id ? <Loader size={13} className="spin" /> : <Trash2 size={13} />}
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// ── Tab 2: Risk & Compliance ──────────────────────────────────────────────────
function RiskTab({ models }) {
  const [selectedId, setSelectedId] = useState(null)
  const [checks, setChecks]         = useState([])
  const [loadingChecks, setLoadingChecks] = useState(false)
  const [newCheck, setNewCheck]     = useState({ check_name: '', check_status: 'pending', notes: '' })
  const [adding, setAdding]         = useState(false)
  const [showAddForm, setShowAddForm] = useState(false)

  const selectedModel = models.find(m => m.id === selectedId)

  const loadChecks = useCallback(async (id) => {
    if (!id) return
    setLoadingChecks(true)
    try { setChecks(await getModelCompliance(id)) } catch { setChecks([]) }
    setLoadingChecks(false)
  }, [])

  useEffect(() => { loadChecks(selectedId) }, [selectedId, loadChecks])

  useEffect(() => {
    if (!selectedId && models.length > 0) setSelectedId(models[0].id)
  }, [models, selectedId])

  const handleAddCheck = async () => {
    if (!newCheck.check_name.trim() || !selectedId) return
    setAdding(true)
    try {
      await addComplianceCheck(selectedId, newCheck)
      await loadChecks(selectedId)
      setNewCheck({ check_name: '', check_status: 'pending', notes: '' })
      setShowAddForm(false)
    } finally { setAdding(false) }
  }

  const handleStatusChange = async (checkId, newStatus) => {
    await updateComplianceCheck(checkId, { check_status: newStatus })
    loadChecks(selectedId)
  }

  const handleDeleteCheck = async (checkId) => {
    await deleteComplianceCheck(checkId)
    loadChecks(selectedId)
  }

  const addDefaultChecks = async () => {
    for (const name of DEFAULT_CHECKS) {
      if (checks.find(c => c.check_name === name)) continue
      await addComplianceCheck(selectedId, { check_name: name, check_status: 'pending' })
    }
    loadChecks(selectedId)
  }

  const passed = checks.filter(c => c.check_status === 'pass').length
  const score  = checks.length ? Math.round(passed / checks.length * 100) : null
  const scoreColor = score === null ? '#94a3b8' : score >= 80 ? '#10b981' : score >= 50 ? '#f59e0b' : '#ef4444'

  if (!models.length) return (
    <div style={{ textAlign: 'center', padding: '60px 0', color: 'var(--text-hint)', fontSize: 13 }}>
      No models registered yet — add a model first from the Model Registry tab.
    </div>
  )

  return (
    <div style={{ display: 'flex', gap: 24 }}>
      {/* Model selector sidebar */}
      <div style={{ width: 220, flexShrink: 0 }}>
        <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-hint)', textTransform: 'uppercase',
          letterSpacing: '0.6px', marginBottom: 10 }}>Select Model</div>
        {models.map(m => (
          <button key={m.id} onClick={() => setSelectedId(m.id)}
            style={{ width: '100%', textAlign: 'left', padding: '10px 12px', borderRadius: 8, border: 'none',
              marginBottom: 4, cursor: 'pointer', fontFamily: 'inherit',
              background: selectedId === m.id ? 'var(--accent-teal-soft)' : 'var(--bg-surface)',
              boxShadow: selectedId === m.id ? 'inset 3px 0 0 var(--accent-teal)' : 'none' }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: selectedId === m.id ? 'var(--accent-teal)' : 'var(--text-primary)' }}>
              {m.name}
            </div>
            <div style={{ marginTop: 4 }}><RiskBadge level={m.risk_level} /></div>
          </button>
        ))}
      </div>

      {/* Main content */}
      <div style={{ flex: 1 }}>
        {!selectedModel ? null : (
          <>
            {/* Risk Assessment Card */}
            <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)',
              borderRadius: 12, padding: 20, marginBottom: 20, boxShadow: 'var(--shadow-card)' }}>
              <div style={{ fontWeight: 700, fontSize: 15, color: 'var(--text-primary)', marginBottom: 14 }}>
                Risk Assessment — {selectedModel.name}
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 14 }}>
                {[
                  ['EU AI Act Tier',   <RiskBadge level={selectedModel.risk_level} />],
                  ['PII Usage',        selectedModel.uses_pii ? <span style={{color:'#ef4444',fontWeight:600,fontSize:13}}>⚠ Yes — uses personal data</span> : <span style={{color:'#10b981',fontWeight:600,fontSize:13}}>✓ No PII</span>],
                  ['Decision Mode',    selectedModel.autonomous ? <span style={{color:'#f59e0b',fontWeight:600,fontSize:13}}>⚠ Fully Autonomous</span> : <span style={{color:'#10b981',fontWeight:600,fontSize:13}}>✓ Human-in-the-loop</span>],
                  ['Status',          <StatusBadge status={selectedModel.status} />],
                ].map(([k, v]) => (
                  <div key={k} style={{ background: 'var(--bg-base)', borderRadius: 8, padding: '10px 14px' }}>
                    <div style={{ fontSize: 11, color: 'var(--text-hint)', fontWeight: 600, marginBottom: 5 }}>{k}</div>
                    <div>{v}</div>
                  </div>
                ))}
              </div>
              <div style={{ padding: '10px 14px', borderRadius: 8, fontSize: 12,
                background: `${RISK_CONFIG[selectedModel.risk_level]?.color}10`,
                border: `1px solid ${RISK_CONFIG[selectedModel.risk_level]?.color}30`,
                color: RISK_CONFIG[selectedModel.risk_level]?.color }}>
                <strong>EU AI Act guidance:</strong> {EU_AI_ACT[selectedModel.risk_level]}
              </div>
            </div>

            {/* Compliance Checklist */}
            <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)', borderRadius: 12, overflow: 'hidden' }}>
              <div style={{ padding: '14px 20px', borderBottom: '1px solid var(--border)',
                display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
                  <span style={{ fontWeight: 700, fontSize: 14, color: 'var(--text-primary)' }}>Compliance Checklist</span>
                  {score !== null && (
                    <span style={{ fontSize: 12, fontWeight: 700, color: scoreColor,
                      background: `${scoreColor}15`, borderRadius: 20, padding: '3px 10px' }}>
                      {passed}/{checks.length} passed · {score}%
                    </span>
                  )}
                </div>
                <div style={{ display: 'flex', gap: 8 }}>
                  {!checks.length && (
                    <button onClick={addDefaultChecks}
                      style={{ fontSize: 12, fontWeight: 600, padding: '7px 14px', borderRadius: 7,
                        border: '1px solid var(--border)', background: 'var(--bg-base)',
                        cursor: 'pointer', color: 'var(--text-muted)', fontFamily: 'inherit' }}>
                      + Add Default Checks
                    </button>
                  )}
                  <button onClick={() => setShowAddForm(f => !f)}
                    style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, fontWeight: 700,
                      padding: '7px 14px', borderRadius: 7, border: 'none',
                      background: 'var(--accent-teal)', color: '#fff', cursor: 'pointer', fontFamily: 'inherit' }}>
                    <Plus size={13} /> Add Check
                  </button>
                </div>
              </div>

              {showAddForm && (
                <div style={{ padding: '14px 20px', borderBottom: '1px solid var(--border)', background: 'var(--bg-base)' }}>
                  <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                    <input
                      placeholder="Check name (e.g. Privacy Impact Assessment completed)"
                      value={newCheck.check_name}
                      onChange={e => setNewCheck(n => ({ ...n, check_name: e.target.value }))}
                      style={{ flex: 1, minWidth: 200, padding: '8px 12px', borderRadius: 7, fontSize: 12,
                        border: '1px solid var(--border)', background: 'var(--bg-surface)',
                        color: 'var(--text-primary)', fontFamily: 'inherit', outline: 'none' }}
                    />
                    <select value={newCheck.check_status}
                      onChange={e => setNewCheck(n => ({ ...n, check_status: e.target.value }))}
                      style={{ padding: '8px 12px', borderRadius: 7, fontSize: 12, border: '1px solid var(--border)',
                        background: 'var(--bg-surface)', color: 'var(--text-primary)', fontFamily: 'inherit' }}>
                      <option value="pending">Pending</option>
                      <option value="pass">Pass</option>
                      <option value="fail">Fail</option>
                    </select>
                    <input placeholder="Notes (optional)" value={newCheck.notes}
                      onChange={e => setNewCheck(n => ({ ...n, notes: e.target.value }))}
                      style={{ width: 180, padding: '8px 12px', borderRadius: 7, fontSize: 12,
                        border: '1px solid var(--border)', background: 'var(--bg-surface)',
                        color: 'var(--text-primary)', fontFamily: 'inherit', outline: 'none' }}
                    />
                    <button onClick={handleAddCheck} disabled={adding || !newCheck.check_name.trim()}
                      style={{ padding: '8px 16px', borderRadius: 7, border: 'none', fontSize: 12, fontWeight: 700,
                        background: 'var(--accent-teal)', color: '#fff', cursor: 'pointer', fontFamily: 'inherit' }}>
                      {adding ? 'Adding…' : 'Add'}
                    </button>
                  </div>
                </div>
              )}

              {loadingChecks ? (
                <div style={{ padding: 24, display: 'flex', alignItems: 'center', gap: 8, color: 'var(--text-hint)', fontSize: 13 }}>
                  <Loader size={14} className="spin" /> Loading checks…
                </div>
              ) : !checks.length ? (
                <div style={{ padding: 32, textAlign: 'center', color: 'var(--text-hint)', fontSize: 13 }}>
                  No compliance checks yet. Click "Add Default Checks" to start with standard requirements.
                </div>
              ) : (
                checks.map((c, i) => {
                  const cfg = CHECK_CONFIG[c.check_status] || CHECK_CONFIG.pending
                  return (
                    <div key={c.id} style={{ display: 'flex', alignItems: 'center', gap: 12,
                      padding: '11px 20px', borderBottom: i < checks.length-1 ? '1px solid var(--border)' : 'none' }}>
                      <cfg.Icon size={16} color={cfg.color} style={{ flexShrink: 0 }} />
                      <div style={{ flex: 1 }}>
                        <div style={{ fontSize: 13, fontWeight: 500, color: 'var(--text-primary)' }}>{c.check_name}</div>
                        {c.notes && <div style={{ fontSize: 11, color: 'var(--text-hint)', marginTop: 2 }}>{c.notes}</div>}
                      </div>
                      <select value={c.check_status}
                        onChange={e => handleStatusChange(c.id, e.target.value)}
                        style={{ padding: '4px 8px', borderRadius: 6, fontSize: 11, fontWeight: 700,
                          border: `1px solid ${cfg.color}40`, background: `${cfg.color}10`,
                          color: cfg.color, fontFamily: 'inherit', cursor: 'pointer' }}>
                        <option value="pending">Pending</option>
                        <option value="pass">Pass</option>
                        <option value="fail">Fail</option>
                      </select>
                      <button onClick={() => handleDeleteCheck(c.id)}
                        style={{ padding: '4px 6px', borderRadius: 6, border: '1px solid rgba(239,68,68,0.2)',
                          background: 'transparent', cursor: 'pointer', color: '#ef4444', display: 'flex' }}>
                        <Trash2 size={13} />
                      </button>
                    </div>
                  )
                })
              )}
            </div>
          </>
        )}
      </div>
    </div>
  )
}

// ── Tab 3: Governance Audit ───────────────────────────────────────────────────
function AuditTab() {
  const [logs, setLogs]       = useState([])
  const [loading, setLoading] = useState(true)

  const AI_EVENTS = ['AI_MODEL_REGISTERED','AI_MODEL_UPDATED','AI_MODEL_REMOVED','AI_COMPLIANCE_CHECKED']

  const load = async () => {
    setLoading(true)
    try {
      const { getAuditLogs } = await import('../../core/api.js')
      const data = await getAuditLogs({ limit: 100 })
      const items = Array.isArray(data) ? data : (data.logs || data.items || [])
      setLogs(items.filter(l => AI_EVENTS.includes(l.event_type)))
    } catch { setLogs([]) }
    setLoading(false)
  }

  useEffect(() => { load() }, [])

  const EVENT_COLOR = {
    AI_MODEL_REGISTERED:  '#10b981',
    AI_MODEL_UPDATED:     '#3b82f6',
    AI_MODEL_REMOVED:     '#ef4444',
    AI_COMPLIANCE_CHECKED:'#8b5cf6',
  }
  const EVENT_LABEL = {
    AI_MODEL_REGISTERED:  'Model Registered',
    AI_MODEL_UPDATED:     'Model Updated',
    AI_MODEL_REMOVED:     'Model Removed',
    AI_COMPLIANCE_CHECKED:'Compliance Checked',
  }

  if (loading) return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--text-hint)', fontSize: 13, padding: 24 }}>
      <Loader size={14} className="spin" /> Loading audit trail…
    </div>
  )

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 14 }}>
        <button onClick={load}
          style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '8px 14px', borderRadius: 8,
            border: '1px solid var(--border)', background: 'transparent', cursor: 'pointer',
            fontSize: 12, fontWeight: 600, color: 'var(--text-muted)', fontFamily: 'inherit' }}>
          <RefreshCw size={12} /> Refresh
        </button>
      </div>

      {!logs.length ? (
        <div style={{ textAlign: 'center', padding: '60px 0' }}>
          <Activity size={36} color="var(--text-hint)" style={{ marginBottom: 12 }} />
          <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-muted)', marginBottom: 6 }}>No AI governance events yet</div>
          <div style={{ fontSize: 12, color: 'var(--text-hint)' }}>Events will appear here when you register models or update compliance checks.</div>
        </div>
      ) : (
        <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)', borderRadius: 12, overflow: 'hidden' }}>
          {logs.map((l, i) => {
            const col = EVENT_COLOR[l.event_type] || '#94a3b8'
            return (
              <div key={l.id || i} style={{ display: 'flex', alignItems: 'flex-start', gap: 14,
                padding: '13px 20px', borderBottom: i < logs.length-1 ? '1px solid var(--border)' : 'none' }}>
                <div style={{ width: 8, height: 8, borderRadius: '50%', background: col,
                  flexShrink: 0, marginTop: 5 }} />
                <div style={{ flex: 1 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                    <span style={{ fontSize: 11, fontWeight: 700, padding: '2px 8px', borderRadius: 20,
                      background: `${col}15`, color: col }}>
                      {EVENT_LABEL[l.event_type] || l.event_type}
                    </span>
                    <span style={{ fontSize: 13, color: 'var(--text-primary)', fontWeight: 500 }}>{l.description}</span>
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--text-hint)', marginTop: 4 }}>
                    {l.created_at ? new Date(l.created_at).toLocaleString() : '—'}
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

// ── Summary stats bar ─────────────────────────────────────────────────────────
function SummaryBar({ summary }) {
  if (!summary) return null
  const stats = [
    ['Total Models',   summary.total_models,   '#14b8a6'],
    ['Active',         summary.active_models,  '#10b981'],
    ['High Risk',      summary.high_risk,       summary.high_risk > 0 ? '#ef4444' : '#94a3b8'],
    ['Uses PII',       summary.uses_pii,        summary.uses_pii > 0  ? '#f59e0b' : '#94a3b8'],
    ['Compliance',     summary.compliance_pct !== null ? `${summary.compliance_pct}%` : '—', '#8b5cf6'],
  ]
  return (
    <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', padding: '14px 28px',
      background: 'var(--bg-base)', borderBottom: '1px solid var(--border)' }}>
      {stats.map(([label, val, color]) => (
        <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 8,
          background: 'var(--bg-surface)', border: '1px solid var(--border)',
          borderRadius: 8, padding: '8px 14px', boxShadow: 'var(--shadow-card)' }}>
          <span style={{ fontSize: 18, fontWeight: 800, color }}>{val}</span>
          <span style={{ fontSize: 11, color: 'var(--text-hint)', fontWeight: 600 }}>{label}</span>
        </div>
      ))}
    </div>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────
export default function AiGovernance() {
  const [activeTab,    setActiveTab]    = useState('models')
  const [models,       setModels]       = useState([])
  const [integrations, setIntegrations] = useState([])
  const [summary,      setSummary]      = useState(null)
  const [loading,      setLoading]      = useState(true)

  const loadAll = useCallback(async () => {
    setLoading(true)
    try {
      const [mods, summ] = await Promise.all([
        getAiModels().catch(() => []),
        getAiGovernanceSummary().catch(() => null),
      ])
      setModels(Array.isArray(mods) ? mods : [])
      setSummary(summ)

      const { getIntegrations } = await import('../../core/api.js')
      const igs = await getIntegrations().catch(() => [])
      setIntegrations(Array.isArray(igs) ? igs : [])
    } finally { setLoading(false) }
  }, [])

  useEffect(() => { loadAll() }, [loadAll])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>

      {/* Header */}
      <div style={{ background: 'var(--bg-surface)', borderBottom: '1px solid var(--border)',
        padding: '14px 28px', flexShrink: 0,
        display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16 }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div style={{ width: 32, height: 32, borderRadius: 8, flexShrink: 0,
              background: 'linear-gradient(135deg,#7c3aed,#8b5cf6)',
              display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <Brain size={16} color="#fff" />
            </div>
            <div>
              <div style={{ fontFamily: 'var(--font-display)', fontSize: 20, fontWeight: 400,
                color: 'var(--text-primary)', letterSpacing: '-0.2px' }}>AI Governance</div>
              <div style={{ fontSize: 11, color: 'var(--text-hint)', marginTop: 1 }}>
                GenAI · Model Registry · Risk Assessment · Compliance · Audit
              </div>
            </div>
          </div>
        </div>
        <button onClick={loadAll}
          style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '8px 14px',
            borderRadius: 8, border: '1px solid var(--border)', background: 'transparent',
            cursor: 'pointer', fontSize: 12, fontWeight: 600, color: 'var(--text-muted)', fontFamily: 'inherit' }}>
          <RefreshCw size={13} /> Refresh
        </button>
      </div>

      {/* Summary stats */}
      <SummaryBar summary={summary} />

      {/* Tab bar */}
      <div style={{ background: 'var(--bg-surface)', borderBottom: '1px solid var(--border)',
        padding: '0 28px', display: 'flex', gap: 0, flexShrink: 0 }}>
        {TABS.map(({ id, label, icon: Icon }) => {
          const isActive = activeTab === id
          return (
            <button key={id} onClick={() => setActiveTab(id)}
              style={{ display: 'flex', alignItems: 'center', gap: 7, padding: '12px 16px',
                fontSize: 13, fontWeight: isActive ? 700 : 500,
                color: isActive ? '#8b5cf6' : 'var(--text-muted)',
                background: 'none', border: 'none',
                borderBottom: isActive ? '2px solid #8b5cf6' : '2px solid transparent',
                cursor: 'pointer', fontFamily: 'inherit', transition: 'all 0.18s', marginBottom: -1 }}>
              <Icon size={14} /> {label}
            </button>
          )
        })}
      </div>

      {/* Content */}
      <main style={{ flex: 1, overflowY: 'auto', padding: '28px 32px' }}>
        <div style={{ display: activeTab === 'models' ? 'block' : 'none' }}>
          <ModelsTab models={models} integrations={integrations} loading={loading} onRefresh={loadAll} />
        </div>
        <div style={{ display: activeTab === 'risk' ? 'block' : 'none' }}>
          <RiskTab models={models} />
        </div>
        <div style={{ display: activeTab === 'audit' ? 'block' : 'none' }}>
          <AuditTab />
        </div>
      </main>
    </div>
  )
}
