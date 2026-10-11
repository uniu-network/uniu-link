<template>
  <div class="page-stack">
    <PageHeader title="系统配置" description="查看与维护网关的运行配置。"
      ><UiButton :loading="loading" @click="load"><NavIcon name="refresh" />刷新</UiButton
      ><UiButton :loading="reloading" @click="handleReload">从文件重新加载</UiButton></PageHeader
    >

    <ListState :error="loadError" @retry="load" />
    <UiSpinner v-if="!loadError" :show="loading">
      <UiDataTable :columns="columns" :data="rows" label="系统配置" />
    </UiSpinner>

    <UiModal
      v-model:open="editModalVisible"
      :busy="submitting"
      :before-close="beforeClose"
      @save="hasChanges && handleSave()"
      title="编辑配置"
      width="520px"
    >
      <div class="space-y-4 text-sm">
        <div>
          <p class="mb-1 text-muted-foreground">配置项</p>
          <UiBadge>{{ editingKey }}</UiBadge>
        </div>
        <div>
          <p class="mb-1 text-muted-foreground">描述</p>
          <p>{{ editingDescription }}</p>
        </div>
        <UiField label="值">
          <UiInput
            v-if="editingType === 'string'"
            v-model="editingValue"
            :placeholder="String(editingDefault)"
            class="w-full"
          />
          <UiInput
            v-else-if="editingType === 'int'"
            v-model.number="editingValueNum"
            type="number"
            :placeholder="String(editingDefault)"
            class="w-full"
          />
          <UiCheckbox v-else-if="editingType === 'bool'" v-model="editingValueBool"
            >启用</UiCheckbox
          >
          <UiInput
            v-else
            v-model="editingValue"
            :placeholder="String(editingDefault)"
            class="w-full"
          />
        </UiField>
        <div>
          <p class="mb-1 text-muted-foreground">默认值</p>
          <p>{{ editingDefault }}</p>
        </div>
        <div>
          <p class="mb-1 text-muted-foreground">热重载</p>
          <UiBadge :variant="editingHotReloadable ? 'success' : 'warning'">{{
            editingHotReloadable ? '支持' : '需重启'
          }}</UiBadge>
          <p v-if="!editingHotReloadable" class="config-hint">
            保存后会写入配置文件并标记为待生效，需要重启服务（或点击“从文件重新加载”）后才会应用。
          </p>
        </div>
      </div>
      <template #footer>
        <div class="flex justify-end gap-2">
          <UiButton @click="closeEditor">取消</UiButton>
          <UiButton
            variant="primary"
            :loading="submitting"
            :disabled="!hasChanges"
            @click="handleSave"
            >保存</UiButton
          >
        </div>
      </template>
    </UiModal>
  </div>
</template>

<script setup lang="ts">
import { useUnsavedForm } from '@/composables/useUnsavedChanges'
import PageHeader from '@/components/PageHeader.vue'
import ListState from '@/components/ListState.vue'
import NavIcon from '@/components/NavIcon.vue'

import UiField from '@/components/ui/UiField.vue'
import UiInput from '@/components/ui/UiInput.vue'
import UiCheckbox from '@/components/ui/UiCheckbox.vue'
import { ref, computed, onMounted, h } from 'vue'
import { listConfig, updateConfig, reloadConfig } from '@/api/config'
import { useToast } from '@/composables/useFeedback'
import UiBadge from '@/components/ui/UiBadge.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiDataTable from '@/components/ui/UiDataTable.vue'
import UiModal from '@/components/ui/UiModal.vue'
import UiSpinner from '@/components/ui/UiSpinner.vue'

const toast = useToast()
const loading = ref(true)
const loadError = ref('')
const reloading = ref(false)
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

const sectionOrder = [
  { key: 'app', label: '应用设置' },
  { key: 'database', label: '数据库' },
  { key: 'redis', label: 'Redis' },
  { key: 'gateway', label: '网关' },
  { key: 'circuit_breaker', label: '熔断器' },
  { key: 'rate_limit', label: '速率限制' },
  { key: 'logging', label: '日志' },
  { key: 'cpa', label: 'CLIProxyAPI' },
]
const sectionLabels = Object.fromEntries(sectionOrder.map((section) => [section.key, section.label]))
const keyToSection: Record<string, string> = {
  app_name: 'app',
  app_env: 'app',
  encryption_key: 'app',
  admin_api_key: 'app',
  admin_hmac_ttl_seconds: 'app',
  postgres_host: 'database',
  postgres_port: 'database',
  postgres_db: 'database',
  postgres_user: 'database',
  postgres_password: 'database',
  redis_url: 'redis',
  default_channel_timeout: 'gateway',
  default_max_retries: 'gateway',
  health_check_interval: 'gateway',
  circuit_breaker_failure_threshold: 'circuit_breaker',
  circuit_breaker_cooldown_seconds: 'circuit_breaker',
  circuit_breaker_half_open_max_requests: 'circuit_breaker',
  rate_limit_global_rps: 'rate_limit',
  rate_limit_per_key_rps: 'rate_limit',
  rate_limit_per_model_rps: 'rate_limit',
  log_level: 'logging',
  log_file: 'logging',
  raw_json_log: 'logging',
  log_body: 'logging',
  log_content: 'logging',
  cpa_manage_enabled: 'cpa',
  cpa_install_dir: 'cpa',
  cpa_release_repo: 'cpa',
  cpa_download_base_url: 'cpa',
  cpa_start_timeout: 'cpa',
  cpa_quota_plugin_enabled: 'cpa',
}

const rows = computed(() => {
  const grouped: Record<string, any[]> = {}
  for (const [key, meta] of Object.entries(configData.value)) {
    const section = keyToSection[key] || 'app'
    ;(grouped[section] ||= []).push({ key, group: section, ...meta })
  }
  return sectionOrder.flatMap((section) => grouped[section.key] || [])
})

const columns = [
  {
    title: '分组',
    key: 'group',
    width: 110,
    render: (row: any) => sectionLabels[row.group] || row.group,
  },
  { title: '配置项', key: 'key', width: 220 },
  {
    title: '值',
    key: 'value',
    render: (row: any) =>
      h('div', { class: 'config-value' }, [
        row.sensitive
          ? h(UiBadge, { variant: 'warning' }, { default: () => row.value })
          : row.type === 'bool'
            ? h(
                UiBadge,
                { variant: row.value ? 'success' : 'default' },
                { default: () => (row.value ? '是' : '否') }
              )
            : h('span', { class: 'config-value-text' }, String(row.value)),
        row.pending_restart
          ? h(UiBadge, { variant: 'info' }, { default: () => '待重启生效' })
          : null,
      ]),
  },
  { title: '类型', key: 'type', width: 80 },
  {
    title: '热重载',
    key: 'hot_reloadable',
    width: 90,
    render: (row: any) =>
      h(
        'span',
        { class: row.hot_reloadable ? 'secondary-text' : 'config-restart' },
        row.hot_reloadable ? '是' : '需重启'
      ),
  },
  { title: '说明', key: 'description' },
  {
    title: '操作',
    key: 'actions',
    width: 80,
    render: (row: any) =>
      row.sensitive && !row.hot_reloadable
        ? h('span', { class: 'secondary-text' }, '仅配置文件')
        : h(
            UiButton,
            { variant: 'link', onClick: () => openEdit(row) },
            { default: () => '编辑' }
          ),
  },
]

function openEdit(row: any) {
  editingKey.value = row.key
  editingDescription.value = row.description || ''
  editingType.value = row.type
  editingDefault.value = row.default
  editingHotReloadable.value = row.hot_reloadable
  editingOriginalValue.value = row.sensitive ? ((row as any)._rawValue ?? row.value) : row.value
  if (row.type === 'int') editingValueNum.value = Number(editingOriginalValue.value)
  else if (row.type === 'bool') editingValueBool.value = !!editingOriginalValue.value
  else editingValue.value = String(editingOriginalValue.value)
  editModalVisible.value = true
}

async function handleSave() {
  const val =
    editingType.value === 'int'
      ? editingValueNum.value
      : editingType.value === 'bool'
        ? editingValueBool.value
        : editingValue.value
  try {
    submitting.value = true
    const result = await updateConfig(editingKey.value, val)
    if (result?.restart_required) {
      toast.warning(`「${editingKey.value}」已写入配置文件，重启后生效`)
    } else if (result && result.persisted === false) {
      toast.warning(`「${editingKey.value}」已生效，但未写入配置文件：${result.persist_error || '未知原因'}`)
    } else {
      toast.success(`「${editingKey.value}」已更新`)
    }
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
  loadError.value = ''
  try {
    configData.value = (await listConfig()) || {}
  } catch (e) {
    loadError.value = '系统配置加载失败，请检查网络后重试'
  } finally {
    loading.value = false
  }
}

const { beforeClose, closeEditor } = useUnsavedForm(
  editModalVisible,
  () => ({
    value: editingValue.value,
    number: editingValueNum.value,
    bool: editingValueBool.value,
  }),
  submitting
)

onMounted(load)
</script>

<style scoped>
.config-value {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  min-width: 0;
}
.config-value-text {
  display: block;
  max-width: 20rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.config-hint {
  margin-top: 0.375rem;
  font-size: 0.75rem;
  color: var(--sidebar-muted);
}
.config-restart {
  color: var(--sidebar-muted);
}
</style>
