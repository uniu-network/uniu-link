<template>
  <div class="space-y-6">
    <div class="flex justify-end gap-2">
      <UiBadge v-if="reloadSuccess" variant="success">已从文件重新加载</UiBadge>
      <UiButton :loading="reloading" @click="handleReload"><RefreshCw class="h-4 w-4" />从文件重新加载</UiButton>
    </div>

    <UiSpinner :show="loading">
      <div class="space-y-3">
        <UiCard v-for="section in sections" :key="section.key" :title="section.label" :padded="false">
          <UiDataTable :columns="columns" :data="section.items" />
        </UiCard>
      </div>
    </UiSpinner>

    <UiModal v-model:open="editModalVisible" title="编辑配置" width="520px">
      <div class="space-y-4 text-sm">
        <div><p class="mb-1 text-muted-foreground">配置项</p><UiBadge>{{ editingKey }}</UiBadge></div>
        <div><p class="mb-1 text-muted-foreground">描述</p><p>{{ editingDescription }}</p></div>
        <label class="block space-y-2 font-medium">
          <span>值</span>
          <input v-if="editingType === 'string'" v-model="editingValue" :placeholder="String(editingDefault)" class="form-input w-full" />
          <input v-else-if="editingType === 'int'" v-model.number="editingValueNum" type="number" :placeholder="String(editingDefault)" class="form-input w-full" />
          <label v-else-if="editingType === 'bool'" class="flex items-center gap-2"><input v-model="editingValueBool" type="checkbox" class="h-4 w-4" />启用</label>
          <input v-else v-model="editingValue" :placeholder="String(editingDefault)" class="form-input w-full" />
        </label>
        <div><p class="mb-1 text-muted-foreground">默认值</p><p>{{ editingDefault }}</p></div>
        <div><p class="mb-1 text-muted-foreground">热重载</p><UiBadge :variant="editingHotReloadable ? 'success' : 'warning'">{{ editingHotReloadable ? '支持' : '需重启' }}</UiBadge></div>
      </div>
      <template #footer>
        <div class="flex justify-end gap-2">
          <UiButton @click="editModalVisible = false">取消</UiButton>
          <UiButton variant="primary" :loading="submitting" :disabled="!hasChanges" @click="handleSave">保存</UiButton>
        </div>
      </template>
    </UiModal>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, h } from 'vue'
import { RefreshCw } from 'lucide-vue-next'
import { listConfig, updateConfig, reloadConfig } from '@/api/config'
import { useToast } from '@/composables/useFeedback'
import UiBadge from '@/components/ui/UiBadge.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiCard from '@/components/ui/UiCard.vue'
import UiDataTable from '@/components/ui/UiDataTable.vue'
import UiModal from '@/components/ui/UiModal.vue'
import UiSpinner from '@/components/ui/UiSpinner.vue'

const toast = useToast()
const loading = ref(true)
const reloading = ref(false)
const reloadSuccess = ref(false)
const submitting = ref(false)
const editModalVisible = ref(false)

const configData = ref<Record<string, any>>({})
const editingKey = ref('')
const editingDescription = ref('')
const editingType = ref('string')
const editingDefault = ref<any>('')
const editingHotReloadable = ref(false)
const editingOriginalValue = ref<any>(null)
const editingValue = ref<any>('')
const editingValueNum = ref<number | null>(null)
const editingValueBool = ref<boolean>(false)

const hasChanges = computed(() => {
  if (editingType.value === 'int') return editingValueNum.value !== editingOriginalValue.value
  if (editingType.value === 'bool') return editingValueBool.value !== editingOriginalValue.value
  return editingValue.value !== editingOriginalValue.value
})

const sections = computed(() => {
  const sectionMap: Record<string, { key: string; label: string; items: any[] }> = {
    app: { key: 'app', label: '应用设置', items: [] },
    database: { key: 'database', label: '数据库', items: [] },
    redis: { key: 'redis', label: 'Redis', items: [] },
    gateway: { key: 'gateway', label: '网关', items: [] },
    circuit_breaker: { key: 'circuit_breaker', label: '熔断器', items: [] },
    rate_limit: { key: 'rate_limit', label: '速率限制', items: [] },
    cache: { key: 'cache', label: '缓存', items: [] },
    logging: { key: 'logging', label: '日志', items: [] },
  }
  const keyToSection: Record<string, string> = {
    app_name: 'app', app_env: 'app', encryption_key: 'app', admin_api_key: 'app', admin_hmac_ttl_seconds: 'app',
    postgres_host: 'database', postgres_port: 'database', postgres_db: 'database', postgres_user: 'database', postgres_password: 'database', redis_url: 'redis',
    default_channel_timeout: 'gateway', default_max_retries: 'gateway', health_check_interval: 'gateway', circuit_breaker_failure_threshold: 'circuit_breaker', circuit_breaker_cooldown_seconds: 'circuit_breaker', circuit_breaker_half_open_max_requests: 'circuit_breaker',
    rate_limit_global_rps: 'rate_limit', rate_limit_per_key_rps: 'rate_limit', rate_limit_per_model_rps: 'rate_limit', cache_default_ttl: 'cache', log_level: 'logging', log_file: 'logging', raw_json_log: 'logging', log_body: 'logging', log_content: 'logging',
  }
  for (const [key, meta] of Object.entries(configData.value)) {
    const section = sectionMap[keyToSection[key] || 'app']
    if (section) section.items.push({ key, ...meta })
  }
  return Object.values(sectionMap).filter((section) => section.items.length > 0)
})

const columns = [
  { title: '配置项', key: 'key' },
  { title: '值', key: 'value', render: (row: any) => row.sensitive ? h(UiBadge, { variant: 'warning' }, { default: () => row.value }) : row.type === 'bool' ? h(UiBadge, { variant: row.value ? 'success' : 'default' }, { default: () => row.value ? '是' : '否' }) : h('span', { class: 'block max-w-80 truncate' }, String(row.value)) },
  { title: '类型', key: 'type', render: (row: any) => h(UiBadge, null, { default: () => row.type }) },
  { title: '热重载', key: 'hot_reloadable', render: (row: any) => h(UiBadge, { variant: row.hot_reloadable ? 'success' : 'warning' }, { default: () => row.hot_reloadable ? '是' : '否' }) },
  { title: '说明', key: 'description' },
  { title: '操作', key: 'actions', render: (row: any) => row.sensitive && !row.hot_reloadable ? null : h(UiButton, { variant: 'link', size: 'sm', onClick: () => openEdit(row) }, { default: () => '编辑' }) },
]

function openEdit(row: any) {
  editingKey.value = row.key
  editingDescription.value = row.description || ''
  editingType.value = row.type
  editingDefault.value = row.default
  editingHotReloadable.value = row.hot_reloadable
  editingOriginalValue.value = row.sensitive ? (row as any)._rawValue ?? row.value : row.value
  if (row.type === 'int') editingValueNum.value = Number(editingOriginalValue.value)
  else if (row.type === 'bool') editingValueBool.value = !!editingOriginalValue.value
  else editingValue.value = String(editingOriginalValue.value)
  editModalVisible.value = true
}

async function handleSave() {
  const val = editingType.value === 'int' ? editingValueNum.value : editingType.value === 'bool' ? editingValueBool.value : editingValue.value
  try {
    submitting.value = true
    await updateConfig(editingKey.value, val)
    toast.success(`「${editingKey.value}」已更新`)
    editModalVisible.value = false
    await load()
  } catch (e: any) {
    toast.error(e?.response?.data?.detail || '更新失败')
  } finally {
    submitting.value = false
  }
}

async function handleReload() {
  try {
    reloading.value = true
    await reloadConfig()
    reloadSuccess.value = true
    setTimeout(() => { reloadSuccess.value = false }, 3000)
    await load()
    toast.success('配置已从文件重新加载')
  } catch (e: any) {
    toast.error(e?.response?.data?.detail || '重新加载失败')
  } finally {
    reloading.value = false
  }
}

async function load() {
  loading.value = true
  try {
    configData.value = await listConfig() || {}
  } catch (e) {
    console.error(e)
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>
