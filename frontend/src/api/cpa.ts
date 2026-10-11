import api from './client'

export interface CpaAccount {
  id: string
  auth_index: string
  name: string
  provider: string
  provider_label: string
  label: string
  email: string
  account: string
  account_type: string
  project_id: string
  note: string
  priority: number | null
  weight: number | null
  status: string
  status_message: string
  state: string
  available: boolean
  disabled: boolean
  unavailable: boolean
  runtime_only: boolean
  success: number
  failed: number
  recent_requests: { time?: string; success?: number; failed?: number }[]
  cooldowns: Record<string, any>[]
  next_retry_after: string
  last_refresh: string
  updated_at: string
  created_at: string
  size: number
  supports_quota: boolean
}

export interface CpaAccountSummary {
  total: number
  active: number
  available: number
  degraded: number
  cooling: number
  error: number
  disabled: number
  pending: number
  refreshing: number
  healthy: boolean
}

/** 按账号类型分组的账号池统计。 */
export interface CpaProviderSummary extends CpaAccountSummary {
  provider: string
  label: string
}

/** 由托管实例自动维护的渠道，一个账号类型一条。 */
export interface CpaManagedChannel {
  id: string
  name: string
  cpa_provider: string
  health_status: string
  upstream_models: string[]
}

export interface CpaInstance {
  id: string
  name: string
  host: string
  port: number
  base_url: string
  version: string
  binary_path: string
  managed_binary: boolean
  install_dir: string
  config_path: string
  auth_dir: string
  log_path: string
  auto_start: boolean
  status: string
  pid: number | null
  access_key: string
  last_error: string
  last_started_at: string
  channels: CpaManagedChannel[]
}

export interface CpaStatus {
  manage_enabled: boolean
  install_dir: string
  release_repo: string
  platform: string
  machine: string
  asset_example: string
  channel_prefix: string
  oauth_providers: { value: string; label: string }[]
}

export async function getCpaStatus(): Promise<CpaStatus> {
  const res = await api.get('/cpa/status')
  return res.data
}

/** 托管实例是单例，后端按需自动创建。 */
export async function getCpaInstance(): Promise<CpaInstance> {
  const res = await api.get('/cpa/instance')
  return res.data
}

export async function installCpaBinary(version = '') {
  // 显式用 undefined 表示「不发送 body」；传 null 会被 axios 序列化成字符串 'null'。
  const res = await api.post('/cpa/instance/install', undefined, { params: { version } })
  return res.data
}

export async function startCpaInstance() {
  const res = await api.post('/cpa/instance/start')
  return res.data
}

export async function stopCpaInstance() {
  const res = await api.post('/cpa/instance/stop')
  return res.data
}

export async function restartCpaInstance() {
  const res = await api.post('/cpa/instance/restart')
  return res.data
}

export async function syncCpaChannels() {
  const res = await api.post('/cpa/instance/sync-channels')
  return res.data
}

export async function listCpaAccounts() {
  const res = await api.get('/cpa/accounts')
  return res.data as {
    data: CpaAccount[]
    summary: CpaAccountSummary
    by_provider: CpaProviderSummary[]
    instance: { id: string; name: string; status: string; quota_enabled: boolean }
  }
}

/** 单个额度窗口，例如 Claude 的 5 小时 / 7 天，或共享同一配额的模型组。 */
export interface CpaQuotaWindow {
  key: string
  label: string
  used_percent: number | null
  remaining_percent: number | null
  resets_at: string
  description: string
  /** 该窗口由多少个模型共享（按模型给额度的来源才有）。 */
  model_count?: number
}

export interface CpaAccountQuota {
  supported: boolean
  status: string
  plan: string
  available: boolean | null
  exhausted: boolean | null
  windows: CpaQuotaWindow[]
  error: string
}

/** 配额插件（cpa-quota-api-extension）的安装与加载状态。 */
export interface CpaQuotaPluginState {
  installed: boolean
  available: boolean
  enabled?: boolean
  registered?: boolean
  plugins_enabled?: boolean
  version?: string
  reason?: string
}

export interface CpaQuotaSnapshot {
  available: boolean
  reason: string
  generated_at: string
  cached?: boolean
  summary: Record<string, any>
  /** 以 auth_index 为键，与账号列表对应。 */
  accounts: Record<string, CpaAccountQuota>
  plugin: CpaQuotaPluginState
}

export async function getCpaQuotas(): Promise<CpaQuotaSnapshot> {
  const res = await api.get('/cpa/accounts/quota')
  return res.data
}

export async function refreshCpaQuotas(): Promise<CpaQuotaSnapshot> {
  const res = await api.post('/cpa/accounts/quota/refresh')
  return res.data
}

export async function installCpaQuotaPlugin(): Promise<CpaQuotaPluginState> {
  const res = await api.post('/cpa/accounts/quota/install')
  return res.data
}

export async function setCpaAccountStatus(
  name: string,
  disabled: boolean,
  authIndex?: string,
) {
  const res = await api.patch('/cpa/accounts', {
    name,
    disabled,
    auth_index: authIndex || undefined,
  })
  return res.data
}

export async function deleteCpaAccount(name: string) {
  const res = await api.delete('/cpa/accounts', { params: { name } })
  return res.data
}

export async function exportCpaAccount(name: string) {
  const res = await api.get('/cpa/accounts/export', { params: { name } })
  return res.data
}

export async function importCpaAccount(
  content: string,
  options: { name?: string; filename?: string } = {},
) {
  const res = await api.post('/cpa/accounts/import', {
    content,
    name: options.name || '',
    filename: options.filename || '',
  })
  return res.data
}

export async function refreshCpaAccounts(name = '', all = false) {
  const res = await api.post('/cpa/accounts/refresh', { name, all })
  return res.data
}

export async function resetCpaAccountQuota(name = '') {
  const res = await api.post('/cpa/accounts/reset-quota', { name })
  return res.data
}

export async function batchCpaAccounts(action: string, names: string[]) {
  const res = await api.post('/cpa/accounts/batch', { action, names })
  return res.data
}

export async function startCpaOauth(provider: string) {
  const res = await api.post('/cpa/oauth/start', { provider })
  return res.data
}

export async function pollCpaOauth(state: string) {
  const res = await api.get('/cpa/oauth/status', { params: { state } })
  return res.data
}

export async function cancelCpaOauth(state: string) {
  const res = await api.delete('/cpa/oauth/status', { params: { state } })
  return res.data
}

export async function listCpaModels() {
  const res = await api.get('/cpa/models')
  return res.data
}
