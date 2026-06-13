import { useState } from 'react'
import { Shield, Eye, EyeOff, Loader } from 'lucide-react'
import { useAuth } from '../context/AuthContext.jsx'

export default function Login({ onRegisterMode }) {
  const { login, register } = useAuth()

  const [mode,     setMode]     = useState('login')   // 'login' | 'register'
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [email,    setEmail]    = useState('')
  const [fullName, setFullName] = useState('')
  const [showPw,   setShowPw]   = useState(false)
  const [loading,  setLoading]  = useState(false)
  const [error,    setError]    = useState('')
  const [success,  setSuccess]  = useState('')

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    setSuccess('')
    if (!username.trim() || !password.trim()) {
      setError('Username and password are required.')
      return
    }
    setLoading(true)
    try {
      if (mode === 'login') {
        await login(username.trim(), password)
      } else {
        await register(username.trim(), password, email.trim() || undefined, fullName.trim() || undefined)
        setSuccess('Account created — signing you in…')
        await login(username.trim(), password)
      }
    } catch (err) {
      setError(err.message || 'Something went wrong')
    } finally {
      setLoading(false)
    }
  }

  const inputStyle = {
    width: '100%', boxSizing: 'border-box',
    padding: '10px 14px', borderRadius: 8, fontSize: 13,
    background: 'var(--bg-base)', color: 'var(--text-primary)',
    border: '1px solid var(--border)',
    outline: 'none', fontFamily: 'inherit',
    transition: 'border-color 0.2s',
  }

  return (
    <div style={{
      minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center',
      background: 'var(--bg-base)',
    }}>
      <div style={{
        width: '100%', maxWidth: 400,
        background: 'var(--bg-surface)', border: '1px solid var(--border)',
        borderRadius: 16, padding: '36px 32px',
        boxShadow: '0 8px 40px rgba(0,0,0,0.4)',
      }}>
        {/* Logo */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 28 }}>
          <div style={{
            width: 40, height: 40, borderRadius: 10, flexShrink: 0,
            background: 'linear-gradient(135deg, #0d9488 0%, #14b8a6 100%)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            boxShadow: '0 2px 10px rgba(20,184,166,0.3)',
          }}>
            <Shield size={18} color="#fff" strokeWidth={2.5} />
          </div>
          <div>
            <div style={{ fontFamily: 'var(--font-display)', fontSize: 22, fontWeight: 400, color: 'var(--text-primary)', letterSpacing: '-0.3px', lineHeight: 1.1 }}>DataGuard</div>
            <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--text-hint)', textTransform: 'uppercase', letterSpacing: '0.8px', marginTop: 1 }}>Governance Platform</div>
          </div>
        </div>

        <div style={{ marginBottom: 24 }}>
          <h2 style={{ fontFamily: 'var(--font-display)', fontSize: 20, fontWeight: 400, color: 'var(--text-primary)', margin: 0, letterSpacing: '-0.2px' }}>
            {mode === 'login' ? 'Sign in to your account' : 'Create an account'}
          </h2>
          <p style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 6 }}>
            {mode === 'login' ? 'Enter your credentials to access the platform.' : 'Set up your DataGuard user account.'}
          </p>
        </div>

        <form onSubmit={handleSubmit}>
          {/* Full name (register only) */}
          {mode === 'register' && (
            <div style={{ marginBottom: 14 }}>
              <label style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-hint)', display: 'block', marginBottom: 5 }}>Full Name</label>
              <input style={inputStyle} placeholder="Jane Smith" value={fullName} onChange={e => setFullName(e.target.value)}
                onFocus={e => e.target.style.borderColor = 'var(--accent-teal)'}
                onBlur={e  => e.target.style.borderColor = 'var(--border)'}
              />
            </div>
          )}

          {/* Email (register only) */}
          {mode === 'register' && (
            <div style={{ marginBottom: 14 }}>
              <label style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-hint)', display: 'block', marginBottom: 5 }}>Email <span style={{ color: 'var(--text-hint)', fontWeight: 400 }}>(optional)</span></label>
              <input style={inputStyle} type="email" placeholder="jane@company.com" value={email} onChange={e => setEmail(e.target.value)}
                onFocus={e => e.target.style.borderColor = 'var(--accent-teal)'}
                onBlur={e  => e.target.style.borderColor = 'var(--border)'}
              />
            </div>
          )}

          {/* Username */}
          <div style={{ marginBottom: 14 }}>
            <label style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-hint)', display: 'block', marginBottom: 5 }}>Username</label>
            <input style={inputStyle} autoFocus placeholder="admin" value={username} onChange={e => setUsername(e.target.value)}
              onFocus={e => e.target.style.borderColor = 'var(--accent-teal)'}
              onBlur={e  => e.target.style.borderColor = 'var(--border)'}
            />
          </div>

          {/* Password */}
          <div style={{ marginBottom: 20 }}>
            <label style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-hint)', display: 'block', marginBottom: 5 }}>Password</label>
            <div style={{ position: 'relative' }}>
              <input style={{ ...inputStyle, paddingRight: 40 }}
                type={showPw ? 'text' : 'password'}
                placeholder="••••••••"
                value={password}
                onChange={e => setPassword(e.target.value)}
                onFocus={e => e.target.style.borderColor = 'var(--accent-teal)'}
                onBlur={e  => e.target.style.borderColor = 'var(--border)'}
              />
              <button type="button" onClick={() => setShowPw(p => !p)}
                style={{ position: 'absolute', right: 12, top: '50%', transform: 'translateY(-50%)', background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-hint)', padding: 0, display: 'flex' }}>
                {showPw ? <EyeOff size={15} /> : <Eye size={15} />}
              </button>
            </div>
          </div>

          {/* Error / success */}
          {error && (
            <div style={{ background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.2)', borderRadius: 8, padding: '10px 14px', fontSize: 12, color: '#ef4444', marginBottom: 16 }}>
              {error}
            </div>
          )}
          {success && (
            <div style={{ background: 'rgba(16,185,129,0.08)', border: '1px solid rgba(16,185,129,0.2)', borderRadius: 8, padding: '10px 14px', fontSize: 12, color: '#10b981', marginBottom: 16 }}>
              {success}
            </div>
          )}

          <button type="submit" disabled={loading}
            style={{ width: '100%', padding: '11px 0', borderRadius: 8, fontSize: 13, fontWeight: 700, fontFamily: 'inherit', background: 'var(--accent-teal)', color: '#fff', border: 'none', cursor: loading ? 'not-allowed' : 'pointer', opacity: loading ? 0.75 : 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8, transition: 'opacity 0.2s' }}>
            {loading && <Loader size={14} className="spin" />}
            {mode === 'login' ? 'Sign In' : 'Create Account'}
          </button>
        </form>

        {/* Mode toggle */}
        <div style={{ marginTop: 20, textAlign: 'center', fontSize: 12, color: 'var(--text-muted)' }}>
          {mode === 'login' ? (
            <>Don't have an account?{' '}
              <button onClick={() => { setMode('register'); setError('') }}
                style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--accent-teal)', fontWeight: 600, fontSize: 12, padding: 0 }}>
                Create one
              </button>
            </>
          ) : (
            <>Already have an account?{' '}
              <button onClick={() => { setMode('login'); setError('') }}
                style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--accent-teal)', fontWeight: 600, fontSize: 12, padding: 0 }}>
                Sign in
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
