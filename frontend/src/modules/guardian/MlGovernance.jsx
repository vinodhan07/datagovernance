import { useState, useEffect, useCallback } from 'react'
import {
  FlaskConical, Link, Unlink, RefreshCw, Settings, Play,
  CheckCircle, XCircle, ChevronDown, ChevronUp,
  Brain, Activity, Loader, Trash2, X, AlertCircle, Info,
} from 'lucide-react'
import {
  getMlflowConnection, connectMlflow, disconnectMlflow,
  getMlflowRegistry, getMlflowVersions,
  getMlModels, createMlModel, updateMlModel, deleteMlModel,
  getMlScans, getMlScanStream, getMlSummary,
  getIntegrations, syncMlflowModels, trainAndRegisterMlModel,
} from '../../core/api.js'
import { getAuthHeader } from '../../core/api.js'

// ── Colour tokens ──────────────────────────────────────────────────────────────
const C = {
  bg:       'var(--bg-base)',
  surface:  'var(--bg-surface)',
  panel:    'var(--bg-panel)',
  border:   'var(--border)',
  teal:     'var(--accent-teal)',
  tealSoft: 'var(--accent-teal-soft)',
  primary:  'var(--text-primary)',
  muted:    'var(--text-muted)',
  hint:     'var(--text-hint)',
}

// ── Helpers ────────────────────────────────────────────────────────────────────
const Pill = ({ label, color = '#10b981' }) => (
  <span style={{
    display: 'inline-block', padding: '2px 8px', borderRadius: 99,
    fontSize: 11, fontWeight: 600, letterSpacing: '0.3px',
    background: `${color}22`, color,
  }}>{label}</span>
)

const stageColor = s => ({ Production: '#10b981', Staging: '#f59e0b', Archived: '#6b7280', None: '#8b5cf6' }[s] || '#8b5cf6')

const verdictBadge = verdict => {
  if (!verdict) return null
  const map = {
    biased:         { label: 'BIASED',        color: '#ef4444' },
    fair:           { label: 'COMPLIANT',      color: '#10b981' },
    drift_detected: { label: 'DRIFT DETECTED', color: '#f59e0b' },
    stable:         { label: 'STABLE',         color: '#10b981' },
    unknown:        { label: 'UNKNOWN',        color: '#6b7280' },
  }
  const m = map[verdict] || { label: verdict.toUpperCase(), color: '#6b7280' }
  return <Pill label={m.label} color={m.color} />
}

function Section({ title, children }) {
  return (
    <div style={{ marginBottom: 24 }}>
      <div style={{ fontSize: 11, fontWeight: 700, color: C.hint, textTransform: 'uppercase', letterSpacing: '1px', marginBottom: 10 }}>{title}</div>
      {children}
    </div>
  )
}

function StatCard({ label, value, color = '#10b981' }) {
  return (
    <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 10, padding: '14px 18px', minWidth: 120 }}>
      <div style={{ fontSize: 24, fontWeight: 700, color }}>{value ?? '—'}</div>
      <div style={{ fontSize: 12, color: C.muted, marginTop: 2 }}>{label}</div>
    </div>
  )
}

// ── Connection Panel ───────────────────────────────────────────────────────────
function ConnectionPanel({ connection, onConnect, onDisconnect, registryCount }) {
  const [url, setUrl]           = useState(connection?.url || '')
  const [connecting, setConn]   = useState(false)
  const [error, setError]       = useState(null)

  useEffect(() => { if (connection?.url) setUrl(connection.url) }, [connection])

  const handleConnect = async () => {
    if (!url.trim()) return
    setConn(true); setError(null)
    try { await onConnect(url.trim()) }
    catch (e) { setError(e.message) }
    finally { setConn(false) }
  }

  const connected = connection?.status === 'connected'

  return (
    <div style={{
      background: C.surface,
      border: `1px solid ${connected ? 'rgba(16,185,129,0.35)' : C.border}`,
      borderRadius: 12, padding: '18px 20px', marginBottom: 24,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14 }}>
        <FlaskConical size={18} color={C.teal} />
        <span style={{ fontWeight: 700, fontSize: 15, color: C.primary }}>MLflow Server</span>
        {connected && (
          <span style={{ marginLeft: 'auto', fontSize: 12, color: '#10b981', display: 'flex', alignItems: 'center', gap: 5 }}>
            <CheckCircle size={13} /> Connected — {registryCount} model{registryCount !== 1 ? 's' : ''} found
          </span>
        )}
        {connection?.status === 'error' && (
          <span style={{ marginLeft: 'auto', fontSize: 12, color: '#ef4444', display: 'flex', alignItems: 'center', gap: 5 }}>
            <XCircle size={13} /> {connection.error_msg?.slice(0, 80)}
          </span>
        )}
      </div>

      <div style={{ display: 'flex', gap: 10 }}>
        <input
          value={url}
          onChange={e => setUrl(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && !connected && handleConnect()}
          placeholder="http://localhost:5000"
          disabled={connected}
          style={{
            flex: 1, padding: '9px 12px', borderRadius: 8,
            border: `1px solid ${C.border}`,
            background: connected ? C.panel : C.bg,
            color: C.primary, fontSize: 13, fontFamily: 'monospace', outline: 'none',
          }}
        />
        {connected ? (
          <button onClick={() => onDisconnect(connection.id)} style={{
            padding: '9px 16px', borderRadius: 8, border: `1px solid ${C.border}`,
            background: 'transparent', color: '#ef4444', fontSize: 13, fontWeight: 600,
            cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 6,
          }}>
            <Unlink size={14} /> Disconnect
          </button>
        ) : (
          <button onClick={handleConnect} disabled={connecting || !url.trim()} style={{
            padding: '9px 20px', borderRadius: 8, border: 'none',
            background: connecting || !url.trim() ? C.panel : C.teal,
            color: connecting || !url.trim() ? C.muted : '#fff',
            fontSize: 13, fontWeight: 600,
            cursor: connecting || !url.trim() ? 'not-allowed' : 'pointer',
            display: 'flex', alignItems: 'center', gap: 6,
          }}>
            {connecting ? <><Loader size={13} className="spin" /> Connecting…</> : <><Link size={13} /> Connect</>}
          </button>
        )}
      </div>
      {error && <div style={{ marginTop: 8, fontSize: 12, color: '#ef4444' }}>{error}</div>}

      {connected && (
        <div style={{ marginTop: 12, padding: '10px 14px', background: C.tealSoft, borderRadius: 8, fontSize: 12, color: C.teal, display: 'flex', gap: 8, alignItems: 'flex-start' }}>
          <Info size={14} style={{ flexShrink: 0, marginTop: 1 }} />
          <span>
            <b>How to run governance scans:</b> Click <b>Configure</b> on any model card below → set the data table &amp; columns → click <b>Save</b> → then click <b>Scan</b> to run bias, drift, and explainability analysis.
          </span>
        </div>
      )}
    </div>
  )
}

// ── Configure & Scan Modal ─────────────────────────────────────────────────────
function ConfigureModal({ registryModel, existingConfig, onSave, onClose }) {
  const [versions, setVersions]         = useState([])
  const [integrations, setIntegrations] = useState([])
  const [saving, setSaving]             = useState(false)
  const [form, setForm]                 = useState({
    mlflow_version:  existingConfig?.mlflow_version || registryModel.latest_versions?.[0]?.version || '1',
    mlflow_stage:    existingConfig?.mlflow_stage   || registryModel.latest_versions?.[0]?.stage   || 'None',
    target_table:    existingConfig?.target_table   || '',
    target_column:   existingConfig?.target_column  || '',
    feature_columns: (existingConfig?.feature_columns || []).join(', '),
    protected_attrs: (existingConfig?.protected_attrs || []).join(', '),
    task_type:       existingConfig?.task_type      || 'classification',
    integration_id:  existingConfig?.integration_id || '',
  })

  useEffect(() => {
    getMlflowVersions(registryModel.name).then(setVersions).catch(() => setVersions(registryModel.latest_versions || []))
    getIntegrations().then(setIntegrations).catch(() => {})
  }, [registryModel.name])

  const set = (k, v) => setForm(f => ({ ...f, [k]: v }))

  const handleSave = async () => {
    setSaving(true)
    try {
      await onSave({
        name:              registryModel.name,
        mlflow_model_name: registryModel.name,
        mlflow_server_url: registryModel.mlflow_url,
        mlflow_version:    form.mlflow_version,
        mlflow_stage:      form.mlflow_stage,
        target_table:      form.target_table,
        target_column:     form.target_column,
        task_type:         form.task_type,
        feature_columns:   form.feature_columns.split(',').map(s => s.trim()).filter(Boolean),
        protected_attrs:   form.protected_attrs.split(',').map(s => s.trim()).filter(Boolean),
        integration_id:    form.integration_id || null,
      })
      onClose()
    } catch (e) {
      alert(e.message)
    } finally {
      setSaving(false)
    }
  }

  const inp = {
    width: '100%', boxSizing: 'border-box', padding: '8px 10px', borderRadius: 7,
    border: `1px solid ${C.border}`, background: C.bg, color: C.primary,
    fontSize: 13, fontFamily: 'inherit', outline: 'none',
  }
  const lbl = { fontSize: 12, fontWeight: 600, color: C.muted, marginBottom: 4, display: 'block' }

  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 1000, background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ background: C.surface, borderRadius: 14, padding: 28, width: 520, maxWidth: '95vw', border: `1px solid ${C.border}`, maxHeight: '90vh', overflowY: 'auto' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 }}>
          <div>
            <div style={{ fontWeight: 700, fontSize: 16, color: C.primary }}>{registryModel.name}</div>
            <div style={{ fontSize: 12, color: C.muted, marginTop: 2 }}>Configure data source for bias, drift &amp; explainability scans</div>
          </div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', color: C.hint }}><X size={18} /></button>
        </div>

        {/* Step guide */}
        <div style={{ background: C.tealSoft, borderRadius: 8, padding: '10px 14px', marginBottom: 18, fontSize: 12, color: C.teal }}>
          Fill in the data source below, save, then click <b>Scan</b> on the model card to run bias/drift/explainability checks.
        </div>

        <div style={{ display: 'grid', gap: 14 }}>
          <div>
            <label style={lbl}>Model Version</label>
            <select value={form.mlflow_version} onChange={e => {
              const v = versions.find(x => x.version === e.target.value)
              set('mlflow_version', e.target.value)
              if (v) set('mlflow_stage', v.stage)
            }} style={inp}>
              {(versions.length > 0 ? versions : registryModel.latest_versions || []).map(v => (
                <option key={v.version} value={v.version}>v{v.version} — {v.stage}</option>
              ))}
            </select>
          </div>

          <div>
            <label style={lbl}>Task Type</label>
            <select value={form.task_type} onChange={e => set('task_type', e.target.value)} style={inp}>
              <option value="classification">Classification</option>
              <option value="regression">Regression</option>
            </select>
          </div>

          {integrations.length > 0 && (
            <div>
              <label style={lbl}>Data Connector (optional — leave blank to use PostgreSQL)</label>
              <select value={form.integration_id} onChange={e => set('integration_id', e.target.value)} style={inp}>
                <option value="">— None (use PostgreSQL table) —</option>
                {integrations.map(i => <option key={i.id} value={i.id}>{i.name}</option>)}
              </select>
            </div>
          )}

          <div>
            <label style={lbl}>Data Table <span style={{ color: '#ef4444' }}>*</span> <span style={{ fontWeight: 400, color: C.hint }}>(used for bias/drift analysis)</span></label>
            <input value={form.target_table} onChange={e => set('target_table', e.target.value)}
              placeholder="e.g. ml_sample_customers" style={inp} />
          </div>

          <div>
            <label style={lbl}>Target Column <span style={{ fontWeight: 400, color: C.hint }}>(label the model predicts)</span></label>
            <input value={form.target_column} onChange={e => set('target_column', e.target.value)}
              placeholder="e.g. churn" style={inp} />
          </div>

          <div>
            <label style={lbl}>Feature Columns <span style={{ fontWeight: 400, color: C.hint }}>(comma-separated — leave blank to auto-detect)</span></label>
            <textarea value={form.feature_columns} onChange={e => set('feature_columns', e.target.value)}
              rows={2} placeholder="e.g. age, income, tenure_months"
              style={{ ...inp, resize: 'vertical' }} />
          </div>

          <div>
            <label style={lbl}>Protected Attributes <span style={{ fontWeight: 400, color: C.hint }}>(for bias detection — e.g. gender, age_group)</span></label>
            <textarea value={form.protected_attrs} onChange={e => set('protected_attrs', e.target.value)}
              rows={2} placeholder="e.g. gender, age_group"
              style={{ ...inp, resize: 'vertical' }} />
          </div>
        </div>

        <div style={{ display: 'flex', gap: 10, marginTop: 22, justifyContent: 'flex-end' }}>
          <button onClick={onClose} style={{ padding: '9px 18px', borderRadius: 8, border: `1px solid ${C.border}`, background: 'transparent', color: C.muted, fontSize: 13, cursor: 'pointer' }}>Cancel</button>
          <button onClick={handleSave} disabled={saving || !form.target_table} style={{
            padding: '9px 22px', borderRadius: 8, border: 'none',
            background: saving || !form.target_table ? C.panel : C.teal,
            color: saving || !form.target_table ? C.muted : '#fff',
            fontSize: 13, fontWeight: 600,
            cursor: saving || !form.target_table ? 'not-allowed' : 'pointer',
          }}>
            {saving ? 'Saving…' : 'Save Configuration'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Train & Register Modal ───────────────────────────────────────────────────
function TrainRegisterModal({ onSave, onClose }) {
  const [saving, setSaving] = useState(false)
  const [form, setForm] = useState({
    model_name:      '',
    task_type:       'classification',
    db_host:         '',
    db_port:         '',
    db_user:         '',
    db_password:     '',
    db_name:         '',
    target_table:    '',
    target_column:   '',
    feature_columns: '',
    protected_attrs: '',
  })

  const set = (k, v) => setForm(f => ({ ...f, [k]: v }))

  const handleTrain = async () => {
    setSaving(true)
    try {
      await onSave(form)
      onClose()
    } catch (e) {
      alert(e.message)
    } finally {
      setSaving(false)
    }
  }

  const inp = {
    width: '100%', boxSizing: 'border-box', padding: '8px 10px', borderRadius: 7,
    border: `1px solid ${C.border}`, background: C.bg, color: C.primary,
    fontSize: 13, fontFamily: 'inherit', outline: 'none',
  }
  const lbl = { fontSize: 12, fontWeight: 600, color: C.muted, marginBottom: 4, display: 'block' }

  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 1000, background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ background: C.surface, borderRadius: 14, padding: 28, width: 550, maxWidth: '95vw', border: `1px solid ${C.border}`, maxHeight: '90vh', overflowY: 'auto' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 }}>
          <div>
            <div style={{ fontWeight: 700, fontSize: 16, color: C.primary }}>Train &amp; Register Model</div>
            <div style={{ fontSize: 12, color: C.muted, marginTop: 2 }}>Train a Random Forest model on MariaDB and register to MLflow</div>
          </div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', color: C.hint }}><X size={18} /></button>
        </div>

        <div style={{ display: 'grid', gap: 14 }}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <div>
              <label style={lbl}>Model Name <span style={{ color: '#ef4444' }}>*</span></label>
              <input value={form.model_name} onChange={e => set('model_name', e.target.value)} placeholder="e.g. adult_income_rf" style={inp} />
            </div>
            <div>
              <label style={lbl}>Task Type</label>
              <select value={form.task_type} onChange={e => set('task_type', e.target.value)} style={inp}>
                <option value="classification">Classification</option>
                <option value="regression">Regression</option>
              </select>
            </div>
          </div>

          <div style={{ border: `1px solid ${C.border}`, borderRadius: 8, padding: 12, background: C.bg }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: C.primary, marginBottom: 8 }}>Database Connection Credentials</div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8, marginBottom: 8 }}>
              <div>
                <label style={lbl}>Host</label>
                <input value={form.db_host} onChange={e => set('db_host', e.target.value)} placeholder="e.g. 127.0.0.1" style={inp} />
              </div>
              <div>
                <label style={lbl}>Port</label>
                <input value={form.db_port} onChange={e => set('db_port', e.target.value)} placeholder="e.g. 3307" style={inp} />
              </div>
              <div>
                <label style={lbl}>Database Name</label>
                <input value={form.db_name} onChange={e => set('db_name', e.target.value)} placeholder="e.g. governance_db" style={inp} />
              </div>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
              <div>
                <label style={lbl}>Username</label>
                <input value={form.db_user} onChange={e => set('db_user', e.target.value)} placeholder="e.g. root" style={inp} />
              </div>
              <div>
                <label style={lbl}>Password</label>
                <input type="password" value={form.db_password} onChange={e => set('db_password', e.target.value)} placeholder="••••••••" style={inp} />
              </div>
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <div>
              <label style={lbl}>Target Table <span style={{ color: '#ef4444' }}>*</span></label>
              <input value={form.target_table} onChange={e => set('target_table', e.target.value)} placeholder="e.g. adult_income" style={inp} />
            </div>
            <div>
              <label style={lbl}>Target Column <span style={{ color: '#ef4444' }}>*</span></label>
              <input value={form.target_column} onChange={e => set('target_column', e.target.value)} placeholder="e.g. income" style={inp} />
            </div>
          </div>

          <div>
            <label style={lbl}>Feature Columns <span style={{ fontWeight: 400, color: C.hint }}>(comma-separated — leave blank for all)</span></label>
            <input value={form.feature_columns} onChange={e => set('feature_columns', e.target.value)} placeholder="e.g. age, workclass, education" style={inp} />
          </div>

          <div>
            <label style={lbl}>Protected Attributes <span style={{ fontWeight: 400, color: C.hint }}>(for bias scans — comma-separated)</span></label>
            <input value={form.protected_attrs} onChange={e => set('protected_attrs', e.target.value)} placeholder="e.g. sex, race" style={inp} />
          </div>
        </div>

        <div style={{ display: 'flex', gap: 10, marginTop: 22, justifyContent: 'flex-end' }}>
          <button onClick={onClose} style={{ padding: '9px 18px', borderRadius: 8, border: `1px solid ${C.border}`, background: 'transparent', color: C.muted, fontSize: 13, cursor: 'pointer' }}>Cancel</button>
          <button onClick={handleTrain} disabled={saving || !form.model_name || !form.target_table || !form.target_column} style={{
            padding: '9px 22px', borderRadius: 8, border: 'none',
            background: saving || !form.model_name || !form.target_table || !form.target_column ? C.panel : C.teal,
            color: saving || !form.model_name || !form.target_table || !form.target_column ? C.muted : '#fff',
            fontSize: 13, fontWeight: 600,
            cursor: saving || !form.model_name || !form.target_table || !form.target_column ? 'not-allowed' : 'pointer',
          }}>
            {saving ? 'Training & Scanning…' : 'Train & Scan Model'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Bias / Drift / Shap display ────────────────────────────────────────────────
function BiasResults({ data }) {
  if (!data) return <div style={{ color: C.muted, fontSize: 13 }}>No bias results yet.</div>
  if (data.error) return <div style={{ color: '#ef4444', fontSize: 13 }}>{data.error}</div>
  return (
    <div>
      <div style={{ display: 'flex', gap: 10, marginBottom: 16, alignItems: 'center' }}>
        <span style={{ fontWeight: 600, color: C.primary }}>Overall verdict:</span>
        {verdictBadge(data.overall_verdict)}
        {data.message && <span style={{ fontSize: 12, color: C.hint }}>{data.message}</span>}
      </div>
      {Object.entries(data.attributes || {}).map(([attr, res]) => (
        <div key={attr} style={{ background: C.bg, border: `1px solid ${C.border}`, borderRadius: 8, padding: '12px 14px', marginBottom: 10 }}>
          <div style={{ display: 'flex', gap: 8, marginBottom: 8, alignItems: 'center' }}>
            <span style={{ fontWeight: 600, color: C.primary, fontSize: 13 }}>{attr}</span>
            {verdictBadge(res.verdict)}
          </div>
          {res.error ? (
            <div style={{ color: '#ef4444', fontSize: 12 }}>{res.error}</div>
          ) : (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
              <div style={{ fontSize: 12, color: C.muted }}>
                <div>Demographic Parity Diff: <b style={{ color: Math.abs(res.demographic_parity_difference) > 0.1 ? '#ef4444' : '#10b981' }}>{res.demographic_parity_difference?.toFixed(4)}</b></div>
                <div>Equalized Odds Diff: <b style={{ color: Math.abs(res.equalized_odds_difference) > 0.1 ? '#ef4444' : '#10b981' }}>{res.equalized_odds_difference?.toFixed(4)}</b></div>
                <div style={{ marginTop: 4, fontSize: 11, color: C.hint }}>Threshold: |value| &lt; 0.1 = fair</div>
              </div>
              <div style={{ fontSize: 12, color: C.muted }}>
                <div style={{ fontWeight: 600, marginBottom: 4 }}>Accuracy by group:</div>
                {Object.entries(res.accuracy_by_group || {}).map(([g, v]) => (
                  <div key={g}>{g}: <b>{(v * 100).toFixed(1)}%</b></div>
                ))}
              </div>
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

function DriftResults({ data }) {
  if (!data) return <div style={{ color: C.muted, fontSize: 13 }}>No drift results yet.</div>
  if (data.error) return <div style={{ color: '#ef4444', fontSize: 13 }}>{data.error}</div>
  return (
    <div>
      <div style={{ display: 'flex', gap: 14, marginBottom: 16, flexWrap: 'wrap' }}>
        <StatCard label="Drifted Features" value={data.drifted_features} color={data.drifted_features > 0 ? '#f59e0b' : '#10b981'} />
        <StatCard label="Total Features"   value={data.total_features}   color={C.teal} />
        <StatCard label="Drift Rate"       value={data.drift_rate !== undefined ? `${(data.drift_rate * 100).toFixed(0)}%` : '—'} color={data.drifted_features > 0 ? '#f59e0b' : C.teal} />
      </div>
      <div style={{ background: C.bg, border: `1px solid ${C.border}`, borderRadius: 8, overflow: 'hidden' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
          <thead>
            <tr style={{ borderBottom: `1px solid ${C.border}` }}>
              {['Feature', 'Test', 'p-value', 'Statistic', 'Severity', 'Status'].map(h => (
                <th key={h} style={{ padding: '8px 12px', textAlign: 'left', color: C.hint, fontWeight: 600, fontSize: 11 }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {Object.entries(data.features || {}).map(([col, r]) => (
              <tr key={col} style={{ borderBottom: `1px solid ${C.border}` }}>
                <td style={{ padding: '7px 12px', color: C.primary }}>{col}</td>
                <td style={{ padding: '7px 12px', color: C.muted }}>{r.test?.toUpperCase()}</td>
                <td style={{ padding: '7px 12px', color: r.drifted ? '#f59e0b' : '#10b981', fontFamily: 'monospace' }}>{r.p_value}</td>
                <td style={{ padding: '7px 12px', color: C.muted, fontFamily: 'monospace' }}>{r.statistic}</td>
                <td style={{ padding: '7px 12px' }}>
                  <Pill label={r.severity || 'low'} color={r.severity === 'high' ? '#ef4444' : r.severity === 'medium' ? '#f59e0b' : '#10b981'} />
                </td>
                <td style={{ padding: '7px 12px' }}>{r.drifted ? <Pill label="DRIFTED" color="#f59e0b" /> : <Pill label="STABLE" color="#10b981" />}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function ShapResults({ data }) {
  if (!data) return <div style={{ color: C.muted, fontSize: 13 }}>No SHAP results yet.</div>
  if (data.error) return <div style={{ color: '#ef4444', fontSize: 13 }}>{data.error}</div>
  const top = data.top_features || []
  const maxVal = top[0]?.importance || 1
  return (
    <div>
      <div style={{ marginBottom: 12, fontSize: 12, color: C.muted }}>
        Method: <b>{data.method}</b> · Samples: <b>{data.n_samples}</b> · Most important: <b style={{ color: C.teal }}>{data.most_important}</b>
      </div>
      {top.map(({ feature, importance }) => (
        <div key={feature} style={{ marginBottom: 10 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4, fontSize: 13 }}>
            <span style={{ color: C.primary, fontWeight: 500 }}>{feature}</span>
            <span style={{ color: C.muted, fontFamily: 'monospace', fontSize: 12 }}>{importance.toFixed(5)}</span>
          </div>
          <div style={{ height: 8, background: C.panel, borderRadius: 4, overflow: 'hidden' }}>
            <div style={{ height: '100%', width: `${(importance / maxVal) * 100}%`, background: `linear-gradient(90deg, ${C.teal}, #0d9488)`, borderRadius: 4 }} />
          </div>
        </div>
      ))}
    </div>
  )
}

// ── Full Scan Tabs (bias + drift + shap in one pane) ───────────────────────────
function ScanResultTabs({ lastScan, scanning, scanLines, liveResults }) {
  const [activeTab, setTab] = useState('bias')

  // Use live results from current scan, fall back to last saved scan
  const bias  = liveResults?.bias  || lastScan?.bias_results
  const drift = liveResults?.drift || lastScan?.drift_results
  const shap  = liveResults?.shap  || lastScan?.shap_results

  const hasPrevScan = lastScan?.status === 'completed'
  const tabs = [
    { id: 'bias',  label: 'Bias Detection',  hasData: !!bias },
    { id: 'drift', label: 'Drift Detection', hasData: !!drift },
    { id: 'shap',  label: 'Explainability',  hasData: !!shap },
  ]

  return (
    <div>
      {/* Scan progress log */}
      {scanLines.length > 0 && (
        <div style={{ background: C.bg, border: `1px solid ${C.border}`, borderRadius: 8, padding: '10px 14px', marginBottom: 16, maxHeight: 140, overflowY: 'auto', fontFamily: 'monospace', fontSize: 12 }}>
          {scanLines.map((l, i) => (
            <div key={i} style={{ display: 'flex', gap: 7, marginBottom: 4, color: l.event === 'error' ? '#ef4444' : C.muted }}>
              <Activity size={12} style={{ flexShrink: 0, marginTop: 2 }} />
              <span>{l.message || l.event}</span>
            </div>
          ))}
        </div>
      )}

      {/* Show previous scan info if applicable */}
      {hasPrevScan && !scanning && (
        <div style={{ marginBottom: 12, fontSize: 12, color: C.hint, display: 'flex', alignItems: 'center', gap: 6 }}>
          <CheckCircle size={12} color="#10b981" />
          Last scan: {lastScan.completed_at ? new Date(lastScan.completed_at).toLocaleString() : 'completed'} · Run scan again to refresh results
        </div>
      )}

      {/* No results yet */}
      {!bias && !drift && !shap && !scanning && (
        <div style={{
          background: C.bg, border: `1px dashed ${C.border}`, borderRadius: 10,
          padding: '32px 20px', textAlign: 'center', color: C.hint,
        }}>
          <AlertCircle size={28} style={{ marginBottom: 10 }} />
          <div style={{ fontWeight: 600, color: C.muted, marginBottom: 6 }}>No scan results yet</div>
          <div style={{ fontSize: 13 }}>Click <b style={{ color: C.teal }}>Run Scan</b> above to analyse this model for bias, data drift, and feature importance.</div>
        </div>
      )}

      {/* Tabs */}
      {(bias || drift || shap) && (
        <div>
          <div style={{ display: 'flex', gap: 4, marginBottom: 16, borderBottom: `1px solid ${C.border}`, paddingBottom: 0 }}>
            {tabs.map(t => (
              <button key={t.id} onClick={() => setTab(t.id)} style={{
                padding: '8px 16px', borderRadius: '7px 7px 0 0', border: 'none',
                borderBottom: activeTab === t.id ? `2px solid ${C.teal}` : '2px solid transparent',
                background: activeTab === t.id ? C.tealSoft : 'transparent',
                color: activeTab === t.id ? C.teal : C.muted,
                fontSize: 13, fontWeight: 600, cursor: 'pointer',
                display: 'flex', alignItems: 'center', gap: 6,
              }}>
                {t.label}
                {t.hasData && <span style={{ width: 6, height: 6, borderRadius: '50%', background: C.teal, display: 'inline-block' }} />}
              </button>
            ))}
          </div>
          <div style={{ paddingTop: 4 }}>
            {activeTab === 'bias'  && <BiasResults  data={bias} />}
            {activeTab === 'drift' && <DriftResults data={drift} />}
            {activeTab === 'shap'  && <ShapResults  data={shap} />}
          </div>
        </div>
      )}
    </div>
  )
}

// ── Model Card ─────────────────────────────────────────────────────────────────
function ModelCard({ registryModel, config, lastScan, onConfigure, onDelete, onScanComplete }) {
  const [expanded, setExpanded]   = useState(false)
  const [scanning, setScanning]   = useState(false)
  const [scanLines, setScanLines] = useState([])
  const [liveResults, setLive]    = useState(null)

  const latestV       = registryModel?.latest_versions?.[0]
  const hasScanData   = lastScan?.status === 'completed'
  const biasBadge     = hasScanData ? lastScan.bias_results?.overall_verdict : null
  const driftBadge    = hasScanData ? lastScan.drift_results?.verdict : null

  const runScan = async () => {
    setScanLines([]); setLive(null); setScanning(true); setExpanded(true)
    try {
      const res = await fetch(getMlScanStream(config.id), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...getAuthHeader() },
      })
      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buf = ''
      while (true) {
        const { value, done } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        const parts = buf.split('\n\n')
        buf = parts.pop()
        for (const part of parts) {
          const line = part.replace(/^data: /, '').trim()
          if (!line) continue
          try {
            const msg = JSON.parse(line)
            setScanLines(l => [...l, msg])
            if (msg.event === 'completed') {
              setLive(msg)
              onScanComplete?.()
            }
          } catch { /* skip */ }
        }
      }
    } catch (e) {
      setScanLines(l => [...l, { event: 'error', message: e.message }])
    } finally {
      setScanning(false)
    }
  }

  return (
    <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 12, overflow: 'hidden' }}>
      {/* Card header */}
      <div style={{ padding: '16px 18px' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 10 }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
              <Brain size={16} color={C.teal} />
              <span style={{ fontWeight: 700, fontSize: 14, color: C.primary }}>{registryModel?.name || config?.name || 'Unnamed Model'}</span>
              {(latestV || config) && <Pill label={`v${latestV?.version || config?.mlflow_version || '1'}`} color="#8b5cf6" />}
              {(latestV || config) && <Pill label={latestV?.stage || config?.mlflow_stage || 'None'} color={stageColor(latestV?.stage || config?.mlflow_stage || 'None')} />}
              {/* Last scan badges */}
              {biasBadge  && verdictBadge(biasBadge)}
              {driftBadge && driftBadge !== 'stable' && verdictBadge(driftBadge)}
            </div>

            {(registryModel?.description || config?.description) && (
              <div style={{ fontSize: 12, color: C.muted, marginTop: 5 }}>{(registryModel?.description || config?.description || '').slice(0, 120)}</div>
            )}

            {latestV?.metrics && Object.keys(latestV.metrics).length > 0 && (
              <div style={{ display: 'flex', gap: 14, marginTop: 8, flexWrap: 'wrap' }}>
                {Object.entries(latestV.metrics).slice(0, 4).map(([k, v]) => (
                  <div key={k} style={{ fontSize: 11, color: C.muted }}>
                    {k}: <b style={{ color: C.primary }}>{typeof v === 'number' ? v.toFixed(3) : v}</b>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Action buttons */}
          <div style={{ display: 'flex', gap: 6, flexShrink: 0, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
            {config && (
              <>
                <button onClick={runScan} disabled={scanning} style={{
                  display: 'flex', alignItems: 'center', gap: 5,
                  padding: '6px 14px', borderRadius: 7, border: 'none',
                  background: scanning ? C.panel : C.teal,
                  color: scanning ? C.muted : '#fff',
                  fontSize: 12, fontWeight: 600, cursor: scanning ? 'not-allowed' : 'pointer',
                }}>
                  {scanning ? <><Loader size={12} className="spin" /> Running…</> : <><Play size={12} /> Run Scan</>}
                </button>
                <button onClick={() => setExpanded(e => !e)} style={{
                  display: 'flex', alignItems: 'center', gap: 4,
                  padding: '6px 10px', borderRadius: 7, border: `1px solid ${C.border}`,
                  background: expanded ? C.tealSoft : 'transparent',
                  color: expanded ? C.teal : C.muted,
                  fontSize: 12, cursor: 'pointer',
                }}>
                  {hasScanData || liveResults ? 'Results' : 'Details'}
                  {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                </button>
              </>
            )}
            <button onClick={() => onConfigure(registryModel)} style={{
              display: 'flex', alignItems: 'center', gap: 5,
              padding: '6px 12px', borderRadius: 7, border: `1px solid ${C.border}`,
              background: 'transparent', color: C.muted, fontSize: 12, cursor: 'pointer',
            }}>
              <Settings size={12} /> {config ? 'Edit' : 'Configure'}
            </button>
            {config && (
              <button onClick={() => onDelete(config.id)} style={{
                padding: '6px 8px', borderRadius: 7, border: `1px solid ${C.border}`,
                background: 'transparent', color: '#ef4444', cursor: 'pointer', display: 'flex',
              }}>
                <Trash2 size={13} />
              </button>
            )}
          </div>
        </div>

        {/* Config summary row */}
        <div style={{ display: 'flex', gap: 10, marginTop: 10, flexWrap: 'wrap', alignItems: 'center' }}>
          {!config ? (
            <span style={{ fontSize: 12, color: C.hint, fontStyle: 'italic' }}>
              Not configured — click <b style={{ color: C.teal }}>Configure</b> to enable governance scans
            </span>
          ) : (
            <>
              <span style={{ fontSize: 11, color: C.hint }}>Table: <b style={{ color: C.muted }}>{config.target_table || '—'}</b></span>
              <span style={{ fontSize: 11, color: C.hint }}>Target: <b style={{ color: C.muted }}>{config.target_column || '—'}</b></span>
              <span style={{ fontSize: 11, color: C.hint }}>v{config.mlflow_version || '?'}</span>
              {config.protected_attrs?.length > 0 && (
                <span style={{ fontSize: 11, color: C.hint }}>Protected: <b style={{ color: C.muted }}>{config.protected_attrs.join(', ')}</b></span>
              )}
            </>
          )}
        </div>
      </div>

      {/* Expanded scan results */}
      {expanded && config && (
        <div style={{ borderTop: `1px solid ${C.border}`, padding: '18px 18px', background: C.bg }}>
          <ScanResultTabs
            lastScan={lastScan}
            scanning={scanning}
            scanLines={scanLines}
            liveResults={liveResults}
          />
        </div>
      )}
    </div>
  )
}

// ── Main Page ──────────────────────────────────────────────────────────────────
export default function MlGovernance() {
  const [connection, setConnection]     = useState(null)
  const [registry, setRegistry]         = useState([])
  const [configs, setConfigs]           = useState([])
  const [lastScans, setLastScans]       = useState({})   // modelId -> scan
  const [summary, setSummary]           = useState(null)
  const [loading, setLoading]           = useState(true)
  const [refreshing, setRefreshing]     = useState(false)
  const [syncing, setSyncing]           = useState(false)
  const [configModal, setConfigModal]   = useState(null)
  const [trainModal, setTrainModal]     = useState(false)

  // Load last scan for every configured model
  const loadScans = async (cfgs) => {
    const scanMap = {}
    await Promise.all(cfgs.map(async c => {
      try {
        const scans = await getMlScans(c.id)
        const done  = (scans || []).find(s => s.status === 'completed')
        if (done) scanMap[c.id] = done
      } catch { /* ignore */ }
    }))
    setLastScans(scanMap)
  }

  const loadAll = useCallback(async () => {
    try {
      const [conns, cfgs, sum] = await Promise.all([
        getMlflowConnection().catch(() => []),
        getMlModels().catch(() => []),
        getMlSummary().catch(() => null),
      ])
      const active = (Array.isArray(conns) ? conns : []).find(c => c.status === 'connected') || (Array.isArray(conns) ? conns[0] : null) || null
      setConnection(active)
      const validCfgs = Array.isArray(cfgs) ? cfgs : []
      setConfigs(validCfgs)
      setSummary(sum)
      await loadScans(validCfgs)

      if (active?.status === 'connected') {
        const reg = await getMlflowRegistry().catch(() => [])
        setRegistry(Array.isArray(reg) ? reg : [])
      } else {
        setRegistry([])
      }
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { loadAll() }, [loadAll])

  const handleConnect = async (url) => {
    const conn = await connectMlflow({ url })
    setConnection(conn)
    if (conn.status === 'connected') {
      const reg = await getMlflowRegistry().catch(() => [])
      setRegistry(Array.isArray(reg) ? reg : [])
    }
  }

  const handleDisconnect = async (id) => {
    await disconnectMlflow(id)
    setConnection(null)
    setRegistry([])
  }

  const handleSaveConfig = async (payload) => {
    const existing = configs.find(c => c.mlflow_model_name === payload.mlflow_model_name)
    let configObj
    if (existing) {
      configObj = await updateMlModel(existing.id, payload)
    } else {
      configObj = await createMlModel(payload)
    }
    const newCfgs = [...configs.filter(c => c.mlflow_model_name !== payload.mlflow_model_name), configObj]
    setConfigs(newCfgs)
    await loadScans(newCfgs)
  }

  const handleDeleteConfig = async (id) => {
    if (!confirm('Remove governance configuration and delete registered model from MLflow?')) return
    await deleteMlModel(id)
    await loadAll()
  }

  const handleSyncAndScan = async () => {
    setSyncing(true)
    try {
      await syncMlflowModels()
      await new Promise(resolve => setTimeout(resolve, 1500))
      await loadAll()
    } catch (e) {
      alert("Error starting sync: " + e.message)
    } finally {
      setSyncing(false)
    }
  }

  const handleRefresh = async () => {
    setRefreshing(true)
    try {
      const reg = await getMlflowRegistry().catch(() => [])
      setRegistry(Array.isArray(reg) ? reg : [])
    } finally {
      setRefreshing(false)
    }
  }

  const handleTrainModel = async (payload) => {
    await trainAndRegisterMlModel(payload)
    await loadAll()
  }

  const configFor   = name => configs.find(c => c.mlflow_model_name === name) || null
  const lastScanFor = name => { const cfg = configFor(name); return cfg ? lastScans[cfg.id] || null : null }

  if (loading) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '60vh', color: C.muted, gap: 10 }}>
        <Loader size={20} className="spin" /> Loading ML Governance…
      </div>
    )
  }

  const connected = connection?.status === 'connected'

  // Get all unique model names from registry and configs
  const allModelNames = Array.from(new Set([
    ...registry.map(m => m.name),
    ...configs.map(c => c.mlflow_model_name)
  ].filter(Boolean)))

  const getRegistryModel = (name) => {
    return registry.find(m => m.name === name) || {
      name: name,
      description: 'Custom configured model (not found in live MLflow registry)',
      latest_versions: [],
      mlflow_url: connection?.url
    }
  }

  return (
    <div style={{ padding: '32px 36px', maxWidth: 1100, margin: '0 auto' }}>
      {/* Header */}
      <div style={{ marginBottom: 28 }}>
        <h1 style={{ fontSize: 24, fontWeight: 700, color: C.primary, margin: 0 }}>ML Governance</h1>
        <p style={{ fontSize: 13, color: C.muted, marginTop: 4 }}>
          Connect MLflow → Browse models → Configure → Run Scan → View Bias / Drift / Explainability
        </p>
      </div>

      {/* Summary stats */}
      {summary && (
        <div style={{ display: 'flex', gap: 12, marginBottom: 28, flexWrap: 'wrap' }}>
          <StatCard label="Registry Models"  value={registry.length}           color={C.teal} />
          <StatCard label="Configured"       value={summary.configured_models} color="#8b5cf6" />
          <StatCard label="Scans Run"        value={summary.total_scans}       color="#f59e0b" />
          <StatCard label="Bias Issues"      value={summary.high_bias_count}   color={summary.high_bias_count  > 0 ? '#ef4444' : '#10b981'} />
          <StatCard label="Drift Detected"   value={summary.high_drift_count}  color={summary.high_drift_count > 0 ? '#f59e0b' : '#10b981'} />
        </div>
      )}

      {/* Connection panel */}
      <ConnectionPanel
        connection={connection}
        onConnect={handleConnect}
        onDisconnect={handleDisconnect}
        registryCount={registry.length}
      />

      {/* Step guide when connected but no configs yet */}
      {connected && registry.length > 0 && configs.length === 0 && (
        <div style={{
          background: C.surface, border: `1px solid ${C.border}`, borderRadius: 12,
          padding: '20px 24px', marginBottom: 24,
          display: 'flex', gap: 0, overflow: 'hidden',
        }}>
          {[
            { n: '1', label: 'Connect MLflow', done: true,  desc: 'Server connected ✓' },
            { n: '2', label: 'Configure Model', done: false, desc: 'Click Configure on any card' },
            { n: '3', label: 'Run Scan',        done: false, desc: 'Click Run Scan on the card' },
            { n: '4', label: 'View Results',    done: false, desc: 'Bias · Drift · Explainability' },
          ].map((step, i, arr) => (
            <div key={step.n} style={{ flex: 1, display: 'flex', alignItems: 'center', gap: 0 }}>
              <div style={{ flex: 1 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <div style={{
                    width: 28, height: 28, borderRadius: '50%', flexShrink: 0,
                    background: step.done ? C.teal : C.panel,
                    color: step.done ? '#fff' : C.hint,
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    fontSize: 13, fontWeight: 700,
                  }}>{step.done ? '✓' : step.n}</div>
                  <div>
                    <div style={{ fontSize: 13, fontWeight: 600, color: step.done ? C.teal : C.primary }}>{step.label}</div>
                    <div style={{ fontSize: 11, color: C.hint }}>{step.desc}</div>
                  </div>
                </div>
              </div>
              {i < arr.length - 1 && (
                <div style={{ width: 40, height: 1, background: C.border, flexShrink: 0 }} />
              )}
            </div>
          ))}
        </div>
      )}

      {/* Model registry grid */}
      {connected && (
        <Section title={`Model Registry (${registry.length})`}>
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10, marginBottom: 12 }}>
            <button onClick={handleSyncAndScan} disabled={syncing} style={{
              display: 'flex', alignItems: 'center', gap: 6,
              padding: '7px 14px', borderRadius: 8, border: `1px solid ${C.border}`,
              background: syncing ? C.panel : C.tealSoft, color: C.teal, fontSize: 12, cursor: syncing ? 'not-allowed' : 'pointer',
              fontWeight: 600,
            }}>
              <RefreshCw size={13} className={syncing ? 'spin' : ''} /> {syncing ? 'Syncing & Auto-Scanning...' : 'Sync & Auto-Scan Models'}
            </button>
            <button onClick={handleRefresh} disabled={refreshing} style={{
              display: 'flex', alignItems: 'center', gap: 6,
              padding: '7px 14px', borderRadius: 8, border: `1px solid ${C.border}`,
              background: 'transparent', color: C.muted, fontSize: 12, cursor: 'pointer',
            }}>
              <RefreshCw size={13} className={refreshing ? 'spin' : ''} /> Refresh
            </button>
            <button onClick={() => setTrainModal(true)} style={{
              display: 'flex', alignItems: 'center', gap: 6,
              padding: '7px 14px', borderRadius: 8, border: 'none',
              background: C.teal, color: '#fff', fontSize: 12, cursor: 'pointer',
              fontWeight: 600,
            }}>
              <Brain size={13} /> Train &amp; Register Model
            </button>
          </div>

          {allModelNames.length === 0 ? (
            <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 12, padding: '48px 24px', textAlign: 'center', color: C.muted }}>
              <Brain size={32} color={C.hint} style={{ marginBottom: 12 }} />
              <div style={{ fontWeight: 600, marginBottom: 6, color: C.primary }}>No registered models found</div>
              <div style={{ fontSize: 13 }}>Register models in your MLflow server to see them here.</div>
            </div>
          ) : (
            <div style={{ display: 'grid', gap: 14 }}>
              {allModelNames.map(name => (
                <ModelCard
                  key={name}
                  registryModel={getRegistryModel(name)}
                  config={configFor(name)}
                  lastScan={lastScanFor(name)}
                  onConfigure={rm => setConfigModal(rm)}
                  onDelete={handleDeleteConfig}
                  onScanComplete={loadAll}
                />
              ))}
            </div>
          )}
        </Section>
      )}

      {/* Not-connected placeholder */}
      {!connected && (
        <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 12, padding: '56px 24px', textAlign: 'center', color: C.muted }}>
          <FlaskConical size={40} color={C.hint} style={{ marginBottom: 14 }} />
          <div style={{ fontWeight: 700, fontSize: 16, color: C.primary, marginBottom: 8 }}>Connect your MLflow server</div>
          <div style={{ fontSize: 13, maxWidth: 380, margin: '0 auto', lineHeight: 1.7 }}>
            Enter your MLflow tracking server URL above to browse registered models and run governance scans.
            <br /><br />
            Start MLflow: <code style={{ background: C.panel, padding: '2px 6px', borderRadius: 4, fontSize: 12 }}>mlflow server --port 5000</code>
          </div>
        </div>
      )}

      {/* Configure modal */}
      {configModal && (
        <ConfigureModal
          registryModel={configModal}
          existingConfig={configFor(configModal.name)}
          onSave={handleSaveConfig}
          onClose={() => setConfigModal(null)}
        />
      )}

      {/* Train & Register modal */}
      {trainModal && (
        <TrainRegisterModal
          onSave={handleTrainModel}
          onClose={() => setTrainModal(false)}
        />
      )}

      <style>{`
        @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
        .spin { animation: spin 1s linear infinite; }
      `}</style>
    </div>
  )
}
