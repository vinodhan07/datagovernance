import { useEffect, useState } from 'react'
import { Plug, Loader, X, ChevronDown, ChevronRight, Pencil, CheckCircle } from 'lucide-react'
import ConnectMariaDB from './ConnectMariaDB.jsx'
import ConnectGitHub from './ConnectGitHub.jsx'
import { getIntegrations, deleteIntegration } from '../../core/api.js'

// ── Section header (collapsible) ──────────────────────────────────────────────
function SectionHeader({ title, open, onToggle, action }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 }}>
      <button
        onClick={onToggle}
        style={{ display: 'flex', alignItems: 'center', gap: 10, background: 'none', border: 'none', cursor: 'pointer', padding: 0, fontFamily: 'inherit' }}
      >
        {open ? <ChevronDown size={14} color="var(--text-muted)" /> : <ChevronRight size={14} color="var(--text-muted)" />}
        <span style={{
          fontFamily: 'var(--font-display)',
          fontSize: 20,
          fontWeight: 400,
          color: 'var(--text-primary)',
          letterSpacing: '-0.2px'
        }}>{title}</span>
      </button>
      {action}
    </div>
  )
}

// ── Generic Connector Card ───────────────────────────────────────────────────
function ConnectorCard({ 
  name, 
  logoUrl, 
  logoFilter = 'none', 
  isConnected, 
  integration, 
  onConnect, 
  onDisconnect, 
  onEdit, 
  delay = 0 
}) {
  const [disconnecting, setDisconnecting] = useState(false)

  const handleDisconnect = async () => {
    setDisconnecting(true)
    try { await onDisconnect() }
    finally { setDisconnecting(false) }
  }

  return (
    <div
      className="fade-up"
      style={{
        background: 'var(--bg-surface)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--radius-md)',
        padding: '24px 20px',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: 12,
        width: 190,
        boxShadow: 'var(--shadow-card)',
        transition: 'all 0.25s ease',
        animationDelay: `${delay}s`,
      }}
      onMouseEnter={e => {
        e.currentTarget.style.boxShadow = 'var(--shadow-md)'
        e.currentTarget.style.transform = 'translateY(-2px)'
        if (isConnected) e.currentTarget.style.borderColor = 'var(--success-border)'
      }}
      onMouseLeave={e => {
        e.currentTarget.style.boxShadow = 'var(--shadow-card)'
        e.currentTarget.style.transform = 'translateY(0)'
        e.currentTarget.style.borderColor = 'var(--border)'
      }}
    >
      {/* Logo */}
      <div style={{
        width: 60, height: 60, borderRadius: 14,
        background: logoFilter !== 'none' ? 'var(--bg-panel)' : '#f0f9ff',
        border: '1px solid var(--border)',
        display: 'flex', alignItems: 'center', justifyContent: 'center', overflow: 'hidden',
        transition: 'all 0.3s ease',
      }}>
        <img
          src={logoUrl}
          alt={name}
          style={{ width: 42, height: 42, objectFit: 'contain', filter: logoFilter }}
          onError={e => {
            e.target.style.display = 'none'
            e.target.parentNode.innerHTML = `<span style="font-family:var(--font-display);font-size:24px;font-weight:400;color:var(--text-primary)">${name[0]}</span>`
          }}
        />
      </div>

      {/* Name */}
      <span style={{ fontWeight: 600, fontSize: 13, color: 'var(--text-primary)', letterSpacing: '-0.2px' }}>{name}</span>

      {isConnected ? (
        <>
          {/* Connected state */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: 'var(--success)' }}>
            <CheckCircle size={13} strokeWidth={2.5} />
            <span style={{ fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.4px', fontSize: 10 }}>Connected</span>
          </div>
          {integration && (
            <div style={{
              fontSize: 11,
              fontFamily: 'var(--font-mono)',
              color: 'var(--text-muted)',
              textAlign: 'center',
              maxWidth: 160,
              wordBreak: 'break-all',
              background: 'var(--bg-panel)',
              padding: '4px 8px',
              borderRadius: 4,
            }}>
              {integration.name}
            </div>
          )}
          <div style={{ display: 'flex', gap: 10, marginTop: 4 }}>
            <button
              onClick={onEdit}
              title="Edit connection"
              style={{
                background: 'var(--bg-panel)', border: '1px solid var(--border)', borderRadius: 6,
                padding: '7px', cursor: 'pointer', color: 'var(--text-muted)', display: 'flex', transition: 'all 0.2s'
              }}
              onMouseEnter={e => e.currentTarget.style.color = 'var(--text-primary)'}
              onMouseLeave={e => e.currentTarget.style.color = 'var(--text-muted)'}
            >
              <Pencil size={13} />
            </button>
            <button
              onClick={handleDisconnect}
              disabled={disconnecting}
              title="Disconnect"
              style={{
                background: 'var(--danger-bg)', border: '1px solid var(--danger-border)', borderRadius: 6,
                padding: '7px', cursor: disconnecting ? 'not-allowed' : 'pointer', color: 'var(--danger)',
                display: 'flex', transition: 'all 0.2s'
              }}
              onMouseEnter={e => e.currentTarget.style.background = 'rgba(239,68,68,0.1)'}
              onMouseLeave={e => e.currentTarget.style.background = 'var(--danger-bg)'}
            >
              {disconnecting ? <Loader size={13} className="spin" /> : <X size={13} />}
            </button>
          </div>
        </>
      ) : (
        /* Not connected state */
        <button
          onClick={onConnect}
          style={{
            width: '100%', background: 'var(--accent-teal)', color: 'var(--text-inverse)',
            border: 'none', borderRadius: 8, padding: '10px 14px',
            fontSize: 12, fontWeight: 600, cursor: 'pointer', fontFamily: 'inherit',
            display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
            marginTop: 6, boxShadow: '0 2px 8px rgba(20, 184, 166, 0.2)',
            transition: 'all 0.2s',
          }}
          onMouseEnter={e => { e.currentTarget.style.background = 'var(--accent-teal-hover)' }}
          onMouseLeave={e => { e.currentTarget.style.background = 'var(--accent-teal)' }}
        >
          <Plug size={13} /> Connect
        </button>
      )}
    </div>
  )
}

// ── Toast notification ────────────────────────────────────────────────────────
function Toast({ message, onHide }) {
  useEffect(() => {
    const t = setTimeout(onHide, 3000)
    return () => clearTimeout(t)
  }, [onHide])

  return (
    <div style={{
      position: 'fixed', bottom: 32, right: 32, zIndex: 3000,
      background: 'var(--text-primary)', border: 'none',
      borderRadius: 10, padding: '14px 22px',
      display: 'flex', alignItems: 'center', gap: 12,
      boxShadow: 'var(--shadow-lg)',
      fontSize: 13, color: 'var(--text-inverse)',
      animation: 'fadeUp 0.3s ease-out',
      fontWeight: 500,
    }}>
      <CheckCircle size={15} color="var(--accent-teal)" strokeWidth={2.5} />
      {message}
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────
export default function Connectors() {
  const [integrations, setIntegrations] = useState([])
  const [loading, setLoading]           = useState(true)
  const [dbSectionOpen, setDbSectionOpen] = useState(true)
  const [showMariaDBModal, setShowMariaDBModal] = useState(false)
  const [showGitHubModal, setShowGitHubModal] = useState(false)
  const [toast, setToast] = useState(null)

  const reload = () => {
    setLoading(true)
    getIntegrations().then(setIntegrations).finally(() => setLoading(false))
  }
  useEffect(reload, [])

  const mariadbIntegration = integrations.find(i => i.provider_name === 'MariaDB') ?? null
  const githubIntegration = integrations.find(i => i.provider_name === 'GitHub') ?? null

  const handleMariaDBConnected = () => {
    reload()
    setToast('MariaDB connected successfully')
  }

  const handleGitHubConnected = () => {
    reload()
    setToast('GitHub connected successfully')
  }

  const handleDisconnect = async (integrationId, providerName) => {
    await deleteIntegration(integrationId)
    reload()
    setToast(`${providerName} disconnected`)
  }

  return (
    <div style={{ padding: '36px 40px' }}>
      <div className="fade-up" style={{ marginBottom: 32 }}>
        <h1 style={{
          fontFamily: 'var(--font-display)',
          fontSize: 32,
          fontWeight: 400,
          color: 'var(--text-primary)',
          letterSpacing: '-1px',
          marginBottom: 6,
        }}>Connectors</h1>
        <p style={{ color: 'var(--text-muted)', fontSize: 14 }}>Manage your data source integrations</p>
      </div>

      {loading && (
        <div style={{ color: 'var(--text-muted)', display: 'flex', gap: 10, alignItems: 'center', fontSize: 13, marginBottom: 24 }}>
          <Loader size={15} className="spin" /> Loading integrations…
        </div>
      )}

      <section className="fade-up" style={{ animationDelay: '0.1s' }}>
        <SectionHeader
          title="Data Connectors"
          open={dbSectionOpen}
          onToggle={() => setDbSectionOpen(p => !p)}
        />

        {dbSectionOpen && (
          <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap' }}>
            <ConnectorCard
              name="MariaDB"
              logoUrl="https://mariadb.com/wp-content/uploads/2019/11/mariadb-logo-vert_blue-transparent.png"
              isConnected={!!mariadbIntegration}
              integration={mariadbIntegration}
              onConnect={() => setShowMariaDBModal(true)}
              onDisconnect={() => handleDisconnect(mariadbIntegration?.id, 'MariaDB')}
              onEdit={() => setShowMariaDBModal(true)}
              delay={0.15}
            />
            
            <ConnectorCard
              name="GitHub"
              logoUrl="https://github.githubassets.com/images/modules/logos_page/GitHub-Mark.png"
              logoFilter="invert(1)"
              isConnected={!!githubIntegration}
              integration={githubIntegration}
              onConnect={() => setShowGitHubModal(true)}
              onDisconnect={() => handleDisconnect(githubIntegration?.id, 'GitHub')}
              onEdit={() => setShowGitHubModal(true)}
              delay={0.2}
            />
          </div>
        )}
      </section>

      <ConnectMariaDB
        isOpen={showMariaDBModal}
        onClose={() => setShowMariaDBModal(false)}
        onSuccess={handleMariaDBConnected}
      />

      <ConnectGitHub
        isOpen={showGitHubModal}
        onClose={() => setShowGitHubModal(false)}
        onSuccess={handleGitHubConnected}
      />

      {toast && <Toast message={toast} onHide={() => setToast(null)} />}
    </div>
  )
}
