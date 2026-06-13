const BASE = 'http://localhost:8000'

function _authHeader() {
  const token = localStorage.getItem('dataguard_token')
  return token ? { Authorization: `Bearer ${token}` } : {}
}

export function getAuthHeader() {
  return _authHeader()
}

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ..._authHeader(), ...options.headers },
    ...options,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || `HTTP ${res.status}`)
  }
  return res.json()
}

// ── Auth ───────────────────────────────────────────────────────────────────
export const loginUser    = (username, password) =>
  request('/auth/login', { method: 'POST', body: JSON.stringify({ username, password }) })

export const registerUser = (data) =>
  request('/auth/register', { method: 'POST', body: JSON.stringify(data) })

export const getCurrentUser = () => request('/auth/me')

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
export const getQualityRules   = (integrationId) => {
  const qs = integrationId ? `?integration_id=${integrationId}` : ''
  return request(`/quality/rules${qs}`)
}
export const createQualityRule = (data) => request('/quality/rules', {
  method: 'POST', body: JSON.stringify(data),
})
export const deleteQualityRule = (id) => request(`/quality/rules/${id}`, { method: 'DELETE' })

// ── Quality Scans ─────────────────────────────────────────────────────────
export const getQualityScans     = (integrationId) => {
  const qs = integrationId ? `?integration_id=${integrationId}` : ''
  return request(`/quality/scans${qs}`)
}
export const getQualityScanDetail = (scanId) => request(`/quality/scans/${scanId}`)
export const getQualityScore      = (integrationId) => request(`/quality/score/${integrationId}`)

// Quality scan SSE stream URL (used directly with EventSource)
export const qualityScanUrl = (integrationId) => `${BASE}/quality/scan/${integrationId}`

// Legacy aliases kept for backward-compatibility with any older code
export const getRules       = getQualityRules
export const createRule     = createQualityRule
export const runScan        = (integrationId) => request(`/quality/scan/${integrationId}`)
export const getScanHistory = getQualityScans

// ── Pipeline ──────────────────────────────────────────────────────────────────
export const getCapabilities     = (integrationId) =>
  request(`/pipeline/${integrationId}/capabilities`)

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
export const ingestCatalog    = (integrationId) =>
  request(`/catalog/ingest/${integrationId}`, { method: 'POST' })

export const getCatalogTables = (q = '') => {
  const qs = q ? `?q=${encodeURIComponent(q)}` : ''
  return request(`/catalog/tables${qs}`)
}

export const getCatalogTable  = (fqn) =>
  request(`/catalog/tables/${encodeURIComponent(fqn)}`)

export const tagCatalogTable  = (fqn, tags) =>
  request(`/catalog/tables/${encodeURIComponent(fqn)}/tags`, {
    method: 'POST', body: JSON.stringify({ tags }),
  })

// Legacy stubs (kept for backward-compatibility)
export const takeSnapshot    = ingestCatalog
export const getLatestSnapshot = getCatalogTable
export const getSnapshotDiff   = (integrationId) => getCatalogTables()

// ── Lineage ───────────────────────────────────────────────────────────────────
export const getLineageGraph    = (integrationId) =>
  request(`/lineage/${integrationId}/graph`)

export const getLineageRuns     = (integrationId) =>
  request(`/lineage/${integrationId}`)

export const getLineageRunDetail = (integrationId, runId) =>
  request(`/lineage/${integrationId}/runs/${runId}`)
