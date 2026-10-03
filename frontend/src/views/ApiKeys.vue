<template>
  <div class="page-stack">
    <PageHeader title="API 密钥" description="管理客户端访问权限、用量配额和频率限制。"
      ><UiButton :loading="loading" @click="load"><NavIcon name="refresh" />刷新</UiButton
      ><UiButton variant="primary" @click="openCreate"
        ><NavIcon name="plus" />新建密钥</UiButton
      ></PageHeader
    >
    <ListState :error="loadError" @retry="load" />
    <UiSpinner v-if="!loadError" :show="loading"
      ><UiDataTable :columns="columns" :data="keys"
    /></UiSpinner>

    <UiModal
      v-model:open="dialogVisible"
      :busy="submitting"
      :before-close="beforeClose"
      @save="submitForm"
      :title="isEditing ? '编辑 API 密钥' : '新建 API 密钥'"
      width="640px"
    >
      <div class="space-y-4">
        <UiField label="名称"
          ><UiInput v-model="form.name" placeholder="例如：生产环境密钥" class="w-full"
        /></UiField>
        <UiCheckbox v-model="form.no_expiry">永不过期</UiCheckbox>
        <UiField v-if="!form.no_expiry" label="到期时间"
          ><UiInput v-model="expiresAtLocal" type="datetime-local" class="w-full"
        /></UiField>
        <UiField label="Token 配额 (0 = 无限)"
          ><UiInput v-model.number="form.max_tokens" type="number" min="0" class="w-full"
        /></UiField>
        <UiCheckbox v-model="form.all_models">不限制（可调用所有模型）</UiCheckbox>
        <div
          v-if="!form.all_models"
          class="space-y-2 rounded-lg border border-border/60 bg-muted/20 p-3"
        >
          <div class="flex gap-2">
            <UiSelect
              v-model="selectedModel"
              :options="modelSelectOptions"
              placeholder="选择模型添加..."
              class="flex-1"
            />
            <UiButton :disabled="!selectedModel" @click="addModel">添加</UiButton>
          </div>
          <div v-if="form.allowed_models.length" class="flex flex-wrap gap-2">
            <UiBadge v-for="m in form.allowed_models" :key="m" variant="info"
              ><UiButton
                variant="ghost"
                size="icon"
                :aria-label="`移除模型 ${m}`"
                @click="removeModel(m)"
                ><NavIcon name="close" :size="16" /></UiButton
              >{{ m }}</UiBadge
            >
          </div>
          <p v-else class="text-sm text-muted-foreground">请至少添加一个模型，否则密钥将无法使用</p>
        </div>
        <UiCheckbox v-model="form.no_rate_limit">不限频</UiCheckbox>
        <UiField v-if="!form.no_rate_limit" label="频率限制（请求/分钟）"
          ><UiInput v-model.number="form.rate_limit" type="number" min="1" class="w-full"
        /></UiField>
      </div>
      <template #footer
        ><div class="flex justify-end gap-2">
          <UiButton @click="closeEditor">取消</UiButton
          ><UiButton variant="primary" :loading="submitting" @click="submitForm">保存</UiButton>
        </div></template
      >
    </UiModal>

    <UiModal v-model:open="newKeyDialogVisible" title="API 密钥已创建" width="520px">
      <div class="space-y-3">
        <p class="inline-feedback">
          <NavIcon
            name="warning"
            class="message-symbol-warning"
          />请立即复制并保存此密钥，关闭后将无法再次查看。
        </p>
        <code class="block break-all rounded-lg border border-border/60 bg-muted/40 p-3 text-sm">{{
          newKeyValue
        }}</code>
      </div>
      <template #footer
        ><div class="flex justify-end gap-2">
          <UiButton variant="primary" @click="copyKey">{{
            copied ? '已复制' : '复制密钥'
          }}</UiButton
          ><UiButton @click="newKeyDialogVisible = false">关闭</UiButton>
        </div></template
      >
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
import { listApiKeys, createApiKey, updateApiKey, deleteApiKey, toggleApiKey } from '@/api/apikeys'
import { listModels } from '@/api/models'
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
const keys = ref<any[]>([])
const loading = ref(true)
const loadError = ref('')
const dialogVisible = ref(false)
const isEditing = ref(false)
const submitting = ref(false)
const deletingId = ref('')
const togglingId = ref('')
const newKeyDialogVisible = ref(false)
const newKeyValue = ref('')
const copied = ref(false)
const availableModels = ref<string[]>([])
const selectedModel = ref('')
const expiresAtLocal = ref('')
const form = ref<any>({
  name: '',
  expires_at: '',
  no_expiry: true,
  max_tokens: 0,
  all_models: true,
  allowed_models: [],
  no_rate_limit: true,
  rate_limit: 0,
})

const modelSelectOptions = computed(() =>
  availableModels.value.map((m: string) => ({ label: m, value: m }))
)
function usagePercent(k: any) {
  if (!k.max_tokens || k.max_tokens <= 0) return 0
  return Math.round((k.used_tokens / k.max_tokens) * 100)
}

const columns = [
  { title: '名称', key: 'name' },
  {
    title: '密钥前缀',
    key: 'key_prefix',
    render: (row: any) =>
      h('code', { class: 'text-xs text-muted-foreground' }, row.key_prefix + '••••••'),
  },
  {
    title: '状态',
    key: 'is_active',
    render: (row: any) =>
      h(
        UiButton,
        {
          size: 'sm',
          variant: row.is_active ? 'primary' : 'default',
          loading: togglingId.value === row.id,
          onClick: () => toggle(row.id),
        },
        {
          default: () => (togglingId.value === row.id ? '处理中' : row.is_active ? '启用' : '禁用'),
        }
      ),
  },
  {
    title: '到期时间',
    key: 'expires_at',
    render: (row: any) =>
      !row.expires_at
        ? h('span', { class: 'message-symbol-success' }, '永不过期')
        : h(
            'span',
            { class: isExpired(row.expires_at) ? 'message-symbol-error' : '' },
            formatDate(row.expires_at)
          ),
  },
  {
    title: 'Token 用量 / 配额',
    key: 'usage',
    render: (row: any) =>
      h('div', { class: 'min-w-36 space-y-1' }, [
        h(
          'p',
          `${formatNumber(row.used_tokens)} / ${row.max_tokens ? formatNumber(row.max_tokens) : '无限'}`
        ),
        row.max_tokens
          ? h('fluent-progress', {
              value: Math.min(usagePercent(row), 100),
              min: 0,
              max: 100,
              'aria-label': 'Token 配额使用比例',
            })
          : null,
      ]),
  },
  {
    title: '可调用模型',
    key: 'allowed_models',
    render: (row: any) =>
      !row.allowed_models?.length
        ? h('span', { class: 'message-symbol-success' }, '所有模型')
        : h(
            'div',
            { class: 'flex flex-wrap gap-1' },
            row.allowed_models
              .slice(0, 3)
              .map((m: string) => h(UiBadge, { variant: 'info' }, { default: () => m }))
              .concat(
                row.allowed_models.length > 3
                  ? [h(UiBadge, null, { default: () => `+${row.allowed_models.length - 3}` })]
                  : []
              )
          ),
  },
  {
    title: '频率限制',
    key: 'rate_limit',
    render: (row: any) => (row.rate_limit ? row.rate_limit + ' req/min' : '不限'),
  },
  {
    title: '操作',
    key: 'actions',
    render: (row: any) =>
      h(UiDropdown, null, {
        default: () => [
          h(
            UiDropdownItem,
            { icon: Power, loading: togglingId.value === row.id, onClick: () => toggle(row.id) },
            {
              default: () =>
                togglingId.value === row.id ? '处理中' : row.is_active ? '禁用' : '启用',
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
      }),
  },
]

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const [keysRes] = await Promise.all([listApiKeys(), loadModelNames()])
    keys.value = keysRes.data || []
  } catch (e) {
    loadError.value = 'API 密钥加载失败，请检查网络后重试'
  } finally {
    loading.value = false
  }
}

async function loadModelNames() {
  try {
    availableModels.value = ((await listModels()).data || []).map((m: any) => m.name)
  } catch {
    availableModels.value = []
  }
}

function openCreate() {
  isEditing.value = false
  form.value = {
    name: '',
    expires_at: '',
    no_expiry: true,
    max_tokens: 0,
    all_models: true,
    allowed_models: [],
    no_rate_limit: true,
    rate_limit: 0,
  }
  expiresAtLocal.value = ''
  dialogVisible.value = true
}

function openEdit(k: any) {
  isEditing.value = true
  form.value = {
    id: k.id,
    name: k.name,
    no_expiry: !k.expires_at,
    max_tokens: k.max_tokens || 0,
    all_models: !k.allowed_models?.length,
    allowed_models: k.allowed_models ? [...k.allowed_models] : [],
    no_rate_limit: !k.rate_limit,
    rate_limit: k.rate_limit || 0,
  }
  expiresAtLocal.value = k.expires_at ? k.expires_at.slice(0, 16) : ''
  dialogVisible.value = true
}

function addModel() {
  if (selectedModel.value && !form.value.allowed_models.includes(selectedModel.value))
    form.value.allowed_models.push(selectedModel.value)
  selectedModel.value = ''
}

function removeModel(m: string) {
  form.value.allowed_models = form.value.allowed_models.filter((x: string) => x !== m)
}

async function submitForm() {
  const data: Record<string, any> = { name: form.value.name }
  data.expires_at = form.value.no_expiry
    ? ''
    : expiresAtLocal.value
      ? new Date(expiresAtLocal.value).toISOString()
      : ''
  data.max_tokens = form.value.max_tokens > 0 ? form.value.max_tokens : 0
  data.allowed_models = form.value.all_models ? [] : form.value.allowed_models
  if (!form.value.all_models && data.allowed_models.length === 0)
    return toast.warning('请至少选择一个可调用模型，或勾选“不限制”')
  data.rate_limit = form.value.no_rate_limit
    ? 0
    : form.value.rate_limit > 0
      ? form.value.rate_limit
      : 0
  if (!form.value.no_rate_limit && !data.rate_limit) return toast.warning('请设置有效的频率限制值')
  try {
    submitting.value = true
    if (isEditing.value) {
      await updateApiKey(form.value.id, data)
      toast.success('密钥已更新')
      dialogVisible.value = false
      await load()
    } else {
      const res = await createApiKey(data)
      dialogVisible.value = false
      newKeyValue.value = res.key
      newKeyDialogVisible.value = true
      copied.value = false
      await load()
    }
  } catch (e: any) {
    toast.error(e?.response?.data?.error?.message || '操作失败')
  } finally {
    submitting.value = false
  }
}

async function deleteItem(id: string) {
  const ok = await confirm({
    title: '确认删除',
    content: '确定删除该 API 密钥吗？删除后使用此密钥的客户端将无法访问。',
    positiveText: '删除',
    negativeText: '取消',
    variant: 'danger',
  })
  if (!ok) return
  deletingId.value = id
  try {
    await deleteApiKey(id)
    toast.success('密钥已删除')
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
    await toggleApiKey(id)
    toast.success('密钥状态已更新')
    await load()
  } catch (e) {
    toast.error('操作失败，请检查配置后重试')
  } finally {
    togglingId.value = ''
  }
}

async function copyKey() {
  try {
    await navigator.clipboard.writeText(newKeyValue.value)
    copied.value = true
    setTimeout(() => {
      copied.value = false
    }, 2000)
  } catch {
    toast.error('复制失败，请手动选择并复制密钥')
  }
}

function formatDate(iso: string) {
  try {
    return new Date(iso).toLocaleString('zh-CN')
  } catch {
    return iso
  }
}
function isExpired(iso: string) {
  try {
    return new Date(iso) < new Date()
  } catch {
    return false
  }
}
function formatNumber(n: number | null | undefined) {
  return n == null ? '0' : n.toLocaleString('zh-CN')
}

const { beforeClose, closeEditor } = useUnsavedForm(
  dialogVisible,
  () => ({ form: form.value, expiry: expiresAtLocal.value }),
  submitting
)

onMounted(load)
</script>
