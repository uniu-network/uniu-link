<template>
  <div class="space-y-6">
    <div class="flex justify-end"><UiButton variant="primary" @click="openCreate">+ 新建密钥</UiButton></div>
    <UiSpinner :show="loading"><UiDataTable :columns="columns" :data="keys" /></UiSpinner>

    <UiModal v-model:open="dialogVisible" :title="isEditing ? '编辑 API 密钥' : '新建 API 密钥'" width="640px">
      <div class="space-y-4">
        <label class="block space-y-2 text-sm font-medium"><span>名称</span><input v-model="form.name" placeholder="例如：生产环境密钥" class="form-input w-full" /></label>
        <label class="flex items-center gap-2 text-sm"><input v-model="form.no_expiry" type="checkbox" class="h-4 w-4" />永不过期</label>
        <label v-if="!form.no_expiry" class="block space-y-2 text-sm font-medium"><span>到期时间</span><input v-model="expiresAtLocal" type="datetime-local" class="form-input w-full" /></label>
        <label class="block space-y-2 text-sm font-medium"><span>Token 配额 (0 = 无限)</span><input v-model.number="form.max_tokens" type="number" min="0" class="form-input w-full" /></label>
        <label class="flex items-center gap-2 text-sm"><input v-model="form.all_models" type="checkbox" class="h-4 w-4" />不限制（可调用所有模型）</label>
        <div v-if="!form.all_models" class="space-y-2 rounded-lg border border-border p-3">
          <div class="flex gap-2">
            <select v-model="selectedModel" class="form-input flex-1"><option value="">选择模型添加...</option><option v-for="m in availableModels" :key="m" :value="m">{{ m }}</option></select>
            <UiButton :disabled="!selectedModel" @click="addModel">添加</UiButton>
          </div>
          <div v-if="form.allowed_models.length" class="flex flex-wrap gap-2">
            <UiBadge v-for="m in form.allowed_models" :key="m" variant="info"><button @click="removeModel(m)">x</button>{{ m }}</UiBadge>
          </div>
          <p v-else class="text-sm text-muted-foreground">请至少添加一个模型，否则密钥将无法使用</p>
        </div>
        <label class="flex items-center gap-2 text-sm"><input v-model="form.no_rate_limit" type="checkbox" class="h-4 w-4" />不限频</label>
        <label v-if="!form.no_rate_limit" class="block space-y-2 text-sm font-medium"><span>频率限制（请求/分钟）</span><input v-model.number="form.rate_limit" type="number" min="1" class="form-input w-full" /></label>
      </div>
      <template #footer><div class="flex justify-end gap-2"><UiButton @click="dialogVisible = false">取消</UiButton><UiButton variant="primary" :loading="submitting" @click="submitForm">保存</UiButton></div></template>
    </UiModal>

    <UiModal v-model:open="newKeyDialogVisible" title="API 密钥已创建" width="520px">
      <div class="space-y-3">
        <div class="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">请立即复制并保存此密钥，关闭后将无法再次查看！</div>
        <code class="block break-all rounded-lg border border-border bg-muted p-3 text-sm">{{ newKeyValue }}</code>
      </div>
      <template #footer><div class="flex justify-end gap-2"><UiButton variant="primary" @click="copyKey">{{ copied ? '已复制' : '复制密钥' }}</UiButton><UiButton @click="newKeyDialogVisible = false">关闭</UiButton></div></template>
    </UiModal>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, h } from 'vue'
import { listApiKeys, createApiKey, updateApiKey, deleteApiKey, toggleApiKey } from '@/api/apikeys'
import { listModels } from '@/api/models'
import { useConfirm, useToast } from '@/composables/useFeedback'
import UiBadge from '@/components/ui/UiBadge.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiDataTable from '@/components/ui/UiDataTable.vue'
import UiModal from '@/components/ui/UiModal.vue'
import UiSpinner from '@/components/ui/UiSpinner.vue'

const toast = useToast()
const confirm = useConfirm()
const keys = ref<any[]>([])
const loading = ref(true)
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
const form = ref<any>({ name: '', expires_at: '', no_expiry: true, max_tokens: 0, all_models: true, allowed_models: [], no_rate_limit: true, rate_limit: 0 })

function usagePercent(k: any) {
  if (!k.max_tokens || k.max_tokens <= 0) return 0
  return Math.round((k.used_tokens / k.max_tokens) * 100)
}

const columns = [
  { title: '名称', key: 'name' },
  { title: '密钥前缀', key: 'key_prefix', render: (row: any) => h('code', { class: 'text-xs text-muted-foreground' }, row.key_prefix + '••••••') },
  { title: '状态', key: 'is_active', render: (row: any) => h(UiButton, { size: 'sm', variant: row.is_active ? 'primary' : 'default', loading: togglingId.value === row.id, onClick: () => toggle(row.id) }, { default: () => togglingId.value === row.id ? '处理中' : (row.is_active ? '启用' : '禁用') }) },
  { title: '到期时间', key: 'expires_at', render: (row: any) => !row.expires_at ? h('span', { class: 'text-emerald-600 dark:text-emerald-400' }, '永不过期') : h('span', { class: isExpired(row.expires_at) ? 'text-red-600 dark:text-red-400' : '' }, formatDate(row.expires_at)) },
  { title: 'Token 用量 / 配额', key: 'usage', render: (row: any) => h('div', { class: 'min-w-36 space-y-1' }, [h('p', `${formatNumber(row.used_tokens)} / ${row.max_tokens ? formatNumber(row.max_tokens) : '无限'}`), row.max_tokens ? h('div', { class: 'h-1.5 rounded-full bg-muted' }, h('div', { class: 'h-full rounded-full bg-foreground', style: { width: `${Math.min(usagePercent(row), 100)}%` } })) : null]) },
  { title: '可调用模型', key: 'allowed_models', render: (row: any) => !row.allowed_models?.length ? h('span', { class: 'text-emerald-600 dark:text-emerald-400' }, '所有模型') : h('div', { class: 'flex flex-wrap gap-1' }, row.allowed_models.slice(0, 3).map((m: string) => h(UiBadge, { variant: 'info' }, { default: () => m })).concat(row.allowed_models.length > 3 ? [h(UiBadge, null, { default: () => `+${row.allowed_models.length - 3}` })] : [])) },
  { title: '频率限制', key: 'rate_limit', render: (row: any) => row.rate_limit ? row.rate_limit + ' req/min' : '不限' },
  { title: '操作', key: 'actions', render: (row: any) => h('div', { class: 'flex gap-2' }, [h(UiButton, { variant: 'link', size: 'sm', onClick: () => openEdit(row) }, { default: () => '编辑' }), h(UiButton, { variant: 'link', size: 'sm', loading: deletingId.value === row.id, onClick: () => deleteItem(row.id) }, { default: () => deletingId.value === row.id ? '删除中' : '删除' })]) },
]

async function load() {
  loading.value = true
  try {
    const [keysRes] = await Promise.all([listApiKeys(), loadModelNames()])
    keys.value = keysRes.data || []
  } catch (e) { console.error(e) } finally { loading.value = false }
}

async function loadModelNames() {
  try { availableModels.value = ((await listModels()).data || []).map((m: any) => m.name) } catch { availableModels.value = [] }
}

function openCreate() {
  isEditing.value = false
  form.value = { name: '', expires_at: '', no_expiry: true, max_tokens: 0, all_models: true, allowed_models: [], no_rate_limit: true, rate_limit: 0 }
  expiresAtLocal.value = ''
  dialogVisible.value = true
}

function openEdit(k: any) {
  isEditing.value = true
  form.value = { id: k.id, name: k.name, no_expiry: !k.expires_at, max_tokens: k.max_tokens || 0, all_models: !k.allowed_models?.length, allowed_models: k.allowed_models ? [...k.allowed_models] : [], no_rate_limit: !k.rate_limit, rate_limit: k.rate_limit || 0 }
  expiresAtLocal.value = k.expires_at ? k.expires_at.slice(0, 16) : ''
  dialogVisible.value = true
}

function addModel() {
  if (selectedModel.value && !form.value.allowed_models.includes(selectedModel.value)) form.value.allowed_models.push(selectedModel.value)
  selectedModel.value = ''
}

function removeModel(m: string) { form.value.allowed_models = form.value.allowed_models.filter((x: string) => x !== m) }

async function submitForm() {
  const data: Record<string, any> = { name: form.value.name }
  data.expires_at = form.value.no_expiry ? '' : expiresAtLocal.value ? new Date(expiresAtLocal.value).toISOString() : ''
  data.max_tokens = form.value.max_tokens > 0 ? form.value.max_tokens : null
  data.allowed_models = form.value.all_models ? [] : form.value.allowed_models
  if (!form.value.all_models && data.allowed_models.length === 0) return toast.warning('请至少选择一个可调用模型，或勾选“不限制”')
  data.rate_limit = form.value.no_rate_limit ? null : form.value.rate_limit > 0 ? form.value.rate_limit : null
  if (!form.value.no_rate_limit && !data.rate_limit) return toast.warning('请设置有效的频率限制值')
  try {
    submitting.value = true
    if (isEditing.value) { await updateApiKey(form.value.id, data); dialogVisible.value = false; await load() }
    else { const res = await createApiKey(data); dialogVisible.value = false; newKeyValue.value = res.key; newKeyDialogVisible.value = true; copied.value = false; await load() }
  } catch (e: any) { toast.error(e?.response?.data?.error?.message || '操作失败') } finally { submitting.value = false }
}

async function deleteItem(id: string) {
  const ok = await confirm({ title: '确认删除', content: '确定删除该 API 密钥吗？删除后使用此密钥的客户端将无法访问。', positiveText: '确定', negativeText: '取消', variant: 'danger' })
  if (!ok) return
  deletingId.value = id
  try { await deleteApiKey(id); await load() } catch (e) { console.error(e) } finally { deletingId.value = '' }
}

async function toggle(id: string) {
  try { togglingId.value = id; await toggleApiKey(id); await load() } catch (e) { console.error(e) } finally { togglingId.value = '' }
}

async function copyKey() {
  try { await navigator.clipboard.writeText(newKeyValue.value); copied.value = true; setTimeout(() => { copied.value = false }, 2000) }
  catch { copied.value = true }
}

function formatDate(iso: string) { try { return new Date(iso).toLocaleString('zh-CN') } catch { return iso } }
function isExpired(iso: string) { try { return new Date(iso) < new Date() } catch { return false } }
function formatNumber(n: number | null | undefined) { return n == null ? '0' : n.toLocaleString('zh-CN') }

onMounted(load)
</script>
