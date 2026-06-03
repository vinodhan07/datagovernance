const BASE = 'http://localhost:8000'

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || `HTTP ${res.status}`)
  }
  return res.json()
}

// ── Dashboard ──────────────────────────────────────────────────────────────
export const getDashboardStats = () => request('/dashboard/stats')

// ── Templates ─────────────────────────────────────────────────────────────
export const getTemplates     = ()     => request('/connectors/templates')
export const createTemplate   = (data) => request('/connectors/templates', {
  method: 'POST', body: JSON.stringify(data),
})

// ── Integrations ──────────────────────────────────────────────────────────
export const getIntegrations    = ()     => request('/connectors/integrations')
export const createIntegration  = (data) => request('/connectors/integrations', {
  method: 'POST', body: JSON.stringify(data),
})
export const testConnection = (id) =>
  request(`/connectors/integrations/${id}/test`, { method: 'POST' })

// ── Schema / Data Explorer ────────────────────────────────────────────────
export const getTables    = (integrationId) =>
  request(`/connectors/integrations/${integrationId}/tables`)

export const getTableData = (integrationId, tableName, limit = 100) =>
  request(`/connectors/integrations/${integrationId}/tables/${encodeURIComponent(tableName)}/data?limit=${limit}`)

// ── Quality Rules ─────────────────────────────────────────────────────────
export const getRules    = ()     => request('/data-quality/rules')
export const createRule  = (data) => request('/data-quality/rules', {
  method: 'POST', body: JSON.stringify(data),
})

// ── Scan ──────────────────────────────────────────────────────────────────
export const runScan       = (integrationId) =>
  request(`/data-quality/scan/${integrationId}`, { method: 'POST' })

export const getScanHistory = (integrationId) => {
  console.log(integrationId)
  const qs = integrationId ? `?integration_id=${integrationId}` : ''
  return request(`/data-quality/scan-history${qs}`)
}

// ── Pipeline ──────────────────────────────────────────────────────────────────
export const runPipeline         = (integrationId) =>
  request(`/pipeline/${integrationId}/run`)

export const getLatestPipelineRun = (integrationId) =>
  request(`/pipeline/${integrationId}/latest`)

export const getPipelineHistory   = (integrationId) =>
  request(`/pipeline/${integrationId}/history`)

// Pipeline SSE stream URL (used directly with EventSource, not fetch)
export const pipelineFetchUrl = (integrationId) =>
  `${BASE}/pipeline/${integrationId}/run`

// ── Audit ─────────────────────────────────────────────────────────────────────
export const getAuditLogs = ({ integrationId, eventType, limit = 50, offset = 0 } = {}) => {
  const params = new URLSearchParams()
  if (integrationId) params.set('integration_id', integrationId)
  if (eventType)     params.set('event_type', eventType)
  params.set('limit', limit)
  params.set('offset', offset)
  return request(`/audit/logs?${params}`)
}

export const getIntegrationAuditLog = (integrationId, limit = 100) =>
  request(`/audit/logs/${integrationId}?limit=${limit}`)

export const auditExportUrl = (integrationId) => {
  const qs = integrationId ? `?integration_id=${integrationId}` : ''
  return `${BASE}/audit/export${qs}`
}

// ── Catalog ───────────────────────────────────────────────────────────────────
export const takeSnapshot       = (integrationId) =>
  request(`/catalog/${integrationId}/snapshot`, { method: 'POST' })

export const getLatestSnapshot  = (integrationId) =>
  request(`/catalog/${integrationId}/latest`)

export const getSnapshotDiff    = (integrationId) =>
  request(`/catalog/${integrationId}/diff`)

// ── Lineage ───────────────────────────────────────────────────────────────────
export const getLineageGraph    = (integrationId) =>
  request(`/lineage/${integrationId}/graph`)

export const getLineageRuns     = (integrationId) =>
  request(`/lineage/${integrationId}`)

export const getLineageRunDetail = (integrationId, runId) =>
  request(`/lineage/${integrationId}/runs/${runId}`)
