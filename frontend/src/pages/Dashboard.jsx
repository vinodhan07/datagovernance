import { useEffect, useState } from 'react'
import { Plug, Shield, Zap, CheckCircle, Loader } from 'lucide-react'
import { getDashboardStats } from '../api/client.js'

const STEPS = [
  { n: 1, title: 'Create MariaDB Template',  desc: 'Go to Connectors and add a new template' },
  { n: 2, title: 'Connect Your MariaDB',      desc: 'Enter credentials and test the connection' },
  { n: 3, title: 'Open Evidence Board',       desc: 'Select your integration to start analysis' },
  { n: 4, title: 'Run a Quality Scan',        desc: 'Check your data quality with one click' },
  { n: 5, title: 'Review Findings',           desc: 'See what failed and why in plain English' },
  { n: 6, title: 'Review Findings',            desc: 'Act on quality issues and track improvements' },
]

function StatCard({ icon: Icon, label, value, color = '#14b8a6', loading, delay = 0 }) {
  return (
    <div
      className="fade-up"
      style={{
        background: 'var(--bg-surface)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--radius-md)',
        padding: '22px 24px',
        flex: 1,
        minWidth: 0,
        boxShadow: 'var(--shadow-card)',
        transition: 'box-shadow 0.25s ease, transform 0.25s ease',
        animationDelay: `${delay}s`,
      }}
      onMouseEnter={e => {
        e.currentTarget.style.boxShadow = 'var(--shadow-md)'
        e.currentTarget.style.transform = 'translateY(-2px)'
      }}
      onMouseLeave={e => {
        e.currentTarget.style.boxShadow = 'var(--shadow-card)'
        e.currentTarget.style.transform = 'translateY(0)'
      }}
    >
      <div
        style={{
          width: 40, height: 40, borderRadius: 10,
          background: `${color}10`,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          marginBottom: 14,
        }}
      >
        <Icon size={18} color={color} strokeWidth={2} />
      </div>
      <div style={{
        fontSize: 28,
        fontFamily: 'var(--font-display)',
        color: 'var(--text-primary)',
        lineHeight: 1,
        marginBottom: 4,
      }}>
        {loading ? <Loader size={20} className="spin" /> : value}
      </div>
      <div style={{ fontSize: 12, color: 'var(--text-muted)', fontWeight: 500 }}>{label}</div>
    </div>
  )
}

export default function Dashboard() {
  const [stats, setStats] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    getDashboardStats()
      .then(setStats)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  const doneSteps = stats
    ? new Set(
        [
          stats.integrations > 0 ? 1 : null,
          stats.integrations > 0 ? 2 : null,
          stats.quality_rules > 0 ? 3 : null,
        ].filter(Boolean)
      )
    : new Set()

  return (
    <div style={{ padding: '36px 40px', maxWidth: 940 }}>
      {/* Heading */}
      <div className="fade-up" style={{ marginBottom: 32 }}>
        <h1 style={{
          fontFamily: 'var(--font-display)',
          fontSize: 32,
          fontWeight: 400,
          color: 'var(--text-primary)',
          marginBottom: 6,
          letterSpacing: '-0.5px',
          lineHeight: 1.2,
        }}>
          Welcome to DataGuard
        </h1>
        <p style={{ color: 'var(--text-muted)', fontSize: 14, fontWeight: 400 }}>
          Connect your MariaDB and start governing your data
        </p>
      </div>

      {/* Error */}
      {error && (
        <div style={{
          background: 'var(--danger-bg)', border: '1px solid var(--danger-border)',
          borderRadius: 'var(--radius-sm)', padding: '12px 16px', color: 'var(--accent-red)',
          fontSize: 13, marginBottom: 24,
        }}>
          Failed to load stats: {error}
        </div>
      )}

      {/* Stat cards */}
      <div style={{ display: 'flex', gap: 16, marginBottom: 40, flexWrap: 'wrap' }}>
        <StatCard icon={Plug}      label="Integrations"  value={stats?.integrations}   loading={loading} color="#14b8a6" delay={0.05} />
        <StatCard icon={Shield}    label="Quality Rules"  value={stats?.quality_rules}  loading={loading} color="#8b5cf6" delay={0.10} />
        <StatCard icon={Zap}       label="Quality Score"  value={stats?.quality_score != null ? `${stats.quality_score}%` : '—'} loading={loading} color="#f59e0b" delay={0.15} />
      </div>
    </div>
  )
}
