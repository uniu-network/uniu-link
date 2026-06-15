<template>
  <div class="space-y-6">
    <div class="flex justify-end">
      <UiButton variant="primary" @click="openCreate">+ 新建插件</UiButton>
    </div>

    <UiSpinner :show="loading">
      <UiDataTable :columns="columns" :data="plugins" />
    </UiSpinner>

    <UiModal v-model:open="dialogVisible" :title="isEditing ? '编辑插件' : '新建插件'" width="600px">
      <div class="space-y-4">
        <label class="block space-y-2 text-sm font-medium">
          <span>名称</span>
          <input v-model="form.name" placeholder="请输入插件名称" class="form-input" />
        </label>
        <label class="block space-y-2 text-sm font-medium">
          <span>钩子类型</span>
          <select v-model="form.hook_type" class="form-input">
            <option v-for="option in hookTypeOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
          </select>
        </label>
        <label class="block space-y-2 text-sm font-medium">
          <span>模块路径</span>
          <input v-model="form.module_path" placeholder="app.plugins.builtin_logging.LoggingPlugin" class="form-input" />
        </label>
        <label class="block space-y-2 text-sm font-medium">
          <span>优先级</span>
          <input v-model.number="form.priority" type="number" class="form-input" />
        </label>
        <label class="block space-y-2 text-sm font-medium">
          <span>配置 (JSON)</span>
          <textarea v-model="form.config_json" rows="4" placeholder="{}" class="form-input min-h-24 py-2" />
        </label>
      </div>
      <template #footer>
        <div class="flex justify-end gap-2">
          <UiButton @click="dialogVisible = false">取消</UiButton>
          <UiButton variant="primary" :loading="submitting" @click="submitForm">保存</UiButton>
        </div>
      </template>
    </UiModal>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, h } from 'vue'
import { listPlugins, createPlugin, updatePlugin, deletePlugin, togglePlugin } from '@/api/plugins'
import { useConfirm, useToast } from '@/composables/useFeedback'
import UiBadge from '@/components/ui/UiBadge.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiDataTable from '@/components/ui/UiDataTable.vue'
import UiModal from '@/components/ui/UiModal.vue'
import UiSpinner from '@/components/ui/UiSpinner.vue'

const toast = useToast()
const confirm = useConfirm()

const plugins = ref<any[]>([])
const loading = ref(true)
const dialogVisible = ref(false)
const isEditing = ref(false)
const submitting = ref(false)
const deletingId = ref('')
const togglingId = ref('')
const form = ref<any>({ name: '', hook_type: 'pre_route', module_path: '', priority: 0, enabled: true, config_json: '{}' })

const hookTypeOptions = [
  { label: 'pre_route', value: 'pre_route' },
  { label: 'on_channel_select', value: 'on_channel_select' },
  { label: 'pre_request', value: 'pre_request' },
  { label: 'post_response', value: 'post_response' },
  { label: 'on_error', value: 'on_error' },
  { label: 'post_send', value: 'post_send' },
]

const columns = [
  { title: '名称', key: 'name' },
  {
    title: '钩子类型',
    key: 'hook_type',
    render(row: any) {
      return h(UiBadge, null, { default: () => row.hook_type })
    },
  },
  { title: '优先级', key: 'priority' },
  { title: '模块路径', key: 'module_path' },
  {
    title: '状态',
    key: 'enabled',
    render(row: any) {
      return h(UiButton, {
        size: 'sm',
        variant: row.enabled ? 'primary' : 'default',
        loading: togglingId.value === row.id,
        onClick: () => toggle(row.id),
      }, { default: () => togglingId.value === row.id ? '处理中' : (row.enabled ? '启用' : '禁用') })
    },
  },
  {
    title: '操作',
    key: 'actions',
    render(row: any) {
      return h('div', { class: 'flex gap-2' }, [
        h(UiButton, { variant: 'link', size: 'sm', onClick: () => openEdit(row) }, { default: () => '编辑' }),
        h(UiButton, { variant: 'link', size: 'sm', loading: deletingId.value === row.id, onClick: () => deleteItem(row.id) }, { default: () => deletingId.value === row.id ? '删除中' : '删除' }),
      ])
    },
  },
]

async function load() {
  loading.value = true
  try {
    const res = await listPlugins()
    plugins.value = res.data || []
  } catch (e) {
    console.error(e)
  } finally {
    loading.value = false
  }
}

function openCreate() {
  isEditing.value = false
  form.value = { name: '', hook_type: 'pre_route', module_path: '', priority: 0, enabled: true, config_json: '{}' }
  dialogVisible.value = true
}

function openEdit(p: any) {
  isEditing.value = true
  form.value = { ...p, config_json: JSON.stringify(p.config || {}, null, 2) }
  dialogVisible.value = true
}

async function submitForm() {
  const data = { ...form.value }
  try {
    data.config = JSON.parse(data.config_json || '{}')
  } catch {
    toast.warning('配置JSON格式错误')
    return
  }
  delete data.config_json

  try {
    submitting.value = true
    if (isEditing.value) await updatePlugin(data.id, data)
    else await createPlugin(data)
    dialogVisible.value = false
    await load()
  } catch (e) {
    console.error(e)
  } finally {
    submitting.value = false
  }
}

async function deleteItem(id: string) {
  const ok = await confirm({ title: '确认删除', content: '确定删除该插件吗？', positiveText: '确定', negativeText: '取消', variant: 'danger' })
  if (!ok) return
  deletingId.value = id
  try {
    await deletePlugin(id)
    await load()
  } catch (e) {
    console.error(e)
  } finally {
    deletingId.value = ''
  }
}

async function toggle(id: string) {
  try {
    togglingId.value = id
    await togglePlugin(id)
    await load()
  } catch (e) {
    console.error(e)
  } finally {
    togglingId.value = ''
  }
}

onMounted(load)
</script>
