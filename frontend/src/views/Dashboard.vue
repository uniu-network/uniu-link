<template>
  <UiSpinner :show="loading">
    <div class="space-y-6">
      <div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        <StatCard label="近1小时请求量" :value="formatNumber(stats.total_requests || 0)" />
        <StatCard label="错误率" :value="`${stats.error_rate || 0}%`" :tone="(stats.error_rate || 0) > 5 ? 'danger' : 'success'" />
        <StatCard label="缓存命中率" :value="`${stats.cache_hit_rate || 0}%`" tone="info" />
        <StatCard label="健康渠道数" :value="`${healthyChannels} / ${totalChannels}`" tone="success" />
        <StatCard label="近1小时 Tokens" :value="formatNumber(stats.token_stats?.total_tokens_last_hour || 0)" :hint="`累计 ${formatNumber(stats.token_stats?.total_tokens_all || 0)}`" />
      </div>

      <UiCard title="趋势统计">
        <template #extra>
          <select v-model="chartGranularity" class="h-9 rounded-md border border-input bg-background px-3 text-sm outline-none focus:ring-2 focus:ring-ring">
            <option v-for="option in granularityOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
          </select>
        </template>
        <div class="grid gap-5 xl:grid-cols-3">
          <section>
            <h3 class="text-sm font-semibold">Token 使用</h3>
            <p class="mb-3 text-xs text-muted-foreground">输入 / 输出 / 总量</p>
            <VueApexCharts type="area" height="280" :options="tokenChartOptions" :series="tokenSeries" />
          </section>
          <section>
            <h3 class="text-sm font-semibold">请求数</h3>
            <p class="mb-3 text-xs text-muted-foreground">请求总数与错误请求</p>
            <VueApexCharts type="bar" height="280" :options="requestChartOptions" :series="requestSeries" />
          </section>
          <section>
            <h3 class="text-sm font-semibold">健康渠道数</h3>
            <p class="mb-3 text-xs text-muted-foreground">周期内成功服务请求的渠道数</p>
            <VueApexCharts type="line" height="280" :options="healthyChannelChartOptions" :series="healthyChannelSeries" />
          </section>
        </div>
      </UiCard>

      <UiCard title="渠道健康状态">
        <div v-if="stats.channel_health?.length" class="divide-y divide-border">
          <div v-for="ch in stats.channel_health" :key="ch.id" class="flex items-center justify-between gap-4 py-3">
            <div class="flex items-center gap-3">
              <span class="h-2.5 w-2.5 rounded-full" :class="ch.health_status === 'healthy' ? 'bg-emerald-500' : 'bg-red-500'" />
              <div>
                <p class="text-sm font-medium">{{ ch.name }}</p>
                <p class="text-xs text-muted-foreground">{{ ch.provider }} · {{ ch.circuit_state }}</p>
              </div>
            </div>
            <UiBadge :variant="ch.health_status === 'healthy' ? 'success' : 'danger'">
              {{ ch.health_status === 'healthy' ? '健康' : '异常' }}
            </UiBadge>
          </div>
        </div>
        <UiEmpty v-else title="暂无渠道数据" />
      </UiCard>

      <UiCard title="缓存命中率详情" :padded="false">
        <UiDataTable :columns="cacheColumns" :data="stats.cache_stats?.models || []" />
      </UiCard>
    </div>
  </UiSpinner>
</template>

<script setup lang="ts">
import { defineComponent, ref, computed, onMounted, h } from 'vue'
import VueApexCharts from 'vue3-apexcharts'
import type { ApexOptions } from 'apexcharts'
import { getDashboardStats } from '@/api/stats'
import { useTheme } from '@/composables/useTheme'
import UiBadge from '@/components/ui/UiBadge.vue'
import UiCard from '@/components/ui/UiCard.vue'
import UiDataTable from '@/components/ui/UiDataTable.vue'
import UiEmpty from '@/components/ui/UiEmpty.vue'
import UiSpinner from '@/components/ui/UiSpinner.vue'

const StatCard = defineComponent({
  props: { label: String, value: String, hint: String, tone: String },
  setup(props) {
    return () => h('div', { class: 'rounded-xl border border-border bg-card p-5 shadow-sm transition-all duration-200 hover:-translate-y-0.5 hover:shadow-vercel-sm' }, [
      h('p', { class: 'text-xs text-muted-foreground' }, props.label),
      h('p', { class: ['mt-2 text-2xl font-semibold tracking-tight', props.tone === 'danger' ? 'text-red-600 dark:text-red-400' : props.tone === 'success' ? 'text-emerald-600 dark:text-emerald-400' : props.tone === 'info' ? 'text-blue-600 dark:text-blue-400' : ''] }, props.value),
      props.hint ? h('p', { class: 'mt-1 text-xs text-muted-foreground' }, props.hint) : null,
    ])
  },
})

const stats = ref<any>({})
const loading = ref(true)
const chartGranularity = ref<'hourly' | 'daily'>('hourly')
const { isDark } = useTheme()

const granularityOptions = [
  { label: '按小时', value: 'hourly' },
  { label: '按每日', value: 'daily' },
]

const healthyChannels = computed(() =>
  (stats.value.channel_health || []).filter((c: any) => c.health_status === 'healthy').length
)
const totalChannels = computed(() => (stats.value.channel_health || []).length)

function formatNumber(value: number) {
  return new Intl.NumberFormat('zh-CN').format(value || 0)
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
    toolbar: { show: false },
    zoom: { enabled: false },
    fontFamily: 'Inter, ui-sans-serif, system-ui, sans-serif',
    background: 'transparent',
  },
  theme: { mode: isDark.value ? 'dark' : 'light' },
  dataLabels: { enabled: false },
  stroke: { curve: 'smooth', width: 2 },
  grid: { borderColor: isDark.value ? '#333' : '#eef2f7' },
  legend: { position: 'top', horizontalAlign: 'left' },
  tooltip: { theme: isDark.value ? 'dark' : 'light' },
  xaxis: {
    labels: { style: { colors: isDark.value ? '#ccc' : '#666' } },
  },
  yaxis: {
    labels: {
      style: { colors: isDark.value ? '#ccc' : '#666' },
      formatter: (value: number) => formatNumber(Math.round(value)),
    },
  },
}))

const tokenChartBaseOptions = computed<ApexOptions>(() => ({
  ...baseChartOptions.value,
  colors: ['#8b5cf6', '#22c55e', '#f97316'],
  tooltip: {
    theme: isDark.value ? 'dark' : 'light',
    y: {
      formatter: (value: number) => `${formatNumber(value)} tokens`,
    },
  },
}))

const selectedChartData = computed(() => stats.value.stats_charts?.[chartGranularity.value] || [])
const chartCategories = computed(() => selectedChartData.value.map((item: any) => (
  chartGranularity.value === 'hourly' ? formatHour(item.time) : formatDay(item.time)
)))

const tokenSeries = computed(() => [
  { name: '总 Tokens', data: selectedChartData.value.map((item: any) => item.total_tokens || 0) },
  { name: '输入 Tokens', data: selectedChartData.value.map((item: any) => item.prompt_tokens || 0) },
  { name: '输出 Tokens', data: selectedChartData.value.map((item: any) => item.completion_tokens || 0) },
])

const requestSeries = computed(() => [
  { name: '请求数', data: selectedChartData.value.map((item: any) => item.request_count || 0) },
  { name: '错误数', data: selectedChartData.value.map((item: any) => item.error_count || 0) },
])

const healthyChannelSeries = computed(() => [
  { name: '健康渠道数', data: selectedChartData.value.map((item: any) => item.healthy_channels || 0) },
])

const tokenChartOptions = computed<ApexOptions>(() => ({
  ...tokenChartBaseOptions.value,
  xaxis: {
    categories: chartCategories.value,
    labels: { style: { colors: isDark.value ? '#ccc' : '#666' } },
  },
  fill: {
    type: 'gradient',
    gradient: { shadeIntensity: 1, opacityFrom: 0.25, opacityTo: 0.02, stops: [0, 90, 100] },
  },
}))

const requestChartOptions = computed<ApexOptions>(() => ({
  ...baseChartOptions.value,
  colors: ['#2563eb', '#ef4444'],
  plotOptions: { bar: { borderRadius: 6, columnWidth: '45%' } },
  xaxis: {
    categories: chartCategories.value,
    labels: { style: { colors: isDark.value ? '#ccc' : '#666' } },
  },
}))

const healthyChannelChartOptions = computed<ApexOptions>(() => ({
  ...baseChartOptions.value,
  colors: ['#16a34a'],
  xaxis: {
    categories: chartCategories.value,
    labels: { style: { colors: isDark.value ? '#ccc' : '#666' } },
  },
  tooltip: {
    theme: isDark.value ? 'dark' : 'light',
    y: {
      formatter: (value: number) => `${formatNumber(value)} 个渠道`,
    },
  },
}))

const cacheColumns = [
  { title: '模型', key: 'model' },
  { title: '命中', key: 'hit', align: 'right' as const },
  { title: '未命中', key: 'miss', align: 'right' as const },
  { title: '总计', key: 'total', align: 'right' as const },
  {
    title: '命中率',
    key: 'hit_rate',
    align: 'right' as const,
    render(row: any) {
      return h(UiBadge, {
        variant: (row.hit_rate || 0) >= 50 ? 'success' : 'warning',
      }, { default: () => `${row.hit_rate}%` })
    },
  },
]

async function load() {
  loading.value = true
  try {
    stats.value = await getDashboardStats()
  } catch (e) {
    console.error(e)
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>
