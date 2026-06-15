<template>
  <div class="space-y-6">
    <div class="flex justify-end"><UiButton variant="primary" @click="openCreate">+ 新建模型</UiButton></div>
    <UiSpinner :show="loading">
      <div class="space-y-4">
        <UiCard v-for="m in models" :key="m.id" :title="m.display_name || m.name">
          <template #extra><div class="flex flex-wrap items-center gap-2"><UiBadge variant="info">{{ m.routing_strategy }}</UiBadge><UiBadge :variant="m.failover_enabled ? 'success' : 'default'">{{ m.failover_enabled ? '容灾顺延' : '不顺延' }}</UiBadge><UiBadge v-if="m.supports_thinking" variant="warning">思考 {{ m.default_thinking_effort || 'none' }}</UiBadge><UiBadge v-if="m.enable_cache" variant="info">缓存已启用</UiBadge><UiButton variant="link" size="sm" :loading="editingId === m.id" @click="openEdit(m)">{{ editingId === m.id ? '加载中' : '编辑' }}</UiButton><UiButton variant="link" size="sm" :loading="deletingModelId === m.id" @click="deleteModelItem(m.id)">{{ deletingModelId === m.id ? '删除中' : '删除' }}</UiButton></div></template>
          <p class="text-sm text-muted-foreground">路由目标（{{ m.channel_refs?.length || 0 }}个）</p>
          <div v-if="m.channel_refs?.length" class="mt-3 flex flex-wrap gap-2"><UiBadge v-for="ref in m.channel_refs" :key="ref.id">{{ ref.channel_name || ref.inline_config?.name || 'inline' }} · {{ ref.type === 'inline' ? '直连上游' : '渠道' }}(权重{{ ref.weight }})</UiBadge></div>
          <p v-else class="mt-2 text-sm text-muted-foreground">无路由目标</p>
        </UiCard>
        <UiEmpty v-if="!models.length" title="暂无模型数据" />
      </div>
    </UiSpinner>

    <UiDrawer v-model:open="dialogVisible" :title="isEditing ? '编辑模型' : '新建模型'" width="760px">
      <div class="space-y-5">
        <div class="grid gap-4 sm:grid-cols-2"><Field label="模型名称"><input v-model="form.name" placeholder="请输入模型名称" class="form-input w-full" /></Field><Field label="显示名称"><input v-model="form.display_name" placeholder="请输入显示名称" class="form-input w-full" /></Field></div>
        <Field label="分配策略"><select v-model="form.routing_strategy" class="form-input w-full"><option v-for="option in routingStrategyOptions" :key="option.value" :value="option.value">{{ option.label }}</option></select></Field>
        <Field label="自定义JS"><textarea v-model="form.custom_js" rows="3" placeholder="function route(channels, ctx) { return channels.map(c => c.ref_id); }" class="form-input min-h-24 w-full py-2" /></Field>
        <div class="grid gap-3 sm:grid-cols-2"><Check v-model="form.failover_enabled" label="启用自动容灾顺延" /><Check v-model="form.is_listed" label="在 /v1/models 中列出" /><Check v-model="form.supports_thinking" label="支持思考模式" /><Check v-model="form.enable_cache" label="启用请求缓存" /></div>
        <div class="grid gap-4 sm:grid-cols-3"><Field label="默认思考等级"><select v-model="form.default_thinking_effort" :disabled="!form.supports_thinking" class="form-input w-full"><option v-for="option in thinkingEffortOptions" :key="option.value" :value="option.value">{{ option.label }}</option></select></Field><Field label="Claude 思考模式"><select v-model="form.claude_thinking_mode" :disabled="!form.supports_thinking" class="form-input w-full"><option v-for="option in claudeThinkingModeOptions" :key="option.value" :value="option.value">{{ option.label }}</option></select></Field><Field label="缓存 TTL (秒)"><input v-model.number="form.cache_ttl_seconds" type="number" class="form-input w-full" /></Field></div>
        <Field label="缓存排除字段 (JSON数组)"><input v-model="form.cache_key_exclude_fields" placeholder='["seed", "user"]' class="form-input w-full" /></Field>

        <div class="border-t border-border pt-5"><h3 class="text-sm font-semibold">路由目标</h3><p class="mt-1 text-sm text-muted-foreground">可选择多个渠道，也可不选渠道直接配置上游。</p></div>
        <div v-if="!isEditing" class="rounded-lg border border-blue-200 bg-blue-50 p-3 text-sm text-blue-700 dark:border-blue-500/30 dark:bg-blue-500/10 dark:text-blue-300">先保存模型后再添加路由目标。</div>
        <template v-else>
          <div v-if="modelRefs.length" class="space-y-2"><UiCard v-for="ref in modelRefs" :key="ref.id"><div class="flex items-center justify-between gap-3"><div><p class="text-sm font-semibold">{{ ref.channel_name || ref.inline_config?.name || 'inline' }}</p><p class="text-xs text-muted-foreground">{{ ref.type === 'inline' ? '直连上游' : '渠道引用' }} · 上游模型 {{ ref.upstream_model_id || '-' }} · 优先级 {{ ref.priority }} / 权重 {{ ref.weight }}</p></div><UiButton variant="link" size="sm" :loading="removingTargetId === ref.id" @click="removeTarget(ref.id)">{{ removingTargetId === ref.id ? '移除中' : '移除' }}</UiButton></div></UiCard></div>
          <UiEmpty v-else title="暂无路由目标" />
          <div v-if="targetError" class="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">{{ targetError }}</div>
          <div class="grid gap-4 sm:grid-cols-2"><Field label="类型"><select v-model="targetForm.type" class="form-input w-full"><option v-for="option in targetTypeOptions" :key="option.value" :value="option.value">{{ option.label }}</option></select></Field><Field label="权重"><input v-model.number="targetForm.weight" type="number" step="0.1" class="form-input w-full" /></Field><Field label="优先级"><input v-model.number="targetForm.priority" type="number" class="form-input w-full" /></Field><Field v-if="targetForm.type === 'reference'" label="渠道"><select v-model="targetForm.channel_id" class="form-input w-full" @change="applySelectedChannelDefaultWeight"><option value="">请选择渠道</option><option v-for="option in channelOptions" :key="option.value" :value="option.value">{{ option.label }}</option></select></Field><Field v-else label="上游名称"><input v-model="targetForm.inline_config.name" class="form-input w-full" /></Field></div>
          <Field v-if="targetForm.type === 'reference'" label="上游模型 ID"><select v-model="targetForm.upstream_model_id" :disabled="!selectedChannelModels().length" class="form-input w-full"><option value="">请选择上游模型</option><option v-for="option in selectedChannelModelOptions" :key="option.value" :value="option.value">{{ option.label }}</option></select></Field>
          <div v-if="targetForm.type === 'inline'" class="space-y-4"><div class="grid gap-4 sm:grid-cols-2"><Field label="提供商"><select v-model="targetForm.inline_config.provider" class="form-input w-full" @change="applyInlineProviderDefaultApiType"><option v-for="option in providerOptions" :key="option.value" :value="option.value">{{ option.label }}</option></select></Field><Field label="上游接口类型"><select v-model="targetForm.inline_config.api_type" class="form-input w-full"><option v-for="option in apiTypeOptions(targetForm.inline_config.provider)" :key="option.value" :value="option.value">{{ option.label }}</option></select></Field></div><Field label="超时 (秒)"><input v-model.number="targetForm.inline_config.timeout" type="number" class="form-input w-full" /></Field><Field label="自定义请求头"><HeaderEditor v-model="targetForm.inline_config.custom_headers" /></Field><Field label="Base URL"><input v-model="targetForm.inline_config.base_url" placeholder="https://api.openai.com" class="form-input w-full" /></Field><Field label="上游模型 ID"><input v-model="targetForm.upstream_model_id" placeholder="例如 gpt-4o 或 claude-3-5-sonnet-latest" class="form-input w-full" /></Field><Field label="API Key"><input v-model="targetForm.inline_config.api_key" type="password" class="form-input w-full" /></Field></div>
          <UiButton variant="primary" block :loading="targetSubmitting" @click="addTarget">{{ targetSubmitting ? '添加中...' : '添加路由目标' }}</UiButton>
        </template>
      </div>
      <template #footer><div class="flex justify-end gap-2"><UiButton @click="dialogVisible = false">取消</UiButton><UiButton variant="primary" :loading="submitting" @click="submitForm">保存</UiButton></div></template>
    </UiDrawer>
  </div>
</template>

<script setup lang="ts">
import { computed, defineComponent, ref, onMounted, h } from 'vue'
import { listChannels } from '@/api/channels'
import { addModelChannel, createModel, deleteModel, deleteModelChannel, listModelChannels, listModels, updateModel } from '@/api/models'
import { useConfirm } from '@/composables/useFeedback'
import HeaderEditor from '@/components/HeaderEditor.vue'
import UiBadge from '@/components/ui/UiBadge.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiCard from '@/components/ui/UiCard.vue'
import UiDrawer from '@/components/ui/UiDrawer.vue'
import UiEmpty from '@/components/ui/UiEmpty.vue'
import UiSpinner from '@/components/ui/UiSpinner.vue'

const Field = defineComponent({ props: { label: String }, setup(props, { slots }) { return () => h('label', { class: 'block space-y-2 text-sm font-medium' }, [h('span', props.label), slots.default?.()]) } })
const Check = defineComponent({ props: { modelValue: Boolean, label: String }, emits: ['update:modelValue'], setup(props, { emit }) { return () => h('label', { class: 'flex items-center gap-2 rounded-lg border border-border p-3 text-sm' }, [h('input', { type: 'checkbox', checked: props.modelValue, class: 'h-4 w-4', onChange: (event: Event) => emit('update:modelValue', (event.target as HTMLInputElement).checked) }), props.label]) } })
const confirm = useConfirm()

const models = ref<any[]>([])
const channels = ref<any[]>([])
const modelRefs = ref<any[]>([])
const loading = ref(true)
const dialogVisible = ref(false)
const isEditing = ref(false)
const submitting = ref(false)
const editingId = ref('')
const deletingModelId = ref('')
const removingTargetId = ref('')
const targetError = ref('')
const targetSubmitting = ref(false)
const form = ref<any>({ name: '', display_name: '', routing_strategy: 'default', custom_js: '', failover_enabled: true, is_listed: true, supports_thinking: false, default_thinking_effort: 'none', claude_thinking_mode: 'adaptive', enable_cache: false, cache_ttl_seconds: 3600, cache_key_exclude_fields: '[]' })
const targetForm = ref<any>(newTargetForm())
const routingStrategyOptions = [{ label: '默认（顺序）', value: 'default' }, { label: '随机', value: 'random' }, { label: '加权', value: 'weighted' }, { label: '自定义JS', value: 'custom_js' }]
const thinkingEffortOptions = [{ label: '关闭', value: 'none' }, { label: '低', value: 'low' }, { label: '中', value: 'medium' }, { label: '高', value: 'high' }]
const claudeThinkingModeOptions = [{ label: 'Adaptive', value: 'adaptive' }, { label: '旧版 Enabled', value: 'enabled' }, { label: 'Disabled', value: 'disabled' }]
const providerOptions = [{ label: 'OpenAI', value: 'openai' }, { label: 'Anthropic', value: 'anthropic' }, { label: 'Azure', value: 'azure' }, { label: 'Google', value: 'google' }, { label: 'Custom', value: 'custom' }]
const targetTypeOptions = [{ label: '选择渠道', value: 'reference' }, { label: '直接上游', value: 'inline' }]
const channelOptions = computed(() => channels.value.map((ch) => ({ label: `${ch.name}（默认权重 ${ch.default_weight}）`, value: ch.id })))

function newTargetForm() { return { type: channels.value.length ? 'reference' : 'inline', channel_id: '', upstream_model_id: '', priority: 0, weight: 1.0, inline_config: { name: '', provider: 'openai', api_type: 'openai', base_url: '', api_key: '', timeout: 30, max_retries: 2, custom_headers: [] } } }
function defaultApiType(provider: string) { return provider === 'anthropic' ? 'claude' : 'openai' }
function applyInlineProviderDefaultApiType() { targetForm.value.inline_config.api_type = defaultApiType(targetForm.value.inline_config.provider) }
function headerItemsToObject(items: { key: string; value: string }[]) { const result: Record<string, string> = {}; for (const item of items) if (item.key.trim()) result[item.key.trim()] = item.value; return result }
function apiTypeOptions(provider: string) { const openaiOptions = [{ label: 'Auto', value: 'auto' }, { label: 'OpenAI Chat Completions', value: 'openai' }, { label: 'OpenAI Responses', value: 'responses' }]; if (provider === 'anthropic') return [{ label: 'Claude Messages', value: 'claude' }]; if (provider === 'custom') return [...openaiOptions, { label: 'Claude Messages', value: 'claude' }]; return openaiOptions }
const selectedChannelModelOptions = computed(() => selectedChannelModels().map((m: string) => ({ label: m, value: m })))
function modelPayload() { return { name: form.value.name, display_name: form.value.display_name, routing_strategy: form.value.routing_strategy, custom_js: form.value.custom_js, failover_enabled: form.value.failover_enabled, is_listed: form.value.is_listed, supports_thinking: form.value.supports_thinking, default_thinking_effort: form.value.default_thinking_effort, claude_thinking_mode: form.value.claude_thinking_mode, enable_cache: form.value.enable_cache, cache_ttl_seconds: form.value.cache_ttl_seconds, cache_key_exclude_fields: form.value.cache_key_exclude_fields } }
async function load() { loading.value = true; try { const [modelRes, channelRes] = await Promise.all([listModels(), listChannels()]); models.value = modelRes.data || []; channels.value = channelRes.data || [] } catch (e) { console.error(e) } finally { loading.value = false } }
function openCreate() { isEditing.value = false; form.value = { name: '', display_name: '', routing_strategy: 'default', custom_js: '', failover_enabled: true, is_listed: true, supports_thinking: false, default_thinking_effort: 'none', claude_thinking_mode: 'adaptive', enable_cache: false, cache_ttl_seconds: 3600, cache_key_exclude_fields: '[]' }; modelRefs.value = []; targetError.value = ''; targetForm.value = newTargetForm(); dialogVisible.value = true }
async function openEdit(m: any) { isEditing.value = true; form.value = { ...m }; targetForm.value = newTargetForm(); targetError.value = ''; try { editingId.value = m.id; modelRefs.value = (await listModelChannels(m.id)).data || [] } catch (e) { console.error(e); modelRefs.value = m.channel_refs || [] } finally { editingId.value = '' } dialogVisible.value = true }
async function submitForm() { try { submitting.value = true; if (isEditing.value) await updateModel(form.value.id, modelPayload()); else await createModel(modelPayload()); dialogVisible.value = false; await load() } catch (e) { console.error(e) } finally { submitting.value = false } }
function applySelectedChannelDefaultWeight() { const selected = channels.value.find((ch) => ch.id === targetForm.value.channel_id); if (selected) { targetForm.value.weight = selected.default_weight; targetForm.value.upstream_model_id = selected.upstream_models?.[0] || '' } }
function selectedChannelModels() { return channels.value.find((ch) => ch.id === targetForm.value.channel_id)?.upstream_models || [] }
async function refreshModelRefs() { modelRefs.value = (await listModelChannels(form.value.id)).data || [] }
async function addTarget() { targetError.value = ''; if (!form.value.id) return targetError.value = '请先保存模型，再添加路由目标'; const data: Record<string, any> = { type: targetForm.value.type, priority: targetForm.value.priority, weight: targetForm.value.weight, upstream_model_id: targetForm.value.upstream_model_id }; if (targetForm.value.type === 'reference') { if (!targetForm.value.channel_id) return targetError.value = '请选择一个渠道'; if (!targetForm.value.upstream_model_id) return targetError.value = '请选择该渠道要代理的上游模型 ID'; data.channel_id = targetForm.value.channel_id } else { data.inline_config = { ...targetForm.value.inline_config, custom_headers: headerItemsToObject(targetForm.value.inline_config.custom_headers || []) }; if (!data.inline_config.name) return targetError.value = '请填写上游名称'; if (!data.inline_config.base_url) return targetError.value = '请填写上游 Base URL'; if (!targetForm.value.upstream_model_id) return targetError.value = '请填写要代理的上游模型 ID' } try { targetSubmitting.value = true; await addModelChannel(form.value.id, data); targetForm.value = newTargetForm(); await refreshModelRefs(); await load() } catch (e) { console.error(e); targetError.value = '添加失败，请检查配置或查看后端日志' } finally { targetSubmitting.value = false } }
async function removeTarget(refId: string) { if (!form.value.id) return; const ok = await confirm({ title: '确认移除', content: '确定移除该路由目标吗？', positiveText: '确定', negativeText: '取消', variant: 'danger' }); if (!ok) return; removingTargetId.value = refId; try { await deleteModelChannel(form.value.id, refId); await refreshModelRefs(); await load() } catch (e) { console.error(e) } finally { removingTargetId.value = '' } }
async function deleteModelItem(id: string) { const ok = await confirm({ title: '确认删除', content: '确定删除该模型配置吗？', positiveText: '确定', negativeText: '取消', variant: 'danger' }); if (!ok) return; deletingModelId.value = id; try { await deleteModel(id); await load() } catch (e) { console.error(e) } finally { deletingModelId.value = '' } }
onMounted(load)
</script>
