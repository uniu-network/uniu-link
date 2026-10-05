<template>
  <div class="page-stack">
    <PageHeader title="仪表盘" description="查看网关运行状况、请求趋势和资源用量。"
      ><UiButton :loading="loading" @click="load"
        ><NavIcon name="refresh" />刷新</UiButton
      ></PageHeader
    >
    <ListState :error="loadError" @retry="load" />
    <UiSpinner v-if="!loadError" :show="loading">
      <div class="metrics">
        <StatCard
          label="近 1 小时请求量"
          :value="formatNumber(stats.total_requests || 0)"
          icon="Activity"
        />
        <StatCard
          label="错误率"
          :value="`${stats.error_rate || 0}%`"
          icon="AlertTriangle"
          :tone="(stats.error_rate || 0) > 5 ? 'danger' : 'success'"
        />
        <StatCard
          label="健康渠道数"
          :value="`${healthyChannels} / ${totalChannels}`"
          icon="Server"
          tone="success"
        />
        <StatCard
          label="近 1 小时 Tokens"
          :value="formatTokens(stats.token_stats?.total_tokens_last_hour || 0)"
          icon="Hash"
          :hint="`累计 ${formatTokens(stats.token_stats?.total_tokens_all || 0)}`"
        />
      </div>
      <div class="dashboard-columns">
        <div class="stack">
          <UiCard title="趋势统计">
            <template #extra
              ><UiSelect
                v-model="chartGranularity"
                :options="granularityOptions"
                aria-label="统计粒度"
            /></template>
            <div class="chart-grid">
              <section class="chart-panel">
                <h3>Token 使用</h3>
                <p class="secondary-text">输入 / 输出 / 总量</p>
                <VueApexCharts
                  v-if="selectedChartData.length"
                  type="area"
                  height="260"
                  :options="tokenChartOptions"
                  :series="tokenSeries"
                /><UiEmpty v-else title="暂无趋势数据" />
              </section>
              <section class="chart-panel">
                <h3>请求数</h3>
                <p class="secondary-text">请求总数与错误请求</p>
                <VueApexCharts
                  v-if="selectedChartData.length"
                  type="bar"
                  height="260"
                  :options="requestChartOptions"
                  :series="requestSeries"
                /><UiEmpty v-else title="暂无趋势数据" />
              </section>
            </div>
          </UiCard>
          <UiCard title="健康渠道趋势"
            ><VueApexCharts
              v-if="selectedChartData.length"
              type="line"
              height="180"
              :options="healthyChannelChartOptions"
              :series="healthyChannelSeries" /><UiEmpty v-else title="暂无趋势数据"
          /></UiCard>
        </div>
        <div class="stack">
          <UiCard title="渠道健康状态">
            <template v-if="stats.channel_health?.length"
              ><div v-for="ch in stats.channel_health" :key="ch.id" class="channel-health-row">
                <div class="channel-health-identity">
                  <ModelIcon :provider="ch.provider" :size="22" />
                  <div class="min-w-0"><p class="truncate text-sm">{{ ch.name }}</p>
                  <p class="secondary-text">{{ ch.provider }}</p></div>
                </div>
                <UiBadge :variant="ch.health_status === 'healthy' ? 'success' : ch.health_status === 'unhealthy' ? 'danger' : 'default'">{{
                  ch.health_status === 'healthy' ? '健康' : ch.health_status === 'unhealthy' ? '异常' : '未知'
                }}</UiBadge>
              </div></template
            >
            <UiEmpty v-else title="暂无渠道数据" />
          </UiCard>
          <UiCard title="概览"
            ><div class="stack">
              <div class="summary-row">
                <span class="secondary-text">总渠道</span><strong>{{ totalChannels }}</strong>
              </div>
              <fluent-divider />
              <div class="summary-row">
                <span class="secondary-text">健康</span
                ><strong class="message-symbol-success">{{ healthyChannels }}</strong>
              </div>
              <fluent-divider />
              <div class="summary-row">
                <span class="secondary-text">异常</span
                ><strong class="message-symbol-error">{{ totalChannels - healthyChannels }}</strong>
              </div>
              <fluent-divider />
              <div class="summary-row">
                <span class="secondary-text">近 24 小时活跃密钥</span
                ><strong>{{ apiKeyStats.length }}</strong>
              </div>
            </div></UiCard
          >
        </div>
      </div>
      <section class="stack">
        <h2>近 24 小时 API Key 调用</h2>
        <UiDataTable :columns="keyColumns" :data="apiKeyStats" label="API Key 调用统计" />
      </section>
    </UiSpinner>
  </div>
</template>

<script setup lang="ts">
import { defineComponent, ref, computed, onMounted, h } from 'vue'
import VueApexCharts from 'vue3-apexcharts'
import type { ApexOptions } from 'apexcharts'
import { Activity, AlertTriangle, Server, Hash } from 'lucide-vue-next'
import { getDashboardStats } from '@/api/stats'
import { useTheme } from '@/composables/useTheme'
import PageHeader from '@/components/PageHeader.vue'
import ListState from '@/components/ListState.vue'
import NavIcon from '@/components/NavIcon.vue'
import ModelIcon from '@/components/ModelIcon.vue'
import { useMediaQuery } from '@vueuse/core'
import UiDataTable from '@/components/ui/UiDataTable.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiBadge from '@/components/ui/UiBadge.vue'
import UiCard from '@/components/ui/UiCard.vue'
import UiEmpty from '@/components/ui/UiEmpty.vue'
import UiSelect from '@/components/ui/UiSelect.vue'
import UiSpinner from '@/components/ui/UiSpinner.vue'

const iconMap: Record<string, any> = { Activity, AlertTriangle, Server, Hash }

const StatCard = defineComponent({
  props: { label: String, value: String, hint: String, tone: String, icon: String },
  setup(props) {
    return () =>
      h(UiCard, { class: 'reveal-item' }, {
        default: () => [
          h('div', { class: 'stat-top' }, [
            h('p', { class: 'secondary-text' }, props.label),
            h('span', { class: 'stat-icon' }, [h(iconMap[props.icon || ''] || 'span', {
              size: 20,
              strokeWidth: 1.5,
              'aria-hidden': true,
              class:
                props.tone === 'danger'
                  ? 'message-symbol-error'
                  : props.tone === 'success'
                    ? 'message-symbol-success'
                    : 'secondary-text',
            })]),
          ]),
          h('p', { class: 'stat-value' }, props.value),
          props.hint ? h('p', { class: 'secondary-text' }, props.hint) : null,
        ],
      })
  },
})

const keyColumns = [
  {
    title: 'API Key',
    key: 'from_apikey',
    render: (row: any) =>
      h('div', null, [
        h('p', row.from_apikey_name || row.from_apikey || '—'),
        row.from_apikey ? h('code', { class: 'secondary-text' }, shortId(row.from_apikey)) : null,
      ]),
  },
  { title: '请求数', key: 'request_count', render: (row: any) => formatNumber(row.request_count) },
  { title: '错误数', key: 'error_count', render: (row: any) => formatNumber(row.error_count) },
  { title: '总 Tokens', key: 'total_tokens', render: (row: any) => formatNumber(row.total_tokens) },
]

const stats = ref<any>({})
const loading = ref(true)
const loadError = ref('')
const chartGranularity = ref<'hourly' | 'daily'>('hourly')
const { isDark } = useTheme()
const reducedMotion = useMediaQuery('(prefers-reduced-motion: reduce)')

const granularityOptions = [
  { label: '按小时', value: 'hourly' },
  { label: '按每日', value: 'daily' },
]

const healthyChannels = computed(
  () => (stats.value.channel_health || []).filter((c: any) => c.health_status === 'healthy').length
)
const totalChannels = computed(() => (stats.value.channel_health || []).length)
const apiKeyStats = computed(() => stats.value.api_key_stats || [])

const tokenFormatter = new Intl.NumberFormat('en-US', {
  notation: 'compact',
  compactDisplay: 'short',
  maximumFractionDigits: 2,
})

function formatTokens(value: number) {
  return tokenFormatter.format(value || 0)
}

function formatNumber(value: number) {
  return new Intl.NumberFormat('zh-CN').format(value || 0)
}

function shortId(value: string) {
  if (!value) return ''
  return value.length > 12 ? `${value.slice(0, 8)}...` : value
}

function formatHour(value: string) {
  if (!value) return ''
  return new Date(value).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    hour12: false,
  })
}

function formatDay(value: string) {
  if (!value) return ''
  return new Date(value).toLocaleDateString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
  })
}

const baseChartOptions = computed<ApexOptions>(() => ({
  chart: {
    animations: { enabled: !reducedMotion.value, speed: 280, animateGradually: { enabled: false }, dynamicAnimation: { enabled: false } },
    toolbar: { show: false },
    zoom: { enabled: false },
    fontFamily: "'Segoe UI', system-ui, sans-serif",
    background: 'transparent',
  },
  theme: { mode: isDark.value ? 'dark' : 'light' },
  dataLabels: { enabled: false },
  stroke: { curve: 'smooth', width: 2 },
  grid: {
    borderColor: isDark.value ? '#383838' : '#e0e0e0',
    strokeDashArray: 4,
  },
  legend: {
    position: 'top',
    horizontalAlign: 'left',
    fontFamily: "'Segoe UI', system-ui, sans-serif",
  },
  tooltip: { theme: isDark.value ? 'dark' : 'light' },
  xaxis: {
    labels: {
      style: {
        colors: isDark.value ? '#ababab' : '#656b76',
        fontFamily: "'Segoe UI', system-ui, sans-serif",
      },
    },
    axisBorder: { show: false },
    axisTicks: { show: false },
  },
  yaxis: {
    labels: {
      style: {
        colors: isDark.value ? '#ababab' : '#656b76',
        fontFamily: "'Segoe UI', system-ui, sans-serif",
      },
      formatter: (value: number) => formatNumber(Math.round(value)),
    },
  },
}))

const tokenChartBaseOptions = computed<ApexOptions>(() => ({
  ...baseChartOptions.value,
  colors: ['#f52d94', '#888888', '#6866ad'],
  tooltip: {
    theme: isDark.value ? 'dark' : 'light',
    y: {
      formatter: (value: number) => `${formatNumber(value)} tokens`,
    },
  },
}))

const selectedChartData = computed(() => stats.value.stats_charts?.[chartGranularity.value] || [])
const chartCategories = computed(() =>
  selectedChartData.value.map((item: any) =>
    chartGranularity.value === 'hourly' ? formatHour(item.time) : formatDay(item.time)
  )
)

const tokenSeries = computed(() => [
  { name: '总 Tokens', data: selectedChartData.value.map((item: any) => item.total_tokens || 0) },
  {
    name: '输入 Tokens',
    data: selectedChartData.value.map((item: any) => item.prompt_tokens || 0),
  },
  {
    name: '输出 Tokens',
    data: selectedChartData.value.map((item: any) => item.completion_tokens || 0),
  },
])

const requestSeries = computed(() => [
  { name: '请求数', data: selectedChartData.value.map((item: any) => item.request_count || 0) },
  { name: '错误数', data: selectedChartData.value.map((item: any) => item.error_count || 0) },
])

const healthyChannelSeries = computed(() => [
  {
    name: '健康渠道数',
    data: selectedChartData.value.map((item: any) => item.healthy_channels || 0),
  },
])

const tokenChartOptions = computed<ApexOptions>(() => ({
  ...tokenChartBaseOptions.value,
  xaxis: {
    categories: chartCategories.value,
    labels: { style: { colors: isDark.value ? '#ababab' : '#656b76' } },
  },
  fill: {
    type: 'solid',
    opacity: 0.08,
  },
}))

const requestChartOptions = computed<ApexOptions>(() => ({
  ...baseChartOptions.value,
  colors: ['#f52d94', isDark.value ? '#ff6b6b' : '#c50f1f'],
  plotOptions: { bar: { borderRadius: 4, columnWidth: '45%' } },
  xaxis: {
    categories: chartCategories.value,
    labels: { style: { colors: isDark.value ? '#ababab' : '#656b76' } },
  },
}))

const healthyChannelChartOptions = computed<ApexOptions>(() => ({
  ...baseChartOptions.value,
  colors: [isDark.value ? '#6ccb5f' : '#107c10'],
  xaxis: {
    categories: chartCategories.value,
    labels: { style: { colors: isDark.value ? '#ababab' : '#656b76' } },
  },
  tooltip: {
    theme: isDark.value ? 'dark' : 'light',
    y: {
      formatter: (value: number) => `${formatNumber(value)} 个渠道`,
    },
  },
}))

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    stats.value = await getDashboardStats()
  } catch (e) {
    loadError.value = '统计数据加载失败，请检查网络后重试'
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>
