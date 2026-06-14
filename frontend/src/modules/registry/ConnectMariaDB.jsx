import { useState, useEffect } from 'react'
import ReactDOM from 'react-dom'
import { Plug, X, Eye, EyeOff, Loader, AlertCircle } from 'lucide-react'
import { createIntegration } from '../../core/api.js'

const MARIADB_TEMPLATE_ID = 'mariadb-builtin'

const SSL_OPTIONS = [
  { value: 'disable',     label: 'disable — no SSL' },
  { value: 'require',     label: 'require — SSL, no cert verify' },
  { value: 'verify-ca',   label: 'verify-ca — verify server cert' },
  { value: 'verify-full', label: 'verify-full — verify cert + hostname' },
]

function Field({ label, required, error, children }) {
  return (
    <div style={{ marginBottom: 18 }}>
      <label style={{ display: 'block', fontSize: 13, fontWeight: 600, color: 'var(--text-secondary)', marginBottom: 6 }}>
        {label}
        {required && <span style={{ color: 'var(--danger)', marginLeft: 3 }}>*</span>}
      </label>
      {children}
      {error && (
        <p style={{ marginTop: 6, fontSize: 12, color: 'var(--danger)', fontWeight: 500 }}>{error}</p>
      )}
    </div>
  )
}

function Input({ value, onChange, onBlur, type = 'text', placeholder, disabled, suffix, error }) {
  const [focused, setFocused] = useState(false)
  return (
    <div style={{ position: 'relative' }}>
      <input
        type={type}
        value={value}
        onChange={onChange}
        onBlur={() => { setFocused(false); onBlur?.() }}
        onFocus={() => setFocused(true)}
        placeholder={placeholder}
        disabled={disabled}
        style={{
          width: '100%',
          padding: suffix ? '11px 44px 11px 14px' : '11px 14px',
          background: 'var(--bg-base)',
          border: `1px solid ${error ? 'var(--danger)' : focused ? 'var(--accent-teal)' : 'var(--border)'}`,
          borderRadius: 8,
          fontSize: 14,
          color: 'var(--text-primary)',
          fontFamily: 'inherit',
          outline: 'none',
          boxSizing: 'border-box',
          transition: 'all 0.15s ease',
          opacity: disabled ? 0.6 : 1,
          boxShadow: focused ? '0 0 0 3px var(--accent-teal-soft)' : 'none',
        }}
      />
      {suffix && (
        <div style={{
          position: 'absolute', right: 14, top: '50%', transform: 'translateY(-50%)',
          color: 'var(--text-hint)', cursor: 'pointer', display: 'flex',
        }}>
          {suffix}
        </div>
      )}
    </div>
  )
}

function SelectInput({ value, onChange, disabled, options }) {
  const [focused, setFocused] = useState(false)
  return (
    <select
      value={value}
      onChange={onChange}
      disabled={disabled}
      onFocus={() => setFocused(true)}
      onBlur={() => setFocused(false)}
      style={{
        width: '100%',
        padding: '11px 14px',
        background: 'var(--bg-base)',
        border: `1px solid ${focused ? 'var(--accent-teal)' : 'var(--border)'}`,
        borderRadius: 8,
        fontSize: 14,
        color: 'var(--text-primary)',
        fontFamily: 'inherit',
        outline: 'none',
        cursor: 'pointer',
        appearance: 'auto',
        opacity: disabled ? 0.6 : 1,
        transition: 'all 0.15s ease',
        boxShadow: focused ? '0 0 0 3px var(--accent-teal-soft)' : 'none',
      }}
    >
      {options.map(o => (
        <option key={o.value} value={o.value}>{o.label}</option>
      ))}
    </select>
  )
}

// ── Main modal ────────────────────────────────────────────────────────────────
export default function ConnectMariaDB({ isOpen, onClose, onSuccess }) {
  const [form, setForm] = useState({ host: '', port: '3306', database: '', username: '', password: '', ssl: 'disable' })
  const [errors, setErrors] = useState({})
  const [showPass, setShowPass] = useState(false)
  const [loading, setLoading] = useState(false)
  const [apiError, setApiError] = useState(null)

  useEffect(() => {
    if (isOpen) {
      setForm({ host: '', port: '3306', database: '', username: '', password: '', ssl: 'disable' })
      setErrors({})
      setApiError(null)
      setLoading(false)
    }
  }, [isOpen])

  if (!isOpen) return null

  const validate = (fields = form) => {
    const errs = {}
    if (!fields.host.trim())     errs.host     = 'Required field'
    if (!fields.port)            errs.port     = 'Required field'
    else if (isNaN(Number(fields.port)) || Number(fields.port) < 1 || Number(fields.port) > 65535)
                                 errs.port     = 'Must be 1-65535'
    if (!fields.database.trim()) errs.database = 'Required field'
    if (!fields.username.trim()) errs.username = 'Required field'
    if (!fields.password)        errs.password = 'Required field'
    return errs
  }

  const blurField = (key) => {
    const errs = validate()
    setErrors(prev => ({ ...prev, [key]: errs[key] }))
  }

  const handleSubmit = async () => {
    const errs = validate()
    setErrors(errs)
    if (Object.keys(errs).length > 0) return

    setLoading(true)
    setApiError(null)
    try {
      const result = await createIntegration({
        template_id: MARIADB_TEMPLATE_ID,
        name: `MariaDB — ${form.database}@${form.host}`,
        credentials: {
          host:     form.host,
          port:     Number(form.port),
          user:     form.username,
          password: form.password,
          database: form.database,
          ssl:      form.ssl,
        },
      })
      onSuccess?.(result)
      onClose()
    } catch (e) {
      setApiError(e.message)
    } finally {
      setLoading(false)
    }
  }

  const set = (key) => (e) => setForm(p => ({ ...p, [key]: e.target.value }))

  const modal = (
    <div
      onClick={e => { if (e.target === e.currentTarget && !loading) onClose() }}
      style={{
        position: 'fixed', inset: 0, zIndex: 2000,
        background: 'rgba(15, 23, 42, 0.4)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        padding: 20,
        backdropFilter: 'blur(4px)',
      }}
    >
      <div
        className="fade-up"
        style={{
          background: 'var(--bg-surface)',
          borderRadius: 14,
          width: '100%',
          maxWidth: 480,
          maxHeight: '94vh',
          display: 'flex',
          flexDirection: 'column',
          boxShadow: 'var(--shadow-lg)',
          fontFamily: 'var(--font-body)',
          overflow: 'hidden'
        }}
      >
        {/* ── Header ── */}
        <div style={{
          padding: '24px 28px 20px',
          borderBottom: '1px solid var(--border)',
          display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between',
        }}>
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: 14 }}>
            <div style={{
              width: 44, height: 44, borderRadius: 10, flexShrink: 0,
              background: '#f0f9ff',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              overflow: 'hidden',
              border: '1px solid #e0f2fe',
            }}>
              <img
                src="https://mariadb.com/wp-content/uploads/2019/11/mariadb-logo-vert_blue-transparent.png"
                alt="MariaDB"
                style={{ width: 30, height: 30, objectFit: 'contain' }}
                onError={e => {
                  e.target.style.display = 'none'
                  e.target.parentNode.innerHTML = '<span style="font-family:var(--font-display);font-size:22px;font-weight:400;color:#0369a1">M</span>'
                }}
              />
            </div>
            <div>
              <div style={{ 
                fontFamily: 'var(--font-display)', 
                fontWeight: 400, 
                fontSize: 22, 
                color: 'var(--text-primary)', 
                lineHeight: 1.1,
                letterSpacing: '-0.3px'
              }}>
                Connect MariaDB
              </div>
              <div style={{ fontSize: 13, color: 'var(--text-hint)', marginTop: 4, fontWeight: 500 }}>Database Connector</div>
            </div>
          </div>
          <button
            onClick={onClose}
            disabled={loading}
            style={{
              background: 'var(--bg-panel)', border: '1px solid var(--border)', cursor: loading ? 'not-allowed' : 'pointer',
              color: 'var(--text-muted)', padding: 6, borderRadius: 8, display: 'flex',
              opacity: loading ? 0.5 : 1,
            }}
          >
            <X size={16} />
          </button>
        </div>

        {/* ── Body ── */}
        <div style={{ padding: '28px', overflowY: 'auto' }}>
          {apiError && (
            <div style={{
              display: 'flex', gap: 12, alignItems: 'flex-start',
              background: 'var(--danger-bg)', border: '1px solid var(--danger-border)',
              borderRadius: 10, padding: '14px 16px', marginBottom: 24,
            }}>
              <AlertCircle size={16} color="var(--danger)" style={{ flexShrink: 0, marginTop: 1 }} />
              <span style={{ fontSize: 13, color: 'var(--danger)', lineHeight: 1.5, fontWeight: 500 }}>
                Verification failed: {apiError}
              </span>
            </div>
          )}

          <div style={{ display: 'flex', gap: 20 }}>
            <div style={{ flex: 1 }}>
                <Field label="Host" required error={errors.host}>
                    <Input
                    value={form.host}
                    onChange={set('host')}
                    onBlur={() => blurField('host')}
                    placeholder="e.g. localhost"
                    disabled={loading}
                    error={errors.host}
                    />
                </Field>
            </div>
            <div style={{ width: 100 }}>
                <Field label="Port" required error={errors.port}>
                    <Input
                    value={form.port}
                    onChange={set('port')}
                    onBlur={() => blurField('port')}
                    type="number"
                    placeholder="3306"
                    disabled={loading}
                    error={errors.port}
                    />
                </Field>
            </div>
          </div>

          <Field label="Database Name" required error={errors.database}>
            <Input
              value={form.database}
              onChange={set('database')}
              onBlur={() => blurField('database')}
              placeholder="e.g. governance_db"
              disabled={loading}
              error={errors.database}
            />
          </Field>

          <div style={{ display: 'flex', gap: 20 }}>
            <Field label="Username" required error={errors.username}>
                <Input
                value={form.username}
                onChange={set('username')}
                onBlur={() => blurField('username')}
                placeholder="root"
                disabled={loading}
                error={errors.username}
                />
            </Field>

            <Field label="Password" required error={errors.password}>
                <Input
                value={form.password}
                onChange={set('password')}
                onBlur={() => blurField('password')}
                type={showPass ? 'text' : 'password'}
                placeholder="••••••••"
                disabled={loading}
                error={errors.password}
                suffix={
                    <span onClick={() => setShowPass(p => !p)} style={{ cursor: 'pointer', padding: 4 }}>
                    {showPass ? <EyeOff size={15} /> : <Eye size={15} />}
                    </span>
                }
                />
            </Field>
          </div>

          <Field label="SSL Lifecycle" required={false} error={null}>
            <SelectInput
              value={form.ssl}
              onChange={set('ssl')}
              disabled={loading}
              options={SSL_OPTIONS}
            />
          </Field>

          {/* ── Footer buttons ── */}
          <div style={{ display: 'flex', gap: 12, marginTop: 12 }}>
            <button
              onClick={handleSubmit}
              disabled={loading}
              style={{
                flex: 1,
                background: 'var(--accent-teal)',
                color: 'var(--text-inverse)',
                border: 'none',
                borderRadius: 10,
                padding: '12px 24px',
                fontSize: 14,
                fontWeight: 700,
                cursor: loading ? 'not-allowed' : 'pointer',
                fontFamily: 'inherit',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: 10,
                transition: 'all 0.2s ease',
                boxShadow: '0 2px 8px rgba(20, 184, 166, 0.2)',
              }}
              onMouseEnter={e => { if (!loading) e.currentTarget.style.background = 'var(--accent-teal-hover)' }}
              onMouseLeave={e => { if (!loading) e.currentTarget.style.background = 'var(--accent-teal)' }}
            >
              {loading
                ? <><Loader size={16} className="spin" /> Verifying Connection…</>
                : <><Plug size={16} strokeWidth={2.5} /> Establish Secure Connection</>
              }
            </button>
            <button
              onClick={onClose}
              disabled={loading}
              style={{
                background: 'transparent',
                border: '1px solid var(--border)',
                color: 'var(--text-muted)',
                fontSize: 14,
                fontWeight: 600,
                cursor: loading ? 'not-allowed' : 'pointer',
                fontFamily: 'inherit',
                padding: '12px 20px',
                borderRadius: 10,
                opacity: loading ? 0.5 : 1,
                transition: 'all 0.15s ease'
              }}
              onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-panel)'}
              onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
            >
              Cancel
            </button>
          </div>
        </div>
      </div>
    </div>
  )

  return ReactDOM.createPortal(modal, document.body)
}
