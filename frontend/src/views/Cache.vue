<template>
  <div class="space-y-6">
    <div class="flex justify-end gap-2">
      <input v-model="clearModel" placeholder="指定模型（留空清除全部）" class="h-9 w-64 rounded-md border border-input bg-background px-3 text-sm outline-none focus:ring-2 focus:ring-ring" />
      <UiButton variant="danger" :loading="clearing" @click="handleClear">清除缓存</UiButton>
    </div>

    <UiSpinner :show="loading">
      <div class="space-y-6">
        <div class="grid gap-3 sm:grid-cols-3">
          <StatCard label="总模型缓存数" :value="stats.models?.length || 0" />
          <StatCard label="总缓存命中" :value="totalHits" tone="success" />
          <StatCard label="总缓存未命中" :value="totalMisses" />
        </div>

        <UiCard title="各模型缓存统计" :padded="false">
          <UiDataTable :columns="columns" :data="stats.models || []" />
        </UiCard>
      </div>
    </UiSpinner>
  </div>
</template>

<script setup lang="ts">
import { defineComponent, ref, computed, onMounted, h } from 'vue'
import { getCacheStats, clearCache } from '@/api/stats'
import { useConfirm } from '@/composables/useFeedback'
import UiBadge from '@/components/ui/UiBadge.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiCard from '@/components/ui/UiCard.vue'
import UiDataTable from '@/components/ui/UiDataTable.vue'
import UiSpinner from '@/components/ui/UiSpinner.vue'

const StatCard = defineComponent({
  props: { label: String, value: [String, Number], tone: String },
  setup(props) {
    return () => h('div', { class: 'rounded-xl border border-border bg-card p-5 shadow-sm transition-all duration-200 hover:-translate-y-0.5 hover:shadow-vercel-sm' }, [
      h('p', { class: 'text-xs text-muted-foreground' }, props.label),
      h('p', { class: ['mt-2 text-2xl font-semibold tracking-tight', props.tone === 'success' ? 'text-emerald-600 dark:text-emerald-400' : ''] }, String(props.value ?? 0)),
    ])
  },
})

const stats = ref<any>({})
const loading = ref(true)
const clearing = ref(false)
const clearingModel = ref('')
const clearModel = ref('')
const confirm = useConfirm()

const totalHits = computed(() =>
  (stats.value.models || []).reduce((sum: number, m: any) => sum + (m.hit || 0), 0)
)
const totalMisses = computed(() =>
  (stats.value.models || []).reduce((sum: number, m: any) => sum + (m.miss || 0), 0)
)

const columns = [
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
  {
    title: '操作',
    key: 'actions',
    align: 'center' as const,
    render(row: any) {
      return h(UiButton, {
        variant: 'link',
        size: 'sm',
        loading: clearingModel.value === row.model,
        onClick: () => clearByModel(row.model),
      }, { default: () => '清除' })
    },
  },
]

async function load() {
  loading.value = true
  try {
    stats.value = await getCacheStats()
  } catch (e) {
    console.error(e)
  } finally {
    loading.value = false
  }
}

async function handleClear() {
  const ok = await confirm({
    title: '确认清除',
    content: clearModel.value ? `确定清除模型 ${clearModel.value} 的缓存吗？` : '确定清除所有缓存吗？',
    positiveText: '确定',
    negativeText: '取消',
    variant: 'danger',
  })
  if (!ok) return
  clearing.value = true
  try {
    await clearCache(clearModel.value || undefined)
    clearModel.value = ''
    await load()
  } catch (e) {
    console.error(e)
  } finally {
    clearing.value = false
  }
}

async function clearByModel(model: string) {
  const ok = await confirm({
    title: '确认清除',
    content: `确定清除模型 ${model} 的缓存吗？`,
    positiveText: '确定',
    negativeText: '取消',
    variant: 'danger',
  })
  if (!ok) return
  clearingModel.value = model
  try {
    await clearCache(model)
    await load()
  } catch (e) {
    console.error(e)
  } finally {
    clearingModel.value = ''
  }
}

onMounted(load)
</script>
