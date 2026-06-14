import { useState, useEffect, useRef } from 'react'
import { LayoutGrid, Plug, Shield, BookOpen, ShieldCheck, Database, Brain, LogOut, User, X, CheckCircle } from 'lucide-react'
import Dashboard      from './pages/Dashboard.jsx'
import Connectors     from './pages/Connectors.jsx'
import DataGovernance from './pages/DataGovernance.jsx'
import AiGovernance   from './pages/AiGovernance.jsx'
import Login          from './pages/Login.jsx'
import { AuthProvider, useAuth } from './context/AuthContext.jsx'
import { getIntegrations } from './api/client.js'

const NAV = [
  { id: 'dashboard',       label: 'Dashboard',       Icon: LayoutGrid },
  { id: 'connectors',      label: 'Connectors',      Icon: Plug },
  { id: 'data-governance', label: 'Data Governance', Icon: Database },
  { id: 'ai-governance',   label: 'AI Governance',   Icon: Brain },
]

// ── Toast notification ────────────────────────────────────────────────────────
function Toast({ message, onDismiss }) {
  useEffect(() => {
    const t = setTimeout(onDismiss, 8000)
    return () => clearTimeout(t)
  }, [onDismiss])

  return (
    <div style={{
      position: 'fixed', bottom: 24, right: 24, zIndex: 9999,
      background: 'var(--bg-surface)', border: '1px solid rgba(16,185,129,0.3)',
      borderRadius: 12, padding: '14px 18px',
      boxShadow: '0 8px 32px rgba(0,0,0,0.4)',
      display: 'flex', alignItems: 'flex-start', gap: 12,
      maxWidth: 380, animation: 'fadeSlideUp 0.3s ease',
    }}>
      <CheckCircle size={18} color="#10b981" style={{ flexShrink: 0, marginTop: 1 }} />
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 2 }}>Welcome back!</div>
        <div style={{ fontSize: 12, color: 'var(--text-muted)', lineHeight: 1.5 }}>{message}</div>
      </div>
      <button onClick={onDismiss}
        style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-hint)', padding: 0, flexShrink: 0, display: 'flex' }}>
        <X size={14} />
      </button>
    </div>
  )
}

// ── Main app shell (only rendered when authenticated) ─────────────────────────
function AppShell() {
  const { user, logout } = useAuth()
  const [page, setPage]   = useState('dashboard')
  const [hovered, setHovered] = useState(null)
  const [toast, setToast]     = useState(null)

  const checkedConnectors = useRef(false)

  // After login, check if connectors already exist → show welcome toast
  useEffect(() => {
    if (checkedConnectors.current) return
    checkedConnectors.current = true

    getIntegrations()
      .then(list => {
        if (list.length > 0) {
          const names = list.slice(0, 2).map(i => i.name).join(', ')
          const extra = list.length > 2 ? ` and ${list.length - 2} more` : ''
          setToast(
            `Your connector${list.length > 1 ? 's' : ''} (${names}${extra}) ${list.length > 1 ? 'are' : 'is'} already connected. ` +
            `Go to Data Governance and click "Fetch & Analyse" to run the analysis.`
          )
        }
      })
      .catch(() => {})
  }, [])

  return (
    <div style={{ display: 'flex', height: '100vh', overflow: 'hidden', background: 'var(--bg-base)' }}>

      {/* ── Sidebar ── */}
      <aside style={{
        width: 240, minWidth: 240,
        background: 'var(--bg-surface)', borderRight: '1px solid var(--border)',
        display: 'flex', flexDirection: 'column', padding: 0,
      }}>
        {/* Logo */}
        <div style={{ padding: '24px 20px 20px', borderBottom: '1px solid var(--border)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <div style={{
              width: 36, height: 36, borderRadius: 10, flexShrink: 0,
              background: 'linear-gradient(135deg, #0d9488 0%, #14b8a6 100%)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              boxShadow: '0 2px 8px rgba(20,184,166,0.25)',
            }}>
              <Shield size={17} color="#fff" strokeWidth={2.5} />
            </div>
            <div>
              <div style={{ fontFamily: 'var(--font-display)', fontWeight: 400, fontSize: 22, color: 'var(--text-primary)', lineHeight: 1.1, letterSpacing: '-0.3px' }}>DataGuard</div>
              <div style={{ fontSize: 11, fontWeight: 500, color: 'var(--text-hint)', marginTop: 2, letterSpacing: '0.5px', textTransform: 'uppercase' }}>Governance Platform</div>
            </div>
          </div>
        </div>

        {/* Nav */}
        <nav style={{ padding: '16px 12px', flex: 1, overflowY: 'auto' }}>
          <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--text-hint)', textTransform: 'uppercase', letterSpacing: '1px', padding: '0 10px 10px' }}>
            Navigation
          </div>
          {NAV.map(({ id, label, Icon }) => {
            const active    = page === id
            const isHovered = hovered === id
            return (
              <button
                key={id}
                onClick={() => setPage(id)}
                onMouseEnter={() => setHovered(id)}
                onMouseLeave={() => setHovered(null)}
                style={{
                  width: '100%', display: 'flex', alignItems: 'center', gap: 10,
                  padding: '9px 12px', borderRadius: 8, border: 'none', marginBottom: 2,
                  background: active ? 'var(--accent-teal-soft)' : isHovered ? 'var(--bg-panel)' : 'transparent',
                  color: active ? 'var(--accent-teal)' : 'var(--text-muted)',
                  fontSize: 13, fontWeight: active ? 600 : 500,
                  textAlign: 'left', transition: 'all 0.2s ease',
                  ...(active ? { boxShadow: 'inset 3px 0 0 var(--accent-teal)' } : {}),
                }}
              >
                <Icon size={16} strokeWidth={active ? 2.2 : 1.8} />
                {label}
              </button>
            )
          })}
        </nav>

        {/* User + logout footer */}
        <div style={{ padding: '12px 16px', borderTop: '1px solid var(--border)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
            <div style={{
              width: 30, height: 30, borderRadius: '50%', flexShrink: 0,
              background: 'var(--accent-teal-soft)', display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}>
              <User size={14} color="var(--accent-teal)" />
            </div>
            <div style={{ flex: 1, overflow: 'hidden' }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {user?.full_name || user?.username || 'User'}
              </div>
              <div style={{ fontSize: 10, color: 'var(--text-hint)' }}>{user?.username}</div>
            </div>
          </div>
          <button onClick={logout}
            style={{
              width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 7,
              padding: '8px 12px', borderRadius: 8, border: '1px solid var(--border)',
              background: 'transparent', color: 'var(--text-muted)', fontSize: 12, fontWeight: 500,
              cursor: 'pointer', fontFamily: 'inherit', transition: 'all 0.18s',
            }}
            onMouseEnter={e => { e.currentTarget.style.borderColor = '#ef4444'; e.currentTarget.style.color = '#ef4444' }}
            onMouseLeave={e => { e.currentTarget.style.borderColor = 'var(--border)'; e.currentTarget.style.color = 'var(--text-muted)' }}
          >
            <LogOut size={13} /> Sign Out
          </button>
        </div>
      </aside>

      {/* ── Main content ── */}
      <main style={{ flex: 1, overflow: 'auto', background: 'var(--bg-base)' }}>
        {page === 'dashboard'       && <Dashboard />}
        {page === 'connectors'      && <Connectors />}
        {page === 'data-governance' && <DataGovernance onNavigate={setPage} />}
        {page === 'ai-governance'   && <AiGovernance />}
      </main>

      {/* ── Welcome-back toast ── */}
      {toast && <Toast message={toast} onDismiss={() => setToast(null)} />}

      <style>{`
        @keyframes fadeSlideUp {
          from { opacity: 0; transform: translateY(12px); }
          to   { opacity: 1; transform: translateY(0); }
        }
      `}</style>
    </div>
  )
}

// ── Root — wraps auth gate ────────────────────────────────────────────────────
function AuthGate() {
  const { isAuthenticated } = useAuth()
  return isAuthenticated ? <AppShell /> : <Login />
}

export default function App() {
  return (
    <AuthProvider>
      <AuthGate />
    </AuthProvider>
  )
}
