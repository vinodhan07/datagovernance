import { useState, useEffect, useRef } from 'react'
import { Loader, Database, RotateCcw } from 'lucide-react'
import Badge from '../components/Badge.jsx'

import PipelineTerminal from '../components/PipelineTerminal.jsx'
import LineageGraph from '../components/LineageGraph.jsx'
import AuditTimeline from '../components/AuditTimeline.jsx'
import { getIntegrations } from '../api/client.js'

// ── Section with heading ──────────────────────────────────────────────────────
function Section({ icon, label, children }) {
  return (
    <div style={{ marginBottom: 40 }}>
      <div style={{
        display: 'flex', alignItems: 'center', gap: 10,
        marginBottom: 20, paddingBottom: 12,
        borderBottom: '1px solid var(--border, #1e293b)',
      }}>
        <span style={{ fontSize: 18 }}>{icon}</span>
        <span style={{
          fontFamily: 'var(--font-display)',
          fontSize: 19, fontWeight: 400,
          color: 'var(--text-primary)', letterSpacing: '-0.2px',
        }}>
          {label}
        </span>
      </div>
      {children}
    </div>
  )
}

// ── Connection card ───────────────────────────────────────────────────────────
function ConnectionCard({ integration, active, onClick }) {
  return (
    <button
      onClick={onClick}
      style={{
        display: 'flex', flexDirection: 'column', gap: 5,
        padding: '12px 16px', minWidth: 180, textAlign: 'left',
        background: active ? 'var(--accent-teal-soft)' : 'var(--bg-surface)',
        border: `1.5px solid ${active ? 'var(--accent-teal-border, rgba(20,184,166,0.4))' : 'var(--border, #1e293b)'}`,
        borderRadius: 10, cursor: 'pointer', fontFamily: 'inherit',
        transition: 'all 0.18s',
        boxShadow: active ? '0 0 0 3px rgba(20,184,166,0.08)' : 'none',
      }}
      onMouseEnter={e => { if (!active) e.currentTarget.style.borderColor = 'var(--text-hint, #64748b)' }}
      onMouseLeave={e => { if (!active) e.currentTarget.style.borderColor = 'var(--border, #1e293b)' }}
    >
      <div style={{
        fontWeight: 700, fontSize: 13,
        color: active ? 'var(--accent-teal)' : 'var(--text-primary)',
      }}>
        {integration.name}
      </div>
      <div style={{ fontSize: 11, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
        {integration.provider_name}
      </div>
      <Badge label={integration.status} type={integration.status} />
    </button>
  )
}

// ── Main ──────────────────────────────────────────────────────────────────────
export default function EvidenceBoard() {
  const [integrations, setIntegrations] = useState([])
  const [loadingList, setLoadingList]   = useState(true)
  const [selected, setSelected]         = useState(null)

  // pipeline states
  const [terminalKey, setTerminalKey]   = useState(0)   // bump to remount terminal
  const [terminalOpen, setTerminalOpen] = useState(false)
  const [pipelineDone, setPipelineDone] = useState(false)
  const [pipelineFailed, setPipelineFailed] = useState(false)

  // track which integration we already auto-triggered for
  const autoTriggeredFor = useRef(null)

  // ── Load integrations on mount ──────────────────────────────────────────────
  useEffect(() => {
    getIntegrations()
      .then(list => {
        setIntegrations(list)
        if (list.length > 0) setSelected(list[0])
      })
      .catch(() => {})
      .finally(() => setLoadingList(false))
  }, [])

  // ── Auto-fetch when active integration selected ─────────────────────────────
  // Condition: integration exists + status === 'active' + not already triggered
  useEffect(() => {
    if (!selected) return
    if (selected.status !== 'active') return
    if (autoTriggeredFor.current === selected.id) return

    autoTriggeredFor.current = selected.id
    setPipelineDone(false)
    setPipelineFailed(false)
    setTerminalKey(k => k + 1)
    setTerminalOpen(true)
  }, [selected])

  // ── Switch connection ───────────────────────────────────────────────────────
  const handleSelect = (ig) => {
    if (selected?.id === ig.id) return
    setTerminalOpen(false)
    setPipelineDone(false)
    setPipelineFailed(false)
    setSelected(ig)
  }

  // ── Pipeline callbacks ──────────────────────────────────────────────────────
  const handleComplete = (lastEntry) => {
    if (lastEntry?.level === 'ERROR') {
      setPipelineFailed(true)
    } else {
      setPipelineDone(true)
    }
  }

  // ── Manual re-run ───────────────────────────────────────────────────────────
  const handleRefetch = () => {
    setPipelineDone(false)
    setPipelineFailed(false)
    setTerminalKey(k => k + 1)   // remount terminal cleanly
    setTerminalOpen(true)
  }

  // sections only appear once pipeline has succeeded
  const showSections = pipelineDone

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>

      {/* ── Your Connections — top bar ── */}
      <div style={{
        background: 'var(--bg-surface)',
        borderBottom: '1px solid var(--border, #1e293b)',
        padding: '16px 28px',
        flexShrink: 0,
      }}>
        <div style={{
          fontSize: 10, fontWeight: 700, color: 'var(--text-hint)',
          textTransform: 'uppercase', letterSpacing: '1.2px', marginBottom: 12,
        }}>
          Your Connections
        </div>

        {loadingList ? (
          <div style={{ color: 'var(--text-muted)', fontSize: 12, display: 'flex', gap: 6, alignItems: 'center' }}>
            <Loader size={12} className="spin" /> Loading…
          </div>
        ) : integrations.length === 0 ? (
          <div style={{ color: 'var(--text-muted)', fontSize: 13 }}>
            No integrations yet — go to <strong>Connectors</strong> to add one.
          </div>
        ) : (
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
            {integrations.map(ig => (
              <ConnectionCard
                key={ig.id}
                integration={ig}
                active={selected?.id === ig.id}
                onClick={() => handleSelect(ig)}
              />
            ))}
          </div>
        )}
      </div>

      {/* ── Scrollable content ── */}
      <main style={{ flex: 1, overflowY: 'auto', padding: '28px 32px' }}>

        {!selected ? (
          <div style={{
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            height: '60%', color: 'var(--text-hint)', fontSize: 14, textAlign: 'center',
          }}>
            <div>
              <div style={{ fontSize: 36, marginBottom: 12, opacity: 0.25 }}>⬆</div>
              Select a connection above to begin
            </div>
          </div>
        ) : (
          <>
            {/* ── Integration header ── */}
            <div className="fade-up" style={{
              display: 'flex', alignItems: 'flex-start',
              justifyContent: 'space-between', marginBottom: 24,
            }}>
              <div>
                <h2 style={{
                  fontFamily: 'var(--font-display)',
                  fontSize: 22, fontWeight: 400,
                  color: 'var(--text-primary)', letterSpacing: '-0.3px', margin: 0,
                }}>
                  {selected.name}
                </h2>
                <p style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4, fontWeight: 500 }}>
                  {selected.provider_name} integration
                </p>
              </div>

              {/* Action buttons — only for active connections */}
              {selected.status === 'active' && (
                <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                  {/* Re-fetch button — visible once pipeline ran */}
                  {(pipelineDone || pipelineFailed) && (
                    <button
                      onClick={handleRefetch}
                      style={{
                        display: 'flex', alignItems: 'center', gap: 6,
                        padding: '8px 16px', borderRadius: 8,
                        fontSize: 12, fontWeight: 600, fontFamily: 'inherit',
                        background: 'var(--bg-panel)',
                        color: 'var(--text-secondary)',
                        border: '1px solid var(--border)',
                        cursor: 'pointer', transition: 'all 0.18s',
                      }}
                      onMouseEnter={e => e.currentTarget.style.borderColor = 'var(--accent-teal)'}
                      onMouseLeave={e => e.currentTarget.style.borderColor = 'var(--border)'}
                    >
                      <RotateCcw size={12} /> Re-fetch Data
                    </button>
                  )}

                  {/* Status pill while fetching */}
                  {terminalOpen && !pipelineDone && !pipelineFailed && (
                    <div style={{
                      display: 'flex', alignItems: 'center', gap: 7,
                      padding: '7px 14px', borderRadius: 8,
                      fontSize: 12, fontWeight: 600,
                      background: 'rgba(245,158,11,0.08)',
                      color: '#f59e0b',
                      border: '1px solid rgba(245,158,11,0.2)',
                    }}>
                      <Database size={13} />
                      Fetching…
                    </div>
                  )}
                </div>
              )}

              {/* Inactive warning */}
              {selected.status !== 'active' && (
                <div style={{
                  fontSize: 12, color: 'var(--warning, #f59e0b)',
                  background: 'rgba(245,158,11,0.08)',
                  border: '1px solid rgba(245,158,11,0.2)',
                  borderRadius: 8, padding: '8px 16px', fontWeight: 500,
                }}>
                  ⚠ Connection inactive — go to Connectors to activate
                </div>
              )}
            </div>

            {/* ── Pipeline terminal (auto-runs for active connections) ── */}
            {terminalOpen && (
              <div style={{ marginBottom: 32 }}>
                <PipelineTerminal
                  key={terminalKey}
                  integrationId={selected.id}
                  isOpen={true}
                  onClose={() => setTerminalOpen(false)}
                  onComplete={handleComplete}
                />
              </div>
            )}

            {/* ── Sections — only shown after pipeline succeeds ── */}
            {showSections && (
              <div className="fade-up">
                {/* 1. Lineage — Primary Feature */}
                <Section icon="🔀" label="Data Lineage Flow">
                  <LineageGraph integrationId={selected.id} />
                </Section>


                {/* 3. Audit Log — Compliance Tracking */}
                <Section icon="📋" label="Governance Audit History">
                  <AuditTimeline integrationId={selected.id} />
                </Section>
              </div>
            )}

            {/* ── Pipeline failed state ── */}
            {pipelineFailed && !terminalOpen && (
              <div style={{
                background: 'rgba(239,68,68,0.06)',
                border: '1px solid rgba(239,68,68,0.2)',
                borderRadius: 10, padding: '20px 24px',
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                marginTop: 8,
              }}>
                <div>
                  <div style={{ fontWeight: 600, fontSize: 14, color: '#ef4444', marginBottom: 4 }}>
                    Pipeline failed
                  </div>
                  <div style={{ fontSize: 12, color: '#94a3b8' }}>
                    Data could not be fetched from MariaDB. Check your connection and try again.
                  </div>
                </div>
                <button
                  onClick={handleRefetch}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 6,
                    padding: '9px 18px', borderRadius: 8,
                    fontSize: 12, fontWeight: 600, fontFamily: 'inherit',
                    background: 'var(--accent-teal)', color: '#fff',
                    border: 'none', cursor: 'pointer',
                  }}
                >
                  <RotateCcw size={13} /> Retry
                </button>
              </div>
            )}

            {/* ── Waiting for inactive connection ── */}
            {selected.status !== 'active' && (
              <div style={{
                textAlign: 'center', color: 'var(--text-hint)',
                fontSize: 13, padding: '40px 0',
              }}>
                Activate this connection in <strong>Connectors</strong> to fetch and analyse data.
              </div>
            )}
          </>
        )}
      </main>
    </div>
  )
}
