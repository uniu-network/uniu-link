<template>
  <div class="page-stack">
    <PageHeader
      title="账号管理"
      description="由 UniuLink 托管 CLIProxyAPI 单实例，按账号类型自动生成渠道并统一管理登录凭据。"
      ><UiButton :loading="loading" @click="loadAll"><NavIcon name="refresh" />刷新</UiButton
      ></PageHeader
    >

    <ListState :error="loadError" @retry="loadAll" />
    <UiSpinner v-if="!loadError" :show="loading">
      <template v-if="instance">
        <UiCard>
          <div class="instance-bar">
            <span class="instance-name">{{ instance.name }}</span>
            <UiBadge :variant="instanceBadgeVariant">{{ instanceStatusLabel }}</UiBadge>
            <span class="secondary-text" role="status">{{ instance.base_url }}</span>
            <span v-if="instance.version" class="secondary-text">v{{ instance.version }}</span>
            <div class="instance-actions">
              <UiButton
                v-if="instance.status !== 'running'"
                :loading="actionBusy === 'start'"
                @click="doInstanceAction('start')"
                ><NavIcon name="play" />启动</UiButton
              >
              <UiButton
                v-else
                :loading="actionBusy === 'stop'"
                @click="doInstanceAction('stop')"
                ><NavIcon name="stop" />停止</UiButton
              >
              <UiButton
                :loading="actionBusy === 'restart'"
                :disabled="instance.status !== 'running'"
                @click="doInstanceAction('restart')"
                ><NavIcon name="refresh" />重启</UiButton
              >
              <UiButton
                :loading="actionBusy === 'sync'"
                :disabled="instance.status !== 'running'"
                @click="doInstanceAction('sync')"
                >同步渠道</UiButton
              >
              <UiButton :loading="actionBusy === 'install'" @click="doInstanceAction('install')"
                ><Download :size="16" />安装/更新</UiButton
              >
            </div>
          </div>
          <p v-if="instance.last_error" class="instance-error" role="alert">
            {{ instance.last_error }}
          </p>
        </UiCard>

        <div class="stat-grid">
          <UiCard v-for="card in overviewCards" :key="card.key" class="stat-card">
            <div class="stat-value" :class="card.className">{{ card.value }}</div>
            <div class="stat-label">{{ card.label }}</div>
          </UiCard>
        </div>

        <UiCard
          :title="poolHealthy ? '账号池健康' : '账号池不健康'"
          :class="['pool-banner', poolHealthy ? 'pool-ok' : 'pool-bad']"
        >
          <p class="pool-text">
            {{
              poolHealthy
                ? `账号池中仍有 ${summary.available} 个可用账号，对应渠道已自动生成并参与路由。`
                : '实例未运行或所有账号均不可用，托管渠道会被健康检查标记为不健康并暂停路由。'
            }}
          </p>
          <ul v-if="instance.channels.length" class="channel-list">
            <li v-for="channel in instance.channels" :key="channel.id">
              <UiBadge :variant="channelBadgeVariant(channel.health_status)">{{
                channelHealthLabel(channel.health_status)
              }}</UiBadge>
              <span>{{ channel.name }}</span>
              <span class="secondary-text">{{ channel.upstream_models.length }} 个模型</span>
            </li>
          </ul>
          <p v-else class="secondary-text">
            账号池为空，尚未生成托管渠道。添加账号后会自动创建 {{ channelPrefix }}&lt;账号类型&gt;
            渠道。
          </p>
        </UiCard>

        <UiSpinner :show="accountsLoading">
          <div class="list-toolbar" role="search" aria-label="筛选账号">
            <UiInput
              v-model="search"
              type="search"
              aria-label="搜索账号"
              placeholder="搜索名称、邮箱或类型"
              class="search-input"
            />
            <UiSelect v-model="stateFilter" :options="stateFilterOptions" aria-label="账号状态" />
            <span class="secondary-text" role="status"
              >显示 {{ filteredAccounts.length }} / {{ accounts.length }} 个账号</span
            >
            <UiButton v-if="search || stateFilter" variant="link" @click="clearFilters"
              >清除筛选</UiButton
            >
            <UiButton
              :loading="quotaBusy"
              :disabled="instance?.status !== 'running'"
              @click="loadQuotas(true)"
              ><NavIcon name="refresh" />刷新额度</UiButton
            >
            <UiButton variant="primary" class="toolbar-add" @click="openAccountsDrawer"
              ><NavIcon name="plus" />添加账号</UiButton
            >
          </div>

          <div v-if="selectedNames.length" class="batch-bar" role="region" aria-label="批量操作">
            <span class="secondary-text">已选择 {{ selectedNames.length }} 个账号</span>
            <UiButton :loading="batchBusy" @click="runBatch('enable')">批量启用</UiButton>
            <UiButton :loading="batchBusy" @click="runBatch('disable')">批量禁用</UiButton>
            <UiButton :loading="batchBusy" @click="runBatch('refresh')">批量刷新</UiButton>
            <UiButton variant="danger" :loading="batchBusy" @click="runBatch('delete')"
              >批量删除</UiButton
            >
            <UiButton variant="link" @click="selectedNames = []">取消选择</UiButton>
          </div>

          <div v-if="quotaHint" class="quota-hint" role="status">
            <span class="secondary-text">额度不可用：{{ quotaSnapshot?.reason }}</span>
            <UiButton
              v-if="canInstallQuotaPlugin"
              variant="link"
              :loading="quotaBusy"
              @click="installQuotaPlugin"
              >安装配额插件</UiButton
            >
          </div>

          <UiDataTable :columns="columns" :data="filteredAccounts" label="账号列表" />
        </UiSpinner>
      </template>
    </UiSpinner>

    <UiDrawer
      v-model:open="accountsDrawerOpen"
      title="添加账号"
      width="620px"
      :busy="submitting"
      :before-close="beforeCloseAccounts"
      @save="submitAccount"
    >
      <div class="space-y-4">
        <UiField label="添加方式">
          <UiSelect v-model="accountMode" :options="accountModeOptions" class="w-full" />
        </UiField>

        <template v-if="accountMode === 'oauth'">
          <UiField label="账号类型">
            <UiSelect v-model="oauthProvider" :options="oauthProviderOptions" class="w-full" />
          </UiField>
          <div class="oauth-actions">
            <UiButton variant="primary" :loading="oauthBusy" @click="startOauth"
              >获取授权链接</UiButton
            >
            <UiButton v-if="oauthState" variant="link" @click="cancelOauth">取消登录</UiButton>
          </div>
          <div v-if="oauthUrl" class="oauth-panel">
            <p class="secondary-text">在浏览器中打开以下链接并完成授权：</p>
            <a :href="oauthUrl" target="_blank" rel="noopener noreferrer" class="oauth-link">{{
              oauthUrl
            }}</a>
            <p class="secondary-text" role="status">
              登录状态：{{ oauthStatus || '未开始' }}
            </p>
          </div>
        </template>

        <template v-else>
          <UiField label="选择文件">
            <input
              ref="fileInput"
              type="file"
              accept="application/json,.json"
              class="file-input"
              @change="onFilePicked"
            />
          </UiField>
          <UiField label="凭据 JSON">
            <UiTextarea
              v-model="importContent"
              rows="8"
              placeholder='粘贴 auth 文件内容，例如 {"type":"codex","access_token":"..."}'
              class="w-full"
            />
          </UiField>
          <UiField label="保存文件名（可选）">
            <UiInput v-model="importName" placeholder="acc1.json" class="w-full" />
          </UiField>
          <p class="help-text">
            凭据内容只发送给本机托管的 CLIProxyAPI 实例，不会写入 UniuLink 数据库。
          </p>
        </template>
      </div>
      <template #footer>
        <div class="flex justify-end gap-2">
          <UiButton @click="closeAccountsDrawer">取消</UiButton>
          <UiButton
            v-if="accountMode !== 'oauth'"
            variant="primary"
            :loading="submitting"
            @click="submitAccount"
            >导入账号</UiButton
          >
        </div>
      </template>
    </UiDrawer>
  </div>
</template>

<script setup lang="ts">
import { computed, h, onMounted, ref } from 'vue'
import { Download } from 'lucide-vue-next'

import PageHeader from '@/components/PageHeader.vue'
import ListState from '@/components/ListState.vue'
import NavIcon from '@/components/NavIcon.vue'

import UiBadge from '@/components/ui/UiBadge.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiCard from '@/components/ui/UiCard.vue'
import UiCheckbox from '@/components/ui/UiCheckbox.vue'
import UiDataTable from '@/components/ui/UiDataTable.vue'
import UiDrawer from '@/components/ui/UiDrawer.vue'
import UiDropdown from '@/components/ui/UiDropdown.vue'
import UiDropdownItem from '@/components/ui/UiDropdownItem.vue'
import UiField from '@/components/ui/UiField.vue'
import UiInput from '@/components/ui/UiInput.vue'
import UiSelect from '@/components/ui/UiSelect.vue'
import UiSpinner from '@/components/ui/UiSpinner.vue'
import UiTextarea from '@/components/ui/UiTextarea.vue'

import { useConfirm, useToast } from '@/composables/useFeedback'
import { useUnsavedForm } from '@/composables/useUnsavedChanges'
import {
  batchCpaAccounts,
  cancelCpaOauth,
  deleteCpaAccount,
  exportCpaAccount,
  getCpaInstance,
  getCpaQuotas,
  getCpaStatus,
  importCpaAccount,
  installCpaBinary,
  installCpaQuotaPlugin,
  listCpaAccounts,
  pollCpaOauth,
  refreshCpaAccounts,
  refreshCpaQuotas,
  resetCpaAccountQuota,
  restartCpaInstance,
  setCpaAccountStatus,
  startCpaInstance,
  startCpaOauth,
  stopCpaInstance,
  syncCpaChannels,
  type CpaAccount,
  type CpaAccountQuota,
  type CpaAccountSummary,
  type CpaInstance,
  type CpaQuotaSnapshot,
} from '@/api/cpa'

const toast = useToast()
const confirm = useConfirm()

const loading = ref(true)
const accountsLoading = ref(false)
const loadError = ref('')
const submitting = ref(false)
const actionBusy = ref('')
const batchBusy = ref(false)
const channelPrefix = ref('CliProxyAPI-')

const instance = ref<CpaInstance | null>(null)
const accounts = ref<CpaAccount[]>([])
const quotaSnapshot = ref<CpaQuotaSnapshot | null>(null)
const quotaBusy = ref(false)
const summary = ref<CpaAccountSummary>({
  total: 0,
  active: 0,
  available: 0,
  degraded: 0,
  cooling: 0,
  error: 0,
  disabled: 0,
  pending: 0,
  refreshing: 0,
  healthy: false,
})
const selectedNames = ref<string[]>([])
const search = ref('')
const stateFilter = ref('')

const accountsDrawerOpen = ref(false)
const accountMode = ref('oauth')
const oauthProvider = ref('codex')
const oauthBusy = ref(false)
const oauthPolling = ref(false)
const oauthUrl = ref('')
const oauthState = ref('')
const oauthStatus = ref('')
const importContent = ref('')
const importName = ref('')
const fileInput = ref<HTMLInputElement | null>(null)

const accountsDraft = useUnsavedForm(
  accountsDrawerOpen,
  () => (accountMode.value === 'import' ? importContent.value : ''),
  submitting
)

const instanceStatusLabel = computed(() => {
  const status = instance.value?.status
  if (status === 'running') return '运行中'
  if (status === 'starting') return '启动中'
  if (status === 'error') return '异常'
  return '已停止'
})

const quotaHint = computed(() => !!quotaSnapshot.value && !quotaSnapshot.value.available)

const canInstallQuotaPlugin = computed(
  () => instance.value?.status === 'running' && !quotaSnapshot.value?.plugin?.installed
)

const instanceBadgeVariant = computed(() => {
  const status = instance.value?.status
  if (status === 'running') return 'success'
  if (status === 'error') return 'danger'
  if (status === 'starting') return 'warning'
  return 'default'
})

const poolHealthy = computed(
  () => instance.value?.status === 'running' && summary.value.healthy
)

function channelBadgeVariant(status: string): 'success' | 'danger' | 'default' {
  if (status === 'healthy') return 'success'
  if (status === 'unhealthy') return 'danger'
  return 'default'
}

function channelHealthLabel(status: string) {
  if (status === 'healthy') return '健康'
  if (status === 'unhealthy') return '不健康'
  return '未探测'
}

const overviewCards = computed(() => [
  { key: 'total', label: '账号总数', value: summary.value.total, className: '' },
  { key: 'available', label: '可用账号', value: summary.value.available, className: 'ok' },
  { key: 'cooling', label: '冷却中', value: summary.value.cooling, className: 'warn' },
  {
    key: 'error',
    label: '异常账号',
    value: summary.value.error,
    className: summary.value.error ? 'bad' : '',
  },
  { key: 'disabled', label: '已禁用', value: summary.value.disabled, className: '' },
])

const stateFilterOptions = [
  { label: '全部状态', value: '' },
  { label: '可用', value: 'available' },
  { label: '降级（部分模型冷却）', value: 'degraded' },
  { label: '冷却中', value: 'cooling' },
  { label: '异常', value: 'error' },
  { label: '已禁用', value: 'disabled' },
]

const accountModeOptions = [
  { label: 'OAuth 登录', value: 'oauth' },
  { label: '导入凭据 JSON', value: 'import' },
]

const oauthProviderOptions = [
  { label: 'OpenAI Codex', value: 'codex' },
  { label: 'Claude Code', value: 'claude' },
  { label: 'Antigravity', value: 'antigravity' },
  { label: 'Kimi', value: 'kimi' },
  { label: 'xAI', value: 'xai' },
  { label: 'Meta', value: 'meta' },
]

const stateLabels: Record<string, string> = {
  active: '可用',
  degraded: '降级',
  cooling: '冷却中',
  error: '异常',
  disabled: '已禁用',
  pending: '待处理',
  refreshing: '刷新中',
}

const stateVariants: Record<string, 'success' | 'warning' | 'danger' | 'default'> = {
  active: 'success',
  degraded: 'warning',
  cooling: 'warning',
  error: 'danger',
  disabled: 'default',
  pending: 'warning',
  refreshing: 'default',
}

function stateBadge(state: string) {
  return h(
    UiBadge,
    { variant: stateVariants[state] || 'default' },
    { default: () => stateLabels[state] || state || '未知' }
  )
}

function healthBar(account: CpaAccount) {
  const buckets = account.recent_requests || []
  if (!buckets.length) return h('span', { class: 'secondary-text' }, '暂无请求')
  const cells = buckets.slice(-20).map((bucket, index) => {
    const success = Number(bucket.success || 0)
    const failed = Number(bucket.failed || 0)
    const total = success + failed
    const ratio = total ? success / total : -1
    const level = ratio < 0 ? 'idle' : ratio >= 0.9 ? 'ok' : ratio >= 0.5 ? 'warn' : 'bad'
    const time = bucket.time ? new Date(bucket.time).toLocaleTimeString() : ''
    const title = total
      ? `${time} 成功 ${success} / 失败 ${failed}`
      : `${time} 无请求`
    return h('span', { class: `health-cell health-${level}`, title, key: index })
  })
  return h('span', { class: 'health-bar', 'aria-hidden': 'true' }, cells)
}

const filteredAccounts = computed(() => {
  const query = search.value.trim().toLowerCase()
  return accounts.value.filter((account) => {
    if (stateFilter.value === 'available' && !account.available) return false
    if (stateFilter.value && stateFilter.value !== 'available' && account.state !== stateFilter.value)
      return false
    if (!query) return true
    return [account.name, account.email, account.provider_label, account.label, account.note].some(
      (value) => value?.toLowerCase().includes(query)
    )
  })
})

const columns = computed(() => [
  {
    title: '选择',
    key: 'select',
    width: 60,
    render: (row: CpaAccount) =>
      h(UiCheckbox, {
        modelValue: selectedNames.value,
        value: row.name,
        'onUpdate:modelValue': (value: string[]) => (selectedNames.value = value),
        'aria-label': `选择账号 ${row.name}`,
      }),
  },
  {
    title: '状态',
    key: 'state',
    width: 130,
    render: (row: CpaAccount) =>
      h('span', { class: 'state-cell' }, [
        stateBadge(row.state),
        row.status_message
          ? h('span', { class: 'secondary-text state-message', title: row.status_message }, row.status_message)
          : null,
      ]),
  },
  {
    title: '类型',
    key: 'provider',
    width: 140,
    render: (row: CpaAccount) => h(UiBadge, null, { default: () => row.provider_label }),
  },
  { title: '额度', key: 'quota', width: 240, render: (row: CpaAccount) => quotaCell(row) },
  {
    title: '账号',
    key: 'identity',
    width: 200,
    render: (row: CpaAccount) => {
      const identity = row.email || row.label || row.account || row.name
      return h('span', { class: 'identity-cell' }, [
        h('span', null, identity),
        h('span', { class: 'secondary-text' }, row.name),
      ])
    },
  },
  {
    title: '优先级/权重',
    key: 'priority',
    width: 120,
    render: (row: CpaAccount) => `${row.priority ?? '-'} / ${row.weight ?? '-'}`,
  },
  {
    title: '请求统计',
    key: 'requests',
    width: 120,
    render: (row: CpaAccount) => `${row.success} / ${row.failed}`,
  },
  { title: '最近请求', key: 'recent', width: 190, render: (row: CpaAccount) => healthBar(row) },
  {
    title: '冷却',
    key: 'cooldown',
    width: 130,
    render: (row: CpaAccount) => formatCooldown(row),
  },
  {
    title: '备注',
    key: 'note',
    width: 140,
    render: (row: CpaAccount) => row.note || '-',
  },
  {
    title: '操作',
    key: 'actions',
    width: 110,
    render: (row: CpaAccount) =>
      h(UiDropdown, null, {
        default: () => [
          h(
            UiDropdownItem,
            { onClick: () => toggleAccount(row) },
            { default: () => (row.disabled ? '启用账号' : '禁用账号') }
          ),
          h(
            UiDropdownItem,
            { onClick: () => refreshAccount(row) },
            { default: () => '刷新 Token' }
          ),
          h(
            UiDropdownItem,
            { onClick: () => resetQuota(row) },
            { default: () => '重置冷却' }
          ),
          h(
            UiDropdownItem,
            { onClick: () => exportAccount(row) },
            { default: () => '导出凭据' }
          ),
          h(
            UiDropdownItem,
            { variant: 'danger', onClick: () => confirmDeleteAccount(row) },
            { default: () => '删除账号' }
          ),
        ],
      }),
  },
])

/** 该账号的额度快照（来自配额插件，按 auth_index 对应）。 */
function accountQuota(account: CpaAccount): CpaAccountQuota | undefined {
  return quotaSnapshot.value?.accounts?.[account.auth_index]
}

function quotaLevelClass(percent: number | null) {
  if (percent === null) return 'quota-level-unknown'
  if (percent <= 15) return 'quota-level-low'
  if (percent <= 40) return 'quota-level-mid'
  return 'quota-level-ok'
}

function clampPercent(value: number | null | undefined): number | null {
  if (value === null || value === undefined || Number.isNaN(value)) return null
  return Math.max(0, Math.min(100, value))
}

function formatQuotaReset(value: string) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  const pad = (input: number) => String(input).padStart(2, '0')
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

/** 额度单元格：套餐 + 各时间窗剩余百分比 + 重置时间。 */
function quotaCell(account: CpaAccount) {
  const quota = accountQuota(account)
  if (!quota) return h('span', { class: 'secondary-text' }, '—')
  if (!quota.windows.length) {
    return h(
      'span',
      { class: 'secondary-text', title: quota.error || quota.status },
      quota.error || '暂无额度数据'
    )
  }

  const children: any[] = []
  if (quota.plan) children.push(h('span', { class: 'quota-plan' }, quota.plan))

  for (const item of quota.windows) {
    const percent = clampPercent(item.remaining_percent)
    const title = [
      item.description,
      percent === null ? '' : `剩余 ${percent.toFixed(1)}%`,
      item.resets_at ? `重置 ${item.resets_at}` : '',
    ]
      .filter(Boolean)
      .join(' · ')
    children.push(
      h('div', { class: 'quota-window', key: item.key }, [
        h('span', { class: 'quota-window-label' }, item.label),
        h('span', { class: 'quota-bar', title }, [
          h('span', {
            class: ['quota-bar-fill', quotaLevelClass(percent)],
            style: { width: `${percent ?? 0}%` },
          }),
        ]),
        h('span', { class: 'quota-percent' }, percent === null ? '—' : `${Math.round(percent)}%`),
        item.resets_at
          ? h('span', { class: 'quota-reset secondary-text' }, `${formatQuotaReset(item.resets_at)} 重置`)
          : null,
      ])
    )
  }
  return h('div', { class: 'quota-cell' }, children)
}

function formatCooldown(account: CpaAccount) {
  if (account.next_retry_after) {
    const target = new Date(account.next_retry_after).getTime()
    const remaining = Math.max(0, Math.round((target - Date.now()) / 1000))
    if (remaining > 0) return formatSeconds(remaining)
  }
  const first = account.cooldowns?.[0]
  const seconds = Number(first?.remaining_seconds || 0)
  return seconds > 0 ? formatSeconds(seconds) : '-'
}

function formatSeconds(seconds: number) {
  if (seconds < 60) return `${seconds} 秒`
  if (seconds < 3600) return `${Math.round(seconds / 60)} 分钟`
  return `${(seconds / 3600).toFixed(1)} 小时`
}

function clearFilters() {
  search.value = ''
  stateFilter.value = ''
}

async function loadAll() {
  loading.value = true
  loadError.value = ''
  try {
    const status = await getCpaStatus()
    channelPrefix.value = status?.channel_prefix || 'CliProxyAPI-'
    instance.value = await getCpaInstance()
    await loadAccounts()
    // 额度需要插件向上游扫描，不阻塞账号列表渲染。
    void loadQuotas()
  } catch (error: any) {
    loadError.value = error?.response?.data?.detail || error?.message || '加载失败'
  } finally {
    loading.value = false
  }
}

async function loadAccounts() {
  accountsLoading.value = true
  try {
    const result = await listCpaAccounts()
    accounts.value = result?.data || []
    summary.value = result?.summary || summary.value
    if (instance.value) {
      instance.value.status = result?.instance?.status || instance.value.status
    }
    selectedNames.value = selectedNames.value.filter((name) =>
      accounts.value.some((account) => account.name === name)
    )
  } catch (error: any) {
    toast.error(error?.response?.data?.detail || '读取账号列表失败')
    accounts.value = []
  } finally {
    accountsLoading.value = false
  }
}

/** 读取账号额度；额度属于附加信息，失败不打断账号列表。 */
async function loadQuotas(refresh = false) {
  if (!instance.value || instance.value.status !== 'running') {
    quotaSnapshot.value = null
    return
  }
  quotaBusy.value = true
  try {
    quotaSnapshot.value = refresh ? await refreshCpaQuotas() : await getCpaQuotas()
  } catch (error: any) {
    quotaSnapshot.value = {
      available: false,
      reason: error?.response?.data?.detail || '读取账号额度失败',
      generated_at: '',
      summary: {},
      accounts: {},
      plugin: { installed: false, available: false },
    }
  } finally {
    quotaBusy.value = false
  }
}

async function installQuotaPlugin() {
  quotaBusy.value = true
  try {
    await installCpaQuotaPlugin()
    toast.success('配额插件已安装')
    await loadQuotas(true)
  } catch (error: any) {
    toast.error(error?.response?.data?.detail || '安装配额插件失败')
  } finally {
    quotaBusy.value = false
  }
}

async function doInstanceAction(action: string) {
  actionBusy.value = action
  try {
    if (action === 'start') await startCpaInstance()
    else if (action === 'stop') await stopCpaInstance()
    else if (action === 'restart') await restartCpaInstance()
    else if (action === 'sync') await syncCpaChannels()
    else if (action === 'install') await installCpaBinary()
    toast.success('操作已提交')
    await loadAll()
  } catch (error: any) {
    toast.error(error?.response?.data?.detail || '操作失败')
  } finally {
    actionBusy.value = ''
  }
}

async function toggleAccount(account: CpaAccount) {
  try {
    await setCpaAccountStatus(account.name, !account.disabled, account.auth_index)
    toast.success(account.disabled ? '账号已启用' : '账号已禁用')
    await loadAccounts()
  } catch (error: any) {
    toast.error(error?.response?.data?.detail || '更新账号状态失败')
  }
}

async function refreshAccount(account: CpaAccount) {
  try {
    await refreshCpaAccounts(account.name, false)
    toast.success('已触发 Token 刷新')
    await loadAccounts()
  } catch (error: any) {
    toast.error(error?.response?.data?.detail || '刷新失败')
  }
}

async function resetQuota(account: CpaAccount) {
  try {
    await resetCpaAccountQuota(account.name)
    toast.success('已重置冷却状态')
    await loadAccounts()
  } catch (error: any) {
    toast.error(error?.response?.data?.detail || '重置失败')
  }
}

async function exportAccount(account: CpaAccount) {
  try {
    const result = await exportCpaAccount(account.name)
    const blob = new Blob([result.content], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = result.name || account.name
    link.click()
    URL.revokeObjectURL(url)
    toast.success('凭据已导出')
  } catch (error: any) {
    toast.error(error?.response?.data?.detail || '导出失败')
  }
}

async function confirmDeleteAccount(account: CpaAccount) {
  const ok = await confirm({
    title: '删除账号',
    content: `确定删除账号 ${account.email || account.name}？该操作会移除 CLIProxyAPI 中的凭据文件。`,
    positiveText: '删除',
    variant: 'danger',
  })
  if (!ok) return
  try {
    await deleteCpaAccount(account.name)
    toast.success('账号已删除')
    await loadAccounts()
  } catch (error: any) {
    toast.error(error?.response?.data?.detail || '删除失败')
  }
}

async function runBatch(action: string) {
  if (!selectedNames.value.length) return
  if (action === 'delete') {
    const ok = await confirm({
      title: '批量删除账号',
      content: `确定删除选中的 ${selectedNames.value.length} 个账号？`,
      positiveText: '删除',
      variant: 'danger',
    })
    if (!ok) return
  }
  batchBusy.value = true
  try {
    const result = await batchCpaAccounts(action, selectedNames.value)
    const failed = result?.failed?.length || 0
    if (failed) toast.warning(`完成，其中 ${failed} 个账号失败`)
    else toast.success('批量操作已完成')
    selectedNames.value = []
    await loadAccounts()
  } catch (error: any) {
    toast.error(error?.response?.data?.detail || '批量操作失败')
  } finally {
    batchBusy.value = false
  }
}

function openAccountsDrawer() {
  accountMode.value = 'oauth'
  oauthUrl.value = ''
  oauthState.value = ''
  oauthStatus.value = ''
  importContent.value = ''
  importName.value = ''
  accountsDrawerOpen.value = true
}

function closeAccountsDrawer() {
  void accountsDraft.closeEditor()
}

function beforeCloseAccounts() {
  return accountsDraft.beforeClose()
}

async function onFilePicked(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  importContent.value = await file.text()
  if (!importName.value) importName.value = file.name
}

async function submitAccount() {
  if (accountMode.value === 'oauth') return
  if (!importContent.value.trim()) {
    toast.warning('请粘贴或选择凭据 JSON')
    return
  }
  submitting.value = true
  try {
    await importCpaAccount(importContent.value, {
      name: importName.value,
      filename: importName.value,
    })
    toast.success('账号已导入')
    accountsDrawerOpen.value = false
    await loadAccounts()
  } catch (error: any) {
    toast.error(error?.response?.data?.detail || '导入账号失败')
  } finally {
    submitting.value = false
  }
}

async function startOauth() {
  oauthBusy.value = true
  try {
    const result = await startCpaOauth(oauthProvider.value)
    oauthUrl.value = result?.url || ''
    oauthState.value = result?.state || ''
    oauthStatus.value = '等待授权'
    if (!oauthUrl.value) {
      toast.warning('CLIProxyAPI 未返回授权链接')
      return
    }
    pollOauth()
  } catch (error: any) {
    toast.error(error?.response?.data?.detail || '获取授权链接失败')
  } finally {
    oauthBusy.value = false
  }
}

async function pollOauth() {
  if (!oauthState.value) return
  oauthPolling.value = true
  const state = oauthState.value
  for (let attempt = 0; attempt < 150; attempt += 1) {
    if (oauthState.value !== state) break
    await new Promise((resolve) => setTimeout(resolve, 2000))
    try {
      const result = await pollCpaOauth(state)
      const status = result?.status
      if (status === 'ok') {
        oauthStatus.value = '授权成功'
        oauthState.value = ''
        toast.success('账号已添加')
        await loadAccounts()
        break
      }
      if (status === 'error') {
        oauthStatus.value = result?.error || '授权失败'
        oauthState.value = ''
        toast.error(oauthStatus.value)
        break
      }
      oauthStatus.value = '等待授权'
    } catch {
      // 轮询失败多为会话过期，交由用户重新发起。
      oauthStatus.value = '登录会话已失效'
      oauthState.value = ''
      break
    }
  }
  oauthPolling.value = false
}

async function cancelOauth() {
  const state = oauthState.value
  oauthState.value = ''
  oauthUrl.value = ''
  oauthStatus.value = ''
  if (!state) return
  try {
    await cancelCpaOauth(state)
  } catch {
    // 取消失败无需提示，会话会自行过期。
  }
}

onMounted(loadAll)
</script>

<style scoped>
.instance-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.75rem;
}
.instance-name {
  font-weight: 600;
}
.instance-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin-left: auto;
}
.instance-error {
  margin-top: 0.75rem;
  color: var(--message-error);
  font-size: 0.8125rem;
  word-break: break-word;
}
.stat-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 0.75rem;
}
.stat-card {
  text-align: center;
}
.stat-value {
  font-size: 1.75rem;
  font-weight: 600;
  line-height: 1.2;
}
.stat-value.ok {
  color: var(--message-success);
}
.stat-value.warn {
  color: var(--message-warning);
}
.stat-value.bad {
  color: var(--message-error);
}
.stat-label {
  margin-top: 0.25rem;
  color: var(--sidebar-muted);
  font-size: 0.8125rem;
}
.pool-banner.pool-ok {
  border-left: 3px solid var(--message-success);
}
.pool-banner.pool-bad {
  border-left: 3px solid var(--message-error);
}
.pool-text {
  font-size: 0.875rem;
}
.channel-list {
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
  margin-top: 0.5rem;
  padding: 0;
  list-style: none;
}
.channel-list li {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.8125rem;
}
.batch-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.75rem;
}
.state-cell,
.identity-cell {
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
  min-width: 0;
}
.state-message,
.identity-cell > span:last-child {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 180px;
  font-size: 0.75rem;
}
.health-bar {
  display: inline-flex;
  gap: 2px;
  align-items: flex-end;
  height: 18px;
}
.health-cell {
  width: 6px;
  height: 100%;
  border-radius: 2px;
  background: var(--surface-subtle);
  display: inline-block;
}
.health-ok {
  background: var(--message-success);
}
.health-warn {
  background: var(--message-warning);
}
.health-bad {
  background: var(--message-error);
}
.health-idle {
  background: var(--surface-subtle);
}
.quota-hint {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.75rem;
}
.quota-cell {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  min-width: 0;
}
.quota-plan {
  align-self: flex-start;
  padding: 0 0.375rem;
  border-radius: var(--controlCornerRadius, 4px);
  background: var(--surface-subtle);
  font-size: 0.6875rem;
  line-height: 1.25rem;
  text-transform: lowercase;
}
.quota-window {
  display: grid;
  grid-template-columns: 3.5rem 1fr 2.25rem;
  align-items: center;
  gap: 0.375rem;
  font-size: 0.75rem;
}
.quota-window-label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.quota-bar {
  display: block;
  height: 6px;
  border-radius: 3px;
  background: var(--surface-subtle);
  overflow: hidden;
}
.quota-bar-fill {
  display: block;
  height: 100%;
  border-radius: 3px;
  transition: width 0.2s ease;
}
.quota-percent {
  text-align: right;
  font-variant-numeric: tabular-nums;
}
.quota-reset {
  grid-column: 2 / -1;
  font-size: 0.6875rem;
}
.quota-level-ok {
  background: var(--message-success);
}
.quota-level-mid {
  background: var(--message-warning);
}
.quota-level-low {
  background: var(--message-error);
}
.quota-level-unknown {
  background: var(--surface-subtle);
}
.oauth-actions,
.oauth-panel {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}
.oauth-actions {
  flex-direction: row;
  align-items: center;
}
.oauth-link {
  word-break: break-all;
  font-size: 0.8125rem;
  color: hsl(var(--primary));
}
.file-input {
  font-size: 0.8125rem;
}
.help-text {
  margin-top: -0.25rem;
  font-size: 0.75rem;
  color: var(--sidebar-muted);
}
.toolbar-add {
  margin-left: auto;
}
@media (prefers-reduced-motion: reduce) {
  .health-cell {
    transition: none;
  }
}
</style>
