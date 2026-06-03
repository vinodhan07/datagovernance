import { X } from 'lucide-react'

export default function Modal({ title, onClose, children, width = 520 }) {
  return (
    <div
      onClick={e => { if (e.target === e.currentTarget) onClose() }}
      style={{
        position: 'fixed', inset: 0, zIndex: 1000,
        background: 'rgba(15, 23, 42, 0.3)',
        backdropFilter: 'blur(4px)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        padding: 20,
      }}
    >
      <div
        style={{
          background: 'var(--bg-elevated)',
          border: '1px solid var(--border)',
          borderRadius: 'var(--radius-lg)',
          width: '100%',
          maxWidth: width,
          maxHeight: '90vh',
          display: 'flex',
          flexDirection: 'column',
          boxShadow: 'var(--shadow-lg)',
          animation: 'fadeUp 0.25s ease-out both',
        }}
      >
        {/* Header */}
        <div
          style={{
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            padding: '18px 24px',
            borderBottom: '1px solid var(--border)',
          }}
        >
          <span style={{
            fontFamily: 'var(--font-display)',
            fontWeight: 400,
            fontSize: 20,
            color: 'var(--text-primary)',
            letterSpacing: '-0.2px',
          }}>
            {title}
          </span>
          <button
            onClick={onClose}
            style={{
              background: 'var(--bg-panel)', border: '1px solid var(--border)',
              cursor: 'pointer', color: 'var(--text-muted)',
              display: 'flex', padding: 5, borderRadius: 6,
              transition: 'all 0.15s',
            }}
            onMouseEnter={e => e.currentTarget.style.background = 'var(--border)'}
            onMouseLeave={e => e.currentTarget.style.background = 'var(--bg-panel)'}
          >
            <X size={14} />
          </button>
        </div>

        {/* Scrollable body */}
        <div style={{ padding: '24px', overflowY: 'auto', flex: 1 }}>
          {children}
        </div>
      </div>
    </div>
  )
}
