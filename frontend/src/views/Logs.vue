<template>
  <div class="page-stack">
    <PageHeader title="请求日志" description="查询调用记录、Token 用量和上游响应。"
      ><UiButton :loading="loading" @click="load"
        ><NavIcon name="refresh" />刷新</UiButton
      ></PageHeader
    >
    <UiCard>
      <form class="stack" @submit.prevent="load">
        <div class="fields">
          <UiField label="API 类型"
            ><UiSelect
              v-model="filters.api_type"
              :options="apiTypeFilterOptions"
              placeholder="全部 API 类型"
          /></UiField>
          <UiField label="模型"><UiInput v-model="filters.model" placeholder="模型名称" /></UiField>
          <UiField label="调用密钥"
            ><UiInput v-model="filters.from_apikey" placeholder="API Key 名称 / ID"
          /></UiField>
          <UiField label="状态码"
            ><UiInput v-model.number="filters.status" type="number" placeholder="例如 200"
          /></UiField>
        </div>
        <div class="actions">
          <UiButton variant="primary" native-type="submit" :loading="loading">查询</UiButton>
        </div>
      </form>
    </UiCard>

    <ListState :error="loadError" @retry="load" />
    <UiSpinner v-if="!loadError" :show="loading">
      <UiDataTable :columns="columns" :data="logs" />
      <div class="pagination">
        <div class="actions">
          <UiButton
            :loading="pagingDirection === 'previous'"
            :disabled="page <= 1 || loading"
            @click="changePage(-1)"
            >上一页</UiButton
          >
          <span class="text-sm text-muted-foreground"
            >第 {{ page }} 页 / 共 {{ Math.max(1, Math.ceil(total / pageSize)) }} 页</span
          >
          <UiButton
            :loading="pagingDirection === 'next'"
            :disabled="page >= Math.ceil(total / pageSize) || loading"
            @click="changePage(1)"
            >下一页</UiButton
          >
        </div>
        <UiSelect v-model="pageSizeStr" :options="pageSizeOptions" aria-label="每页条数" />
      </div>
    </UiSpinner>

    <UiDrawer v-model:open="drawerVisible" title="请求详情" width="640px">
      <div v-if="selectedLog" class="space-y-4">
        <UiCard title="基本信息">
          <InfoGrid :items="basicInfo" />
        </UiCard>
        <UiCard title="Token 统计">
          <InfoGrid :items="tokenInfo" />
        </UiCard>
        <UiCard v-if="selectedLog.error_message" title="错误信息">
          <p class="text-sm message-symbol-error">{{ selectedLog.error_message }}</p>
        </UiCard>
        <CodePanel
          v-if="selectedLog.input_content"
          title="输入内容"
          :code="selectedLog.input_content"
        />
        <CodePanel
          v-if="selectedLog.output_content"
          title="输出内容"
          :code="selectedLog.output_content"
        />
        <CodePanel
          v-if="selectedLog.request_body"
          title="请求体"
          :code="formatJson(selectedLog.request_body)"
        />
        <CodePanel
          v-if="selectedLog.response_body"
          title="响应体"
          :code="formatJson(selectedLog.response_body)"
        />
      </div>
    </UiDrawer>
  </div>
</template>

<script setup lang="ts">
import PageHeader from '@/components/PageHeader.vue'
import ListState from '@/components/ListState.vue'
import NavIcon from '@/components/NavIcon.vue'
import ModelLabel from '@/components/ModelLabel.vue'
import { listModels } from '@/api/models'
import { upstreamModelNames, type ModelPresentation } from '@/utils/modelIdentity'

import UiInput from '@/components/ui/UiInput.vue'
import UiField from '@/components/ui/UiField.vue'
import { computed, defineComponent, ref, onMounted, watch, h } from 'vue'
import { FileSearch } from 'lucide-vue-next'
import { listLogs } from '@/api/logs'
import UiBadge from '@/components/ui/UiBadge.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiCard from '@/components/ui/UiCard.vue'
import UiDataTable from '@/components/ui/UiDataTable.vue'
import UiDrawer from '@/components/ui/UiDrawer.vue'
import UiDropdown from '@/components/ui/UiDropdown.vue'
import UiDropdownItem from '@/components/ui/UiDropdownItem.vue'
import UiSelect from '@/components/ui/UiSelect.vue'
import UiSpinner from '@/components/ui/UiSpinner.vue'

const InfoGrid = defineComponent({
  props: { items: { type: Array, required: true } },
  setup(props) {
    return () =>
      h(
        'dl',
        { class: 'grid gap-3 sm:grid-cols-2' },
        (props.items as any[]).map((item) =>
          h('div', { class: 'rounded-lg border border-border/60 bg-muted/20 p-3' }, [
            h('dt', { class: 'text-xs text-muted-foreground' }, item.label),
            h('dd', { class: 'mt-1 break-all text-sm font-medium' }, item.value),
          ])
        )
      )
  },
})

const CodePanel = defineComponent({
  props: { title: String, code: String },
  setup(props) {
    return () =>
      h(
        UiCard,
        { title: props.title },
        {
          default: () =>
            h(
              'pre',
              {
                class:
                  'max-h-80 overflow-auto whitespace-pre-wrap rounded-lg bg-muted p-3 text-xs thin-scrollbar',
              },
              props.code
            ),
        }
      )
  },
})

const logs = ref<any[]>([])
const modelCatalog = ref<ModelPresentation[]>([])
const loading = ref(true)
const loadError = ref('')
const pagingDirection = ref<'previous' | 'next' | ''>('')
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const filters = ref<{
  api_type: string
  model: string
  from_apikey: string
  status: number | null
}>({ api_type: '', model: '', from_apikey: '', status: null })

const drawerVisible = ref(false)
const selectedLog = ref<any>(null)

const apiTypeOptions = [
  { label: 'OpenAI', value: 'openai' },
  { label: 'Responses', value: 'responses' },
  { label: 'Claude', value: 'claude' },
]

const apiTypeFilterOptions = computed(() => [
  { label: '全部API类型', value: '' },
  ...apiTypeOptions.map((option: any) => ({ label: option.label, value: option.value })),
])

const pageSizeOptions = [
  { label: '20', value: '20' },
  { label: '50', value: '50' },
  { label: '100', value: '100' },
]

const pageSizeStr = computed({
  get: () => String(pageSize.value),
  set: (value: string) => {
    pageSize.value = Number(value)
  },
})

const basicInfo = computed(() =>
  selectedLog.value
    ? [
        { label: 'Trace ID', value: selectedLog.value.trace_id },
        { label: '调用密钥', value: formatApiKey(selectedLog.value) },
        { label: 'API类型', value: selectedLog.value.api_type },
        { label: '模型', value: selectedLog.value.model || '-' },
        { label: '渠道', value: selectedLog.value.selected_channel_name || '-' },
        { label: '上游地址', value: selectedLog.value.upstream_url || '-' },
        { label: '耗时', value: `${selectedLog.value.latency_ms?.toFixed(0)} ms` },
        { label: '状态码', value: selectedLog.value.status_code },
        { label: '请求时间', value: formatDate(selectedLog.value.created_at) },
      ]
    : []
)

const tokenInfo = computed(() =>
  selectedLog.value
    ? [
        { label: 'Prompt', value: selectedLog.value.prompt_tokens ?? '-' },
        { label: 'Completion', value: selectedLog.value.completion_tokens ?? '-' },
        { label: 'Total', value: selectedLog.value.total_tokens ?? '-' },
        { label: '输入缓存', value: selectedLog.value.cache_tokens ?? '-' },
      ]
    : []
)

function formatDate(d: string) {
  if (!d) return '-'
  return new Date(d).toLocaleString('zh-CN', { hour12: false })
}

function formatJson(raw: string): string {
  if (!raw) return '-'
  try {
    return JSON.stringify(JSON.parse(raw), null, 2)
  } catch {
    return raw
  }
}

function openDetail(log: any) {
  selectedLog.value = log
  drawerVisible.value = true
}

function shortId(value: string) {
  if (!value) return ''
  return value.length > 12 ? `${value.slice(0, 8)}...` : value
}

function formatApiKey(log: any) {
  const name = log?.from_apikey_name || ''
  const id = log?.from_apikey || ''
  if (name && id) return `${name} (${id})`
  return name || id || '-'
}

function renderApiKey(row: any) {
  const name = row.from_apikey_name || ''
  const id = row.from_apikey || ''
  return h('div', { class: 'min-w-32 space-y-0.5' }, [
    h('p', { class: 'font-medium' }, name || id || '-'),
    id ? h('code', { class: 'text-xs text-muted-foreground' }, shortId(id)) : null,
  ])
}

const columns = [
  { title: '请求 / 时间', key: 'trace_id', width: 155, render: (row: any) => h('div', { class: 'table-cell-stack' }, [
    h('code', { title: row.trace_id }, shortId(row.trace_id)),
    h('span', { class: 'secondary-text' }, formatDate(row.created_at)),
  ]) },
  { title: '模型 / 协议', key: 'model', width: 180, render: (row: any) => {
    const model = modelCatalog.value.find(item => item.name === row.model)
    return h('div', { class: 'table-cell-stack' }, [
      h(ModelLabel, { model: row.model, icon: model?.icon, upstreamModels: upstreamModelNames(model) }),
      h('span', { class: 'secondary-text' }, `${row.api_type}${row.thinking_effort ? ` · 思考 ${row.thinking_effort}` : ''}`),
    ])
  } },
  { title: '调用密钥', key: 'from_apikey_name', width: 130, render: renderApiKey },
  { title: '渠道', key: 'selected_channel_name', width: 120 },
  { title: '状态', key: 'status_code', width: 100, render: (row: any) => h('div', { class: 'table-cell-stack' }, [
    h(UiBadge, { variant: row.status_code >= 400 ? 'danger' : 'success' }, { default: () => String(row.status_code) }),
    row.error_message ? h('span', { class: 'table-error secondary-text', title: row.error_message }, row.error_message) : null,
  ]) },
  { title: '耗时', key: 'latency_ms', width: 90, render: (row: any) => `${Math.round(row.latency_ms || 0)} ms` },
  { title: 'Token 用量', key: 'total_tokens', width: 150, render: (row: any) => h('div', { class: 'table-cell-stack' }, [
    h('strong', String(row.total_tokens ?? 0)),
    h('span', { class: 'secondary-text' }, `输入 ${row.prompt_tokens ?? 0} / 输出 ${row.completion_tokens ?? 0}`),
  ]) },
  {
    title: '操作',
    key: 'actions',
    render: (row: any) =>
      h(UiDropdown, null, {
        default: () =>
          h(
            UiDropdownItem,
            { icon: FileSearch, onClick: () => openDetail(row) },
            { default: () => '详情' }
          ),
      }),
  },
]

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const params: any = { page: page.value, page_size: pageSize.value }
    if (filters.value.api_type) params.api_type = filters.value.api_type
    if (filters.value.model) params.model = filters.value.model
    if (filters.value.from_apikey) params.from_apikey = filters.value.from_apikey
    if (filters.value.status !== null && filters.value.status !== undefined)
      params.status = filters.value.status
    const res = await listLogs(params)
    logs.value = res.data || []
    total.value = res.total || 0
  } catch (e) {
    loadError.value = '请求日志加载失败，请检查网络后重试'
  } finally {
    loading.value = false
  }
}

async function changePage(delta: -1 | 1) {
  if (loading.value) return
  pagingDirection.value = delta < 0 ? 'previous' : 'next'
  page.value += delta
  try {
    await load()
  } finally {
    pagingDirection.value = ''
  }
}

watch(pageSize, () => {
  page.value = 1
  load()
})

onMounted(() => {
  void load()
  // Branding is optional; log browsing remains available if the catalog fails.
  void listModels().then(result => { modelCatalog.value = result.data || [] }).catch(() => {})
})
</script>
