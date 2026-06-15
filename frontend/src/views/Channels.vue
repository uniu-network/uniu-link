<template>
  <div class="space-y-6">
    <div class="flex justify-end"><UiButton variant="primary" @click="openCreate">+ 新建渠道</UiButton></div>
    <UiSpinner :show="loading"><UiDataTable :columns="columns" :data="channels" /></UiSpinner>

    <UiDrawer v-model:open="dialogVisible" :title="isEditing ? '编辑渠道' : '新建渠道'" width="560px">
      <div class="space-y-4">
        <Field label="名称"><input v-model="form.name" placeholder="请输入渠道名称" class="form-input w-full" /></Field>
        <Field label="提供商"><select v-model="form.provider" class="form-input w-full" @change="applyProviderDefaultApiType"><option v-for="option in providerOptions" :key="option.value" :value="option.value">{{ option.label }}</option></select></Field>
        <Field label="上游接口类型"><select v-model="form.api_type" class="form-input w-full"><option v-for="option in apiTypeOptions(form.provider)" :key="option.value" :value="option.value">{{ option.label }}</option></select><Help>网关会按该类型把请求体转换为上游可接受的格式。</Help></Field>
        <Field label="自定义请求头"><HeaderEditor v-model="form.custom_headers" /><Help>HTTP 请求中追加的自定义头，不会覆盖 Authorization 等认证头。</Help></Field>
        <Field label="Base URL"><input v-model="form.base_url" placeholder="https://api.openai.com" class="form-input w-full" /></Field>
        <Field label="API Key"><input v-model="form.api_key" type="password" class="form-input w-full" /></Field>
        <div class="grid gap-4 sm:grid-cols-2">
          <Field label="超时 (秒)"><input v-model.number="form.timeout" type="number" class="form-input w-full" /></Field>
          <Field label="最大重试"><input v-model.number="form.max_retries" type="number" class="form-input w-full" /></Field>
        </div>
        <Field label="默认权重"><input v-model.number="form.default_weight" type="number" step="0.1" class="form-input w-full" /><Help>模型添加该渠道时默认使用，可在模型配置中单独覆盖。</Help></Field>
        <Field label="上游模型列表"><textarea v-model="upstreamModelsText" rows="4" placeholder="每行一个上游模型 ID" class="form-input min-h-28 w-full py-2" /><Help>可手动填写，也可保存后点击列表里的“拉取模型”自动同步。</Help></Field>
      </div>
      <template #footer><div class="flex justify-end gap-2"><UiButton @click="dialogVisible = false">取消</UiButton><UiButton variant="primary" :loading="submitting" @click="submitForm">保存</UiButton></div></template>
    </UiDrawer>

    <UiModal v-model:open="testDialogVisible" title="测试渠道" width="640px">
      <div class="space-y-4">
        <p class="text-sm font-semibold">{{ testChannelName }}</p>
        <Field label="搜索模型"><input v-model="testModelSearch" placeholder="搜索模型..." class="form-input w-full" /></Field>
        <Field label="选择模型">
          <div class="max-h-52 overflow-auto rounded-lg border border-border p-3 thin-scrollbar">
            <label v-for="m in filteredTestModels" :key="m" class="flex items-center gap-2 py-1 text-sm"><input v-model="testSelectedModels" type="checkbox" :value="m" class="h-4 w-4" />{{ m }}</label>
            <UiEmpty v-if="!filteredTestModels.length" title="暂无模型，请先拉取上游模型" />
          </div>
          <Help>已选 {{ testSelectedModels.length }} 个模型</Help>
        </Field>
        <Field label="测试消息"><input v-model="testMessage" class="form-input w-full" /></Field>
        <div v-if="testResults.length" class="max-h-80 space-y-2 overflow-auto thin-scrollbar">
          <UiCard v-for="r in testResults" :key="r.model">
            <div class="flex items-center justify-between gap-3"><code :class="r.success ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400'">{{ r.model }}</code><span class="text-xs text-muted-foreground">{{ r.latency_ms }}ms</span></div>
            <p v-if="r.success" class="mt-2 text-sm text-emerald-600 dark:text-emerald-400">{{ r.reply }}</p>
            <p v-else class="mt-2 text-sm text-red-600 dark:text-red-400"><span v-if="r.status_code">HTTP {{ r.status_code }}: </span>{{ r.error }}</p>
          </UiCard>
        </div>
      </div>
      <template #footer><div class="flex justify-end gap-2"><UiButton @click="testDialogVisible = false">关闭</UiButton><UiButton variant="primary" :loading="testing" :disabled="!testSelectedModels.length" @click="runTest">{{ testing ? '测试中...' : '开始测试' }}</UiButton></div></template>
    </UiModal>
  </div>
</template>

<script setup lang="ts">
import { computed, defineComponent, ref, onMounted, h } from 'vue'
import { listChannels, createChannel, updateChannel, deleteChannel, syncChannelModels, testChannel } from '@/api/channels'
import { useConfirm, useToast } from '@/composables/useFeedback'
import HeaderEditor from '@/components/HeaderEditor.vue'
import UiBadge from '@/components/ui/UiBadge.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiCard from '@/components/ui/UiCard.vue'
import UiDataTable from '@/components/ui/UiDataTable.vue'
import UiDrawer from '@/components/ui/UiDrawer.vue'
import UiEmpty from '@/components/ui/UiEmpty.vue'
import UiModal from '@/components/ui/UiModal.vue'
import UiSpinner from '@/components/ui/UiSpinner.vue'

const Field = defineComponent({ props: { label: String }, setup(props, { slots }) { return () => h('label', { class: 'block space-y-2 text-sm font-medium' }, [h('span', props.label), slots.default?.()]) } })
const Help = defineComponent({ setup(_, { slots }) { return () => h('p', { class: 'text-xs text-muted-foreground' }, slots.default?.()) } })

const toast = useToast()
const confirm = useConfirm()
const channels = ref<any[]>([])
const loading = ref(true)
const dialogVisible = ref(false)
const isEditing = ref(false)
const submitting = ref(false)
const syncingId = ref('')
const deletingId = ref('')
const upstreamModelsText = ref('')
const testDialogVisible = ref(false)
const testChannelId = ref('')
const testChannelName = ref('')
const testModels = ref<string[]>([])
const testModelSearch = ref('')
const testSelectedModels = ref<string[]>([])
const testMessage = ref('Hi, please respond with a short greeting to confirm you are working.')
const testing = ref(false)
const testResults = ref<any[]>([])
const form = ref<any>({ name: '', provider: 'openai', api_type: 'openai', base_url: '', api_key: '', timeout: 30, max_retries: 2, default_weight: 1.0, custom_headers: [] })

const providerOptions = [{ label: 'OpenAI', value: 'openai' }, { label: 'Anthropic', value: 'anthropic' }, { label: 'Azure', value: 'azure' }, { label: 'Google', value: 'google' }, { label: 'Custom', value: 'custom' }]
function defaultApiType(provider: string) { return provider === 'anthropic' ? 'claude' : 'openai' }
function apiTypeLabel(apiType: string) { return ({ openai: 'Chat Completions', responses: 'Responses', claude: 'Claude Messages', auto: 'Auto' } as Record<string, string>)[apiType] || apiType || '-' }
function applyProviderDefaultApiType() { form.value.api_type = defaultApiType(form.value.provider) }
function apiTypeOptions(provider: string) { const openaiOptions = [{ label: 'Auto', value: 'auto' }, { label: 'OpenAI Chat Completions', value: 'openai' }, { label: 'OpenAI Responses', value: 'responses' }]; if (provider === 'anthropic') return [{ label: 'Claude Messages', value: 'claude' }]; if (provider === 'custom') return [...openaiOptions, { label: 'Claude Messages', value: 'claude' }]; return openaiOptions }
function parseUpstreamModels() { return upstreamModelsText.value.split('\n').map((item) => item.trim()).filter(Boolean) }
function objectToHeaderItems(headers: Record<string, string> | undefined | null) { return Object.entries(headers || {}).map(([key, value]) => ({ key, value: String(value) })) }
function headerItemsToObject(items: { key: string; value: string }[]) { const result: Record<string, string> = {}; for (const item of items) if (item.key.trim()) result[item.key.trim()] = item.value; return result }

const filteredTestModels = computed(() => { const q = testModelSearch.value.toLowerCase().trim(); return q ? testModels.value.filter((m) => m.toLowerCase().includes(q)) : testModels.value })

function openTest(ch: any) { testChannelId.value = ch.id; testChannelName.value = ch.name; testModels.value = ch.upstream_models || []; testModelSearch.value = ''; testSelectedModels.value = []; testMessage.value = 'Hi, please respond with a short greeting to confirm you are working.'; testResults.value = []; testDialogVisible.value = true }
async function runTest() { if (!testSelectedModels.value.length) return; testing.value = true; testResults.value = []; const results: any[] = []; for (const model of [...testSelectedModels.value]) { try { results.push({ model, ...(await testChannel(testChannelId.value, model, testMessage.value)) }) } catch (e: any) { results.push({ model, success: false, reply: '', error: e?.response?.data?.error?.message || e?.message || 'Unknown error', status_code: e?.response?.status || 500, latency_ms: 0 }) } testResults.value = [...results] } testing.value = false }
async function load() { loading.value = true; try { channels.value = (await listChannels()).data || [] } catch (e) { console.error(e) } finally { loading.value = false } }
function openCreate() { isEditing.value = false; form.value = { name: '', provider: 'openai', api_type: 'openai', base_url: '', api_key: '', timeout: 30, max_retries: 2, default_weight: 1.0, custom_headers: [] }; upstreamModelsText.value = ''; dialogVisible.value = true }
function openEdit(ch: any) { isEditing.value = true; form.value = { ...ch, api_type: ch.api_type || defaultApiType(ch.provider), api_key: '', custom_headers: objectToHeaderItems(ch.custom_headers) }; upstreamModelsText.value = (ch.upstream_models || []).join('\n'); dialogVisible.value = true }
async function submitForm() { const data = { ...form.value, upstream_models: parseUpstreamModels(), custom_headers: headerItemsToObject(form.value.custom_headers || []) }; if (isEditing.value && !data.api_key) delete data.api_key; try { submitting.value = true; if (isEditing.value) await updateChannel(data.id, data); else await createChannel(data); dialogVisible.value = false; await load() } catch (e) { console.error(e) } finally { submitting.value = false } }
async function syncModels(id: string) { try { syncingId.value = id; const res = await syncChannelModels(id); toast.success(`已拉取 ${res.total || 0} 个上游模型`); await load() } catch (e) { console.error(e); toast.error('拉取上游模型失败，请检查 Base URL、Provider 和 API Key') } finally { syncingId.value = '' } }
async function deleteItem(id: string) { const ok = await confirm({ title: '确认删除', content: '确定删除该渠道吗？', positiveText: '确定', negativeText: '取消', variant: 'danger' }); if (!ok) return; deletingId.value = id; try { await deleteChannel(id); await load() } catch (e) { console.error(e) } finally { deletingId.value = '' } }

const columns = [
  { title: '名称', key: 'name' }, { title: '提供商', key: 'provider' }, { title: '接口类型', key: 'api_type', render: (row: any) => apiTypeLabel(row.api_type) }, { title: '自定义请求头', key: 'custom_headers', render: (row: any) => `${Object.keys(row.custom_headers || {}).length} 个` }, { title: '地址', key: 'base_url' }, { title: '默认权重', key: 'default_weight' }, { title: '上游模型', key: 'upstream_models', render: (row: any) => (row.upstream_models?.length || 0) + ' 个' },
  { title: '健康状态', key: 'health_status', render: (row: any) => h(UiBadge, { variant: row.health_status === 'healthy' ? 'success' : 'danger' }, { default: () => row.health_status }) },
  { title: '熔断状态', key: 'circuit_state', render: (row: any) => h(UiBadge, { variant: row.circuit_state === 'open' ? 'danger' : row.circuit_state === 'half_open' ? 'warning' : 'success' }, { default: () => row.circuit_state }) },
  { title: '操作', key: 'actions', render: (row: any) => h('div', { class: 'flex flex-wrap gap-2' }, [h(UiButton, { variant: 'link', size: 'sm', loading: syncingId.value === row.id, onClick: () => syncModels(row.id) }, { default: () => syncingId.value === row.id ? '拉取中' : '拉取模型' }), h(UiButton, { variant: 'link', size: 'sm', onClick: () => openTest(row) }, { default: () => '测试' }), h(UiButton, { variant: 'link', size: 'sm', onClick: () => openEdit(row) }, { default: () => '编辑' }), h(UiButton, { variant: 'link', size: 'sm', loading: deletingId.value === row.id, onClick: () => deleteItem(row.id) }, { default: () => deletingId.value === row.id ? '删除中' : '删除' })]) },
]

onMounted(load)
</script>
