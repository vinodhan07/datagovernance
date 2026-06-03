import { useState, useEffect } from 'react'
import ReactDOM from 'react-dom'
import { GitBranch, X, Eye, EyeOff, Loader, AlertCircle, CheckCircle } from 'lucide-react'
import { createIntegration } from '../api/client.js'

const GITHUB_TEMPLATE_ID = 'github-builtin'

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

export default function ConnectGitHub({ isOpen, onClose, onSuccess }) {
  const [form, setForm] = useState({ owner: '', repo: '', filepath: '', branch: 'main', token: '' })
  const [errors, setErrors] = useState({})
  const [showPass, setShowPass] = useState(false)
  const [loading, setLoading] = useState(false)
  const [apiError, setApiError] = useState(null)

  useEffect(() => {
    if (isOpen) {
      setForm({ owner: '', repo: '', filepath: '', branch: 'main', token: '' })
      setErrors({})
      setApiError(null)
      setLoading(false)
    }
  }, [isOpen])

  if (!isOpen) return null

  const validate = (fields = form) => {
    const errs = {}
    if (!fields.owner.trim())    errs.owner    = 'Required field'
    if (!fields.repo.trim())     errs.repo     = 'Required field'
    if (!fields.filepath.trim()) errs.filepath = 'Required field'
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
        template_id: GITHUB_TEMPLATE_ID,
        name: `GitHub — ${form.owner}/${form.repo}`,
        credentials: {
          owner:    form.owner,
          repo:     form.repo,
          filepath: form.filepath,
          branch:   form.branch || 'main',
          token:    form.token,
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
        {/* Header */}
        <div style={{
          padding: '24px 28px 20px',
          borderBottom: '1px solid var(--border)',
          display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between',
        }}>
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: 14 }}>
            <div style={{
              width: 44, height: 44, borderRadius: 10, flexShrink: 0,
              background: 'var(--bg-panel)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              overflow: 'hidden',
              border: '1px solid var(--border)',
            }}>
              <img
                src="https://github.githubassets.com/images/modules/logos_page/GitHub-Mark.png"
                alt="GitHub"
                style={{ width: 28, height: 28, objectFit: 'contain', filter: 'invert(1)' }}
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
                Connect GitHub
              </div>
              <div style={{ fontSize: 13, color: 'var(--text-hint)', marginTop: 4, fontWeight: 500 }}>ETL Code Lineage Analyzer</div>
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

        {/* Body */}
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
              <Field label="Owner / Org" required error={errors.owner}>
                <Input
                  value={form.owner}
                  onChange={set('owner')}
                  onBlur={() => blurField('owner')}
                  placeholder="e.g. octocat"
                  disabled={loading}
                  error={errors.owner}
                />
              </Field>
            </div>
            <div style={{ flex: 1 }}>
              <Field label="Repository Name" required error={errors.repo}>
                <Input
                  value={form.repo}
                  onChange={set('repo')}
                  onBlur={() => blurField('repo')}
                  placeholder="e.g. hello-world"
                  disabled={loading}
                  error={errors.repo}
                />
              </Field>
            </div>
          </div>

          <Field label="ETL File Path" required error={errors.filepath}>
            <Input
              value={form.filepath}
              onChange={set('filepath')}
              onBlur={() => blurField('filepath')}
              placeholder="e.g. backend/etl/etl_pipeline.py"
              disabled={loading}
              error={errors.filepath}
            />
          </Field>

          <div style={{ display: 'flex', gap: 20 }}>
            <div style={{ flex: 1 }}>
              <Field label="Branch (Optional)" required={false} error={null}>
                <Input
                  value={form.branch}
                  onChange={set('branch')}
                  placeholder="main"
                  disabled={loading}
                />
              </Field>
            </div>
            <div style={{ flex: 1 }}>
              <Field label="Personal Token (Optional)" required={false} error={null}>
                <Input
                  value={form.token}
                  onChange={set('token')}
                  type={showPass ? 'text' : 'password'}
                  placeholder="ghp_••••••••"
                  disabled={loading}
                  suffix={
                    <span onClick={() => setShowPass(p => !p)} style={{ cursor: 'pointer', padding: 4 }}>
                      {showPass ? <EyeOff size={15} /> : <Eye size={15} />}
                    </span>
                  }
                />
              </Field>
            </div>
          </div>

          {/* Footer buttons */}
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
                ? <><Loader size={16} className="spin" /> Checking Repository…</>
                : <><GitBranch size={16} strokeWidth={2.5} /> Connect and Verify Repository</>
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
