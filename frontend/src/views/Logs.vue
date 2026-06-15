<template>
  <div class="space-y-6">
    <UiCard>
      <div class="flex flex-wrap gap-3">
        <select v-model="filters.api_type" class="form-input w-40">
          <option :value="null">全部API类型</option>
          <option v-for="option in apiTypeOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
        </select>
        <input v-model="filters.model" placeholder="模型名称" class="form-input w-40" />
        <input v-model.number="filters.status" type="number" placeholder="状态码" class="form-input w-32" />
        <UiButton variant="primary" :loading="loading" @click="load">查询</UiButton>
      </div>
    </UiCard>

    <UiSpinner :show="loading">
      <UiDataTable :columns="columns" :data="logs" />
      <div class="mt-4 flex items-center justify-center gap-3">
        <UiButton :disabled="page <= 1" @click="page -= 1">上一页</UiButton>
        <span class="text-sm text-muted-foreground">第 {{ page }} 页 / 共 {{ Math.max(1, Math.ceil(total / pageSize)) }} 页</span>
        <UiButton :disabled="page >= Math.ceil(total / pageSize)" @click="page += 1">下一页</UiButton>
        <select v-model.number="pageSize" class="form-input w-24">
          <option :value="20">20</option>
          <option :value="50">50</option>
          <option :value="100">100</option>
        </select>
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
          <p class="text-sm text-red-600 dark:text-red-400">{{ selectedLog.error_message }}</p>
        </UiCard>
        <CodePanel v-if="selectedLog.input_content" title="输入内容" :code="selectedLog.input_content" />
        <CodePanel v-if="selectedLog.output_content" title="输出内容" :code="selectedLog.output_content" />
        <CodePanel v-if="selectedLog.request_body" title="请求体" :code="formatJson(selectedLog.request_body)" />
        <CodePanel v-if="selectedLog.response_body" title="响应体" :code="formatJson(selectedLog.response_body)" />
      </div>
    </UiDrawer>
  </div>
</template>

<script setup lang="ts">
import { computed, defineComponent, ref, onMounted, watch, h } from 'vue'
import { listLogs } from '@/api/logs'
import UiBadge from '@/components/ui/UiBadge.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiCard from '@/components/ui/UiCard.vue'
import UiDataTable from '@/components/ui/UiDataTable.vue'
import UiDrawer from '@/components/ui/UiDrawer.vue'
import UiSpinner from '@/components/ui/UiSpinner.vue'

const InfoGrid = defineComponent({
  props: { items: { type: Array, required: true } },
  setup(props) {
    return () => h('dl', { class: 'grid gap-3 sm:grid-cols-2' }, (props.items as any[]).map((item) => h('div', { class: 'rounded-lg border border-border p-3' }, [
      h('dt', { class: 'text-xs text-muted-foreground' }, item.label),
      h('dd', { class: 'mt-1 break-all text-sm font-medium' }, item.value),
    ])))
  },
})

const CodePanel = defineComponent({
  props: { title: String, code: String },
  setup(props) {
    return () => h(UiCard, { title: props.title }, { default: () => h('pre', { class: 'max-h-80 overflow-auto whitespace-pre-wrap rounded-lg bg-muted p-3 text-xs thin-scrollbar' }, props.code) })
  },
})

const logs = ref<any[]>([])
const loading = ref(true)
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const filters = ref<{ api_type: string | null; model: string; status: number | null }>({ api_type: null, model: '', status: null })

const drawerVisible = ref(false)
const selectedLog = ref<any>(null)

const apiTypeOptions = [
  { label: 'OpenAI', value: 'openai' },
  { label: 'Responses', value: 'responses' },
  { label: 'Claude', value: 'claude' },
]

const basicInfo = computed(() => selectedLog.value ? [
  { label: 'Trace ID', value: selectedLog.value.trace_id },
  { label: 'API类型', value: selectedLog.value.api_type },
  { label: '模型', value: selectedLog.value.model || '-' },
  { label: '渠道', value: selectedLog.value.selected_channel_name || '-' },
  { label: '上游地址', value: selectedLog.value.upstream_url || '-' },
  { label: '耗时', value: `${selectedLog.value.latency_ms?.toFixed(0)} ms` },
  { label: '状态码', value: selectedLog.value.status_code },
  { label: '请求时间', value: formatDate(selectedLog.value.created_at) },
] : [])

const tokenInfo = computed(() => selectedLog.value ? [
  { label: 'Prompt', value: selectedLog.value.prompt_tokens ?? '-' },
  { label: 'Completion', value: selectedLog.value.completion_tokens ?? '-' },
  { label: 'Total', value: selectedLog.value.total_tokens ?? '-' },
  { label: '输入缓存', value: selectedLog.value.cache_tokens ?? '-' },
] : [])

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

const columns = [
  { title: 'Trace ID', key: 'trace_id', render: (row: any) => h('code', { class: 'text-xs text-muted-foreground' }, row.trace_id.slice(0, 8) + '...') },
  { title: 'API类型', key: 'api_type', render: (row: any) => h(UiBadge, { variant: row.api_type === 'openai' ? 'success' : 'info' }, { default: () => row.api_type }) },
  { title: '模型', key: 'model' },
  { title: '思考', key: 'thinking_effort' },
  { title: '渠道', key: 'selected_channel_name' },
  { title: '耗时(ms)', key: 'latency_ms' },
  { title: '请求Token', key: 'prompt_tokens' },
  { title: '响应Token', key: 'completion_tokens' },
  { title: '总Token', key: 'total_tokens' },
  { title: '状态码', key: 'status_code', render: (row: any) => h('span', { class: row.status_code >= 400 ? 'text-red-600 dark:text-red-400' : 'text-emerald-600 dark:text-emerald-400' }, String(row.status_code)) },
  { title: '时间', key: 'created_at' },
  { title: '错误', key: 'error_message', render: (row: any) => h('span', { class: 'text-xs text-red-600 dark:text-red-400' }, row.error_message || '-') },
  { title: '操作', key: 'actions', render: (row: any) => h(UiButton, { size: 'sm', onClick: () => openDetail(row) }, { default: () => '详情' }) },
]

async function load() {
  loading.value = true
  try {
    const params: any = { page: page.value, page_size: pageSize.value }
    if (filters.value.api_type) params.api_type = filters.value.api_type
    if (filters.value.model) params.model = filters.value.model
    if (filters.value.status !== null && filters.value.status !== undefined) params.status = filters.value.status
    const res = await listLogs(params)
    logs.value = res.data || []
    total.value = res.total || 0
  } catch (e) {
    console.error(e)
  } finally {
    loading.value = false
  }
}

watch(page, load)
watch(pageSize, () => { page.value = 1; load() })

onMounted(load)
</script>
