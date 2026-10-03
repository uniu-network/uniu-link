<template>
  <div class="page-stack">
    <PageHeader title="插件管理" description="管理请求生命周期中的扩展插件。"
      ><UiButton :loading="loading" @click="load"><NavIcon name="refresh" />刷新</UiButton
      ><UiButton variant="primary" @click="openCreate"
        ><NavIcon name="plus" />新建插件</UiButton
      ></PageHeader
    >

    <ListState :error="loadError" @retry="load" />
    <UiSpinner v-if="!loadError" :show="loading">
      <UiDataTable :columns="columns" :data="plugins" />
    </UiSpinner>

    <UiModal
      v-model:open="dialogVisible"
      :busy="submitting"
      :before-close="beforeClose"
      @save="submitForm"
      :title="isEditing ? '编辑插件' : '新建插件'"
      width="600px"
    >
      <div class="space-y-4">
        <UiField label="名称">
          <UiInput v-model="form.name" placeholder="请输入插件名称" class="w-full" />
        </UiField>
        <UiField label="钩子类型">
          <UiSelect v-model="form.hook_type" :options="hookTypeOptions" class="w-full" />
        </UiField>
        <UiField label="模块路径">
          <UiInput
            v-model="form.module_path"
            placeholder="app.plugins.builtin_logging.LoggingPlugin"
            class="w-full"
          />
        </UiField>
        <UiField label="优先级">
          <UiInput v-model.number="form.priority" type="number" class="w-full" />
        </UiField>
        <UiField label="配置 (JSON)">
          <UiTextarea v-model="form.config_json" rows="4" placeholder="{}" class="w-full" />
        </UiField>
      </div>
      <template #footer>
        <div class="flex justify-end gap-2">
          <UiButton @click="closeEditor">取消</UiButton>
          <UiButton variant="primary" :loading="submitting" @click="submitForm">保存</UiButton>
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
import UiTextarea from '@/components/ui/UiTextarea.vue'
import { ref, onMounted, h } from 'vue'
import { listPlugins, createPlugin, updatePlugin, deletePlugin, togglePlugin } from '@/api/plugins'
import { useConfirm, useToast } from '@/composables/useFeedback'
import UiBadge from '@/components/ui/UiBadge.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiDataTable from '@/components/ui/UiDataTable.vue'
import UiDropdown from '@/components/ui/UiDropdown.vue'
import UiDropdownItem from '@/components/ui/UiDropdownItem.vue'
import UiModal from '@/components/ui/UiModal.vue'
import UiSelect from '@/components/ui/UiSelect.vue'
import UiSpinner from '@/components/ui/UiSpinner.vue'
import { Pencil, Trash2, Power } from 'lucide-vue-next'

const toast = useToast()
const confirm = useConfirm()

const plugins = ref<any[]>([])
const loading = ref(true)
const loadError = ref('')
const dialogVisible = ref(false)
const isEditing = ref(false)
const submitting = ref(false)
const deletingId = ref('')
const togglingId = ref('')
const form = ref<any>({
  name: '',
  hook_type: 'pre_route',
  module_path: '',
  priority: 0,
  enabled: true,
  config_json: '{}',
})

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
      return h(
        UiButton,
        {
          size: 'sm',
          variant: row.enabled ? 'primary' : 'default',
          loading: togglingId.value === row.id,
          onClick: () => toggle(row.id),
        },
        { default: () => (togglingId.value === row.id ? '处理中' : row.enabled ? '启用' : '禁用') }
      )
    },
  },
  {
    title: '操作',
    key: 'actions',
    render(row: any) {
      return h(UiDropdown, null, {
        default: () => [
          h(
            UiDropdownItem,
            { icon: Power, loading: togglingId.value === row.id, onClick: () => toggle(row.id) },
            {
              default: () =>
                togglingId.value === row.id ? '处理中' : row.enabled ? '禁用' : '启用',
            }
          ),
          h(
            UiDropdownItem,
            { icon: Pencil, onClick: () => openEdit(row) },
            { default: () => '编辑' }
          ),
          h(
            UiDropdownItem,
            {
              icon: Trash2,
              variant: 'danger',
              loading: deletingId.value === row.id,
              onClick: () => deleteItem(row.id),
            },
            { default: () => (deletingId.value === row.id ? '删除中' : '删除') }
          ),
        ],
      })
    },
  },
]

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const res = await listPlugins()
    plugins.value = res.data || []
  } catch (e) {
    loadError.value = '插件管理加载失败，请检查网络后重试'
  } finally {
    loading.value = false
  }
}

function openCreate() {
  isEditing.value = false
  form.value = {
    name: '',
    hook_type: 'pre_route',
    module_path: '',
    priority: 0,
    enabled: true,
    config_json: '{}',
  }
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
    toast.success('保存成功')
    dialogVisible.value = false
    await load()
  } catch (e) {
    toast.error('操作失败，请检查配置后重试')
  } finally {
    submitting.value = false
  }
}

async function deleteItem(id: string) {
  const ok = await confirm({
    title: '确认删除',
    content: '确定删除该插件吗？',
    positiveText: '删除',
    negativeText: '取消',
    variant: 'danger',
  })
  if (!ok) return
  deletingId.value = id
  try {
    await deletePlugin(id)
    toast.success('插件已删除')
    await load()
  } catch (e) {
    toast.error('操作失败，请检查配置后重试')
  } finally {
    deletingId.value = ''
  }
}

async function toggle(id: string) {
  try {
    togglingId.value = id
    await togglePlugin(id)
    toast.success('插件状态已更新')
    await load()
  } catch (e) {
    toast.error('操作失败，请检查配置后重试')
  } finally {
    togglingId.value = ''
  }
}

const { beforeClose, closeEditor } = useUnsavedForm(dialogVisible, () => form.value, submitting)

onMounted(load)
</script>
