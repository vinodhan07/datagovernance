/**
 * PipelineTerminal
 * ─────────────────
 * Live terminal-style log streamed from GET /pipeline/{id}/fetch via SSE.
 * Shows one log line per event with colour-coded levels.
 *
 * Props:
 *   integrationId  — string
 *   isOpen         — bool
 *   onClose        — fn()
 *   onComplete     — fn(lastEntry) called when DONE or ERROR received
 */

import { useEffect, useRef, useState, useCallback } from 'react'
import { X, Copy, RotateCcw, CheckCircle } from 'lucide-react'

const BASE = 'http://localhost:8000'

// Colour map per level
const LEVEL_STYLE = {
  INFO:  { color: '#94a3b8', weight: 400 },
  OK:    { color: '#10b981', weight: 500 },
  WARN:  { color: '#f59e0b', weight: 500 },
  FAIL:  { color: '#ef4444', weight: 500 },
  ERROR: { color: '#ef4444', weight: 700 },
  DONE:  { color: '#2dd4bf', weight: 700 },
}

function LogLine({ entry, isLast, running }) {
  const style = LEVEL_STYLE[entry.level || 'INFO'] || LEVEL_STYLE.INFO
  return (
    <div style={{
      display: 'flex', gap: 12, padding: '2px 0',
      animation: 'termFadeIn 0.15s ease-out',
      fontFamily: '"JetBrains Mono", "Fira Code", "Cascadia Code", Consolas, monospace',
      fontSize: 12.5,
      lineHeight: 1.7,
    }}>
      {/* Timestamp */}
        [{entry.ts || '--:--:--'}]
      {/* Level badge */}
      <span style={{
        minWidth: 48, fontWeight: 700, fontSize: 11,
        color: style.color, userSelect: 'none',
        letterSpacing: '0.5px',
      }}>
        {entry.level || 'INFO'}
      </span>
      {/* Message */}
      <span style={{ color: style.color, fontWeight: style.weight, flex: 1 }}>
        {entry.msg || ''}
        {isLast && running && (
          <span style={{ animation: 'termBlink 1s step-end infinite', marginLeft: 2 }}>▋</span>
        )}
      </span>
    </div>
  )
}

export default function PipelineTerminal({ integrationId, isOpen, onClose, onComplete }) {
  const [lines, setLines]       = useState([])
  const [running, setRunning]   = useState(false)
  const [copied, setCopied]     = useState(false)
  const [elapsed, setElapsed]   = useState(0)
  const esRef                   = useRef(null)
  const bottomRef               = useRef(null)
  const startTimeRef            = useRef(null)
  const timerRef                = useRef(null)

  // Auto-scroll to bottom on new lines
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [lines])

  // Elapsed timer
  useEffect(() => {
    if (running) {
      startTimeRef.current = Date.now()
      timerRef.current = setInterval(() => {
        setElapsed(Math.floor((Date.now() - startTimeRef.current) / 1000))
      }, 1000)
    } else {
      clearInterval(timerRef.current)
    }
    return () => clearInterval(timerRef.current)
  }, [running])

  const startFetch = useCallback(() => {
    if (!integrationId) return

    // Close any existing stream
    if (esRef.current) {
      esRef.current.close()
      esRef.current = null
    }

    setLines([])
    setElapsed(0)
    setRunning(true)

    const es = new EventSource(`${BASE}/pipeline/${integrationId}/run`)
    esRef.current = es

    es.onmessage = (event) => {
      try {
        const entry = JSON.parse(event.data)
        setLines(prev => [...prev, entry])

        if (entry.level === 'DONE' || entry.level === 'ERROR') {
          es.close()
          esRef.current = null
          setRunning(false)
          if (onComplete) onComplete(entry)
        }
      } catch (_) {}
    }

    es.onerror = () => {
      es.close()
      esRef.current = null
      setRunning(false)
      setLines(prev => [
        ...prev,
        { ts: new Date().toLocaleTimeString('en-US', { hour12: false }), level: 'ERROR', msg: 'Connection lost — check backend is running' },
      ])
    }
  }, [integrationId, onComplete])

  // Auto-start when opened
  useEffect(() => {
    if (isOpen && integrationId) {
      startFetch()
    }
    return () => {
      if (esRef.current) {
        esRef.current.close()
        esRef.current = null
      }
      clearInterval(timerRef.current)
    }
  }, [isOpen, integrationId]) // eslint-disable-line react-hooks/exhaustive-deps

  const handleCopy = () => {
    const text = lines.map(l => `[${l.ts || ''}] ${(l.level || '').padEnd(5)} ${l.msg || ''}`).join('\n')
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1800)
    })
  }

  const lastEntry = lines[lines.length - 1]
  const isDone    = lastEntry?.level === 'DONE'
  const isError   = lastEntry?.level === 'ERROR'

  if (!isOpen) return null

  return (
    <>
      {/* CSS animations */}
      <style>{`
        @keyframes termFadeIn {
          from { opacity: 0; transform: translateY(4px); }
          to   { opacity: 1; transform: translateY(0); }
        }
        @keyframes termBlink {
          0%, 100% { opacity: 1; }
          50%       { opacity: 0; }
        }
        @keyframes termSpin {
          from { transform: rotate(0deg); }
          to   { transform: rotate(360deg); }
        }
      `}</style>

      <div style={{
        background: '#080f1a',
        border: '1px solid #1e293b',
        borderRadius: 12,
        overflow: 'hidden',
        marginBottom: 24,
        boxShadow: '0 4px 32px rgba(0,0,0,0.5)',
      }}>
        {/* Title bar */}
        <div style={{
          background: '#0d1626',
          borderBottom: '1px solid #1e293b',
          padding: '10px 16px',
          display: 'flex', alignItems: 'center', gap: 10,
        }}>
          {/* Traffic lights */}
          <div style={{ display: 'flex', gap: 6, marginRight: 6 }}>
            <div style={{ width: 11, height: 11, borderRadius: '50%', background: '#ef4444', opacity: 0.8 }} />
            <div style={{ width: 11, height: 11, borderRadius: '50%', background: '#f59e0b', opacity: 0.8 }} />
            <div style={{ width: 11, height: 11, borderRadius: '50%', background: '#22c55e', opacity: 0.8 }} />
          </div>

          <span style={{
            fontFamily: '"JetBrains Mono", Consolas, monospace',
            fontSize: 12, color: '#64748b', flex: 1,
          }}>
            Pipeline Fetch Log
          </span>

          {/* Status badge */}
          {running && (
            <span style={{
              fontSize: 11, color: '#f59e0b', fontWeight: 600,
              background: 'rgba(245,158,11,0.1)', border: '1px solid rgba(245,158,11,0.2)',
              borderRadius: 6, padding: '2px 8px',
            }}>
              <span style={{
                display: 'inline-block', marginRight: 5,
                animation: 'termSpin 1s linear infinite',
              }}>⟳</span>
              RUNNING
            </span>
          )}
          {isDone && (
            <span style={{
              fontSize: 11, color: '#10b981', fontWeight: 600,
              background: 'rgba(16,185,129,0.1)', border: '1px solid rgba(16,185,129,0.2)',
              borderRadius: 6, padding: '2px 8px',
            }}>
              ✓ COMPLETED
            </span>
          )}
          {isError && !running && !isDone && (
            <span style={{
              fontSize: 11, color: '#ef4444', fontWeight: 600,
              background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.2)',
              borderRadius: 6, padding: '2px 8px',
            }}>
              ✕ FAILED
            </span>
          )}

          {/* Copy button */}
          <button
            onClick={handleCopy}
            title="Copy logs"
            style={{
              background: 'transparent', border: '1px solid #1e293b',
              borderRadius: 6, padding: '3px 8px', cursor: 'pointer',
              color: copied ? '#10b981' : '#475569', fontSize: 11,
              display: 'flex', alignItems: 'center', gap: 4,
              fontFamily: 'inherit', transition: 'color 0.2s',
            }}
          >
            {copied ? <CheckCircle size={12} /> : <Copy size={12} />}
            {copied ? 'Copied' : 'Copy'}
          </button>

          {/* Close */}
          <button
            onClick={onClose}
            style={{
              background: 'transparent', border: 'none',
              cursor: 'pointer', color: '#475569', padding: 4,
              display: 'flex', alignItems: 'center',
            }}
          >
            <X size={15} />
          </button>
        </div>

        {/* Log area */}
        <div style={{
          height: 360,
          overflowY: 'auto',
          padding: '14px 20px',
          background: '#080f1a',
        }}>
          {lines.length === 0 && !running && (
            <div style={{
              color: '#334155', fontFamily: 'monospace', fontSize: 12,
              paddingTop: 8,
            }}>
              Waiting to start…
            </div>
          )}
          {lines.map((entry, i) => (
            <LogLine
              key={i}
              entry={entry}
              isLast={i === lines.length - 1}
              running={running}
            />
          ))}
          <div ref={bottomRef} />
        </div>

        {/* Footer */}
        <div style={{
          background: '#0d1626',
          borderTop: '1px solid #1e293b',
          padding: '8px 16px',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        }}>
          <span style={{
            fontFamily: 'monospace', fontSize: 11, color: '#475569',
          }}>
            {running
              ? `Elapsed: ${elapsed}s`
              : lines.length > 0
                ? `${lines.length} log lines · ${elapsed}s total`
                : ''
            }
          </span>

          <div style={{ display: 'flex', gap: 8 }}>
            {(isError || (!running && lines.length > 0)) && (
              <button
                onClick={startFetch}
                style={{
                  background: 'transparent',
                  border: '1px solid #1e293b',
                  borderRadius: 6, padding: '4px 12px',
                  fontSize: 11, color: '#94a3b8', cursor: 'pointer',
                  display: 'flex', alignItems: 'center', gap: 5,
                  fontFamily: 'inherit',
                }}
              >
                <RotateCcw size={11} /> Re-run
              </button>
            )}
            {isDone && (
              <button
                onClick={onClose}
                style={{
                  background: 'var(--accent-teal, #14b8a6)',
                  border: 'none',
                  borderRadius: 6, padding: '4px 14px',
                  fontSize: 11, color: '#fff', cursor: 'pointer',
                  fontWeight: 600, fontFamily: 'inherit',
                }}
              >
                View Results ↓
              </button>
            )}
          </div>
        </div>
      </div>
    </>
  )
}
