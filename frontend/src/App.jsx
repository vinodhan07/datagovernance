import { useState } from 'react'
import { LayoutGrid, Plug, Layers, Shield } from 'lucide-react'
import Dashboard from './pages/Dashboard.jsx'
import Connectors from './pages/Connectors.jsx'
import EvidenceBoard from './pages/EvidenceBoard.jsx'

const NAV = [
  { id: 'dashboard',      label: 'Dashboard',      Icon: LayoutGrid },
  { id: 'connectors',     label: 'Connectors',     Icon: Plug },
  { id: 'evidence-board', label: 'Evidence Board',  Icon: Layers },
]

export default function App() {
  const [page, setPage] = useState('dashboard')
  const [hovered, setHovered] = useState(null)

  return (
    <div style={{ display: 'flex', height: '100vh', overflow: 'hidden', background: 'var(--bg-base)' }}>
      {/* ── Sidebar ──────────────────────────────────────────── */}
      <aside
        style={{
          width: 240,
          minWidth: 240,
          background: 'var(--bg-surface)',
          borderRight: '1px solid var(--border)',
          display: 'flex',
          flexDirection: 'column',
          padding: 0,
        }}
      >
        {/* Logo */}
        <div style={{ padding: '24px 20px 20px', borderBottom: '1px solid var(--border)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <div
              style={{
                width: 36, height: 36, borderRadius: 10,
                background: 'linear-gradient(135deg, #0d9488 0%, #14b8a6 100%)',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                flexShrink: 0,
                boxShadow: '0 2px 8px rgba(20, 184, 166, 0.25)',
              }}
            >
              <Shield size={17} color="#fff" strokeWidth={2.5} />
            </div>
            <div>
              <div style={{
                fontFamily: 'var(--font-display)',
                fontWeight: 400,
                fontSize: 22,
                color: 'var(--text-primary)',
                lineHeight: 1.1,
                letterSpacing: '-0.3px',
              }}>
                DataGuard
              </div>
              <div style={{
                fontSize: 11,
                fontWeight: 500,
                color: 'var(--text-hint)',
                marginTop: 2,
                letterSpacing: '0.5px',
                textTransform: 'uppercase',
              }}>
                Governance Platform
              </div>
            </div>
          </div>
        </div>

        {/* Nav */}
        <nav style={{ padding: '16px 12px', flex: 1 }}>
          <div style={{
            fontSize: 10,
            fontWeight: 600,
            color: 'var(--text-hint)',
            textTransform: 'uppercase',
            letterSpacing: '1px',
            padding: '0 10px 10px',
          }}>
            Navigation
          </div>
          {NAV.map(({ id, label, Icon }) => {
            const active = page === id
            const isHovered = hovered === id
            return (
              <button
                key={id}
                onClick={() => setPage(id)}
                onMouseEnter={() => setHovered(id)}
                onMouseLeave={() => setHovered(null)}
                style={{
                  width: '100%',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 10,
                  padding: '9px 12px',
                  borderRadius: 8,
                  border: 'none',
                  marginBottom: 2,
                  background: active
                    ? 'var(--accent-teal-soft)'
                    : isHovered
                      ? 'var(--bg-panel)'
                      : 'transparent',
                  color: active ? 'var(--accent-teal)' : 'var(--text-muted)',
                  fontSize: 13,
                  fontWeight: active ? 600 : 500,
                  textAlign: 'left',
                  transition: 'all 0.2s ease',
                  ...(active ? { boxShadow: `inset 3px 0 0 var(--accent-teal)` } : {}),
                }}
              >
                <Icon size={16} strokeWidth={active ? 2.2 : 1.8} />
                {label}
              </button>
            )
          })}
        </nav>

        {/* Footer */}
        <div
          style={{
            padding: '14px 20px',
            borderTop: '1px solid var(--border)',
            fontSize: 11,
            color: 'var(--text-hint)',
            letterSpacing: '0.3px',
            fontWeight: 500,
          }}
        >
          FastAPI · PostgreSQL · MariaDB
        </div>
      </aside>

      {/* ── Main content ─────────────────────────────────────── */}
      <main style={{ flex: 1, overflow: 'auto', background: 'var(--bg-base)' }}>
        {page === 'dashboard'      && <Dashboard />}
        {page === 'connectors'     && <Connectors />}
        {page === 'evidence-board' && <EvidenceBoard />}
      </main>
    </div>
  )
}
