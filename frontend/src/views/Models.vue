<template>
  <div class="page-stack">
    <PageHeader title="模型管理" description="配置对外模型、路由目标与容灾策略。"
      ><UiButton :loading="loading" @click="load"><NavIcon name="refresh" />刷新</UiButton
      ><UiButton variant="primary" @click="openCreate"
        ><NavIcon name="plus" />新建模型</UiButton
      ></PageHeader
    >
    <ListState :error="loadError" @retry="load" />
    <UiSpinner v-if="!loadError" :show="loading">
      <div class="catalog-overview" aria-label="模型概览">
        <span><strong>{{ models.length }}</strong> 个模型</span>
        <span><strong>{{ models.filter(m => m.is_listed).length }}</strong> 个公开</span>
        <span><strong>{{ models.filter(m => m.supports_thinking).length }}</strong> 个支持思考</span>
      </div>
      <div class="list-toolbar" role="search" aria-label="筛选模型">
        <UiInput v-model="search" type="search" placeholder="搜索模型名称、显示名称或上游模型" aria-label="搜索模型" class="search-input" />
        <UiSelect v-model="brandFilter" :options="brandOptions" aria-label="模型品牌" />
        <span class="secondary-text" role="status">显示 {{ filteredModels.length }} / {{ models.length }} 个</span>
        <UiButton v-if="search || brandFilter" variant="link" @click="search = ''; brandFilter = ''">清除筛选</UiButton>
      </div>
      <div v-if="filteredModels.length" class="model-grid">
        <UiCard v-for="(m, index) in filteredModels" :key="m.id" class="model-card reveal-item" :style="{ '--reveal-index': Math.min(index, 7) }">
          <template #header>
            <ModelIcon :model="m.name" :icon="m.icon" :upstream-models="upstreamModelNames(m)" :size="28" framed />
            <div class="model-card-title">
              <h2>{{ m.display_name || m.name }}</h2>
              <code class="secondary-text">{{ m.name }}</code>
            </div>
          </template>
          <template #extra>
            <UiDropdown>
              <UiDropdownItem :icon="Pencil" :loading="editingId === m.id" :onClick="() => openEdit(m)">{{ editingId === m.id ? '加载中' : '编辑' }}</UiDropdownItem>
              <UiDropdownItem :icon="Trash2" variant="danger" :loading="deletingModelId === m.id" :onClick="() => deleteModelItem(m.id)">{{ deletingModelId === m.id ? '删除中' : '删除' }}</UiDropdownItem>
            </UiDropdown>
          </template>
          <div class="model-capabilities">
            <UiBadge>{{ routingStrategyOptions.find(option => option.value === m.routing_strategy)?.label || m.routing_strategy }}</UiBadge>
            <UiBadge :variant="m.is_listed ? 'info' : 'default'">{{ m.is_listed ? '公开模型' : '未公开' }}</UiBadge>
            <UiBadge v-if="m.supports_thinking" variant="info">思考 · {{ m.default_thinking_effort || 'none' }}</UiBadge>
          </div>
          <div class="model-routes">
            <div class="summary-row"><span class="secondary-text">路由目标</span><strong>{{ m.channel_refs?.length || 0 }}</strong></div>
            <div v-if="m.channel_refs?.length" class="route-targets">
              <div v-for="target in m.channel_refs" :key="target.id" class="route-target">
                <NavIcon name="server" :size="16" />
                <span class="route-target-copy"><span>{{ target.channel_name || target.inline_config?.name || '直连上游' }}</span><code class="secondary-text">{{ target.upstream_model_id || '未设置上游模型' }}</code></span>
                <span class="secondary-text">权重 {{ target.weight }}</span>
              </div>
            </div>
            <p v-else class="model-no-routes"><NavIcon name="warning" :size="16" />尚未配置路由目标</p>
          </div>
          <template #footer>
            <span class="secondary-text">{{ m.failover_enabled ? '已启用自动容灾' : '未启用自动容灾' }}</span>
            <UiButton variant="link" :loading="editingId === m.id" @click="openEdit(m)">配置模型</UiButton>
          </template>
        </UiCard>
      </div>
      <UiEmpty v-else :title="models.length ? '没有匹配的模型' : '暂无模型数据'" :description="models.length ? '尝试其他关键词，或清除筛选条件。' : '添加对外模型并配置路由目标，即可通过网关调用。'">
        <template #icon><NavIcon name="model" :size="32" /></template>
        <UiButton v-if="models.length" @click="search = ''; brandFilter = ''">清除筛选</UiButton>
        <UiButton v-else variant="primary" @click="openCreate">新建模型</UiButton>
      </UiEmpty>
    </UiSpinner>

    <UiDrawer
      v-model:open="dialogVisible"
      :busy="submitting"
      :before-close="beforeClose"
      @save="submitForm"
      :title="isEditing ? '编辑模型' : '新建模型'"
      width="760px"
    >
      <div class="stack">
        <div class="fields">
          <UiField label="模型名称"
            ><UiInput v-model="form.name" placeholder="请输入模型名称" class="w-full" /></UiField
          ><UiField label="显示名称"
            ><UiInput v-model="form.display_name" placeholder="请输入显示名称" class="w-full"
          /></UiField>
        </div>
        <div class="model-icon-editor">
          <ModelIcon :model="form.name" :icon="form.icon" :upstream-models="upstreamModelNames({ name: form.name, channel_refs: modelRefs })" :size="32" framed />
          <UiField label="模型图标">
            <UiSelect v-model="form.icon" :options="iconOptions" />
            <p class="secondary-text">手动选择后优先使用此图标；自动识别会参考模型名称和路由目标。</p>
          </UiField>
        </div>
        <UiField label="分配策略"
          ><UiSelect
            v-model="form.routing_strategy"
            :options="routingStrategyOptions"
            class="w-full"
        /></UiField>
        <UiField label="自定义JS"
          ><UiTextarea
            v-model="form.custom_js"
            rows="3"
            placeholder="function route(channels, ctx) { return channels.map(c => c.ref_id); }"
            class="form-input min-h-24 w-full py-2"
        /></UiField>
        <div class="fields">
          <UiCheckbox v-model="form.failover_enabled" label="启用自动容灾顺延" /><UiCheckbox
            v-model="form.is_listed"
            label="在 /v1/models 中列出"
          /><UiCheckbox v-model="form.supports_thinking" label="支持思考模式" />
        </div>
        <div class="fields">
          <UiField label="默认思考等级"
            ><UiSelect
              v-model="form.default_thinking_effort"
              :options="thinkingEffortOptions"
              :disabled="!form.supports_thinking"
              class="w-full" /></UiField
          ><UiField label="Claude 思考模式"
            ><UiSelect
              v-model="form.claude_thinking_mode"
              :options="claudeThinkingModeOptions"
              :disabled="!form.supports_thinking"
              class="w-full"
          /></UiField>
        </div>

        <fluent-divider />
        <div>
          <h3 class="text-sm font-semibold">路由目标</h3>
          <p class="mt-1 text-sm text-muted-foreground">
            可选择多个渠道，也可不选渠道直接配置上游。
          </p>
        </div>
        <p v-if="!isEditing" class="secondary-text">先保存模型后再添加路由目标。</p>
        <template v-else>
          <div v-if="modelRefs.length" class="space-y-2">
            <UiCard v-for="ref in modelRefs" :key="ref.id"
              ><div class="flex items-center justify-between gap-3">
                <div>
                  <p class="text-sm font-semibold">
                    {{ ref.channel_name || ref.inline_config?.name || 'inline' }}
                  </p>
                  <p class="text-xs text-muted-foreground">
                    {{ ref.type === 'inline' ? '直连上游' : '渠道引用' }} · 上游模型
                    {{ ref.upstream_model_id || '-' }} · 优先级 {{ ref.priority }} / 权重
                    {{ ref.weight }}
                  </p>
                </div>
                <UiButton
                  variant="link"
                  size="sm"
                  :loading="removingTargetId === ref.id"
                  @click="removeTarget(ref.id)"
                  >{{ removingTargetId === ref.id ? '移除中' : '移除' }}</UiButton
                >
              </div></UiCard
            >
          </div>
          <UiEmpty v-else title="暂无路由目标" />
          <p v-if="targetError" class="inline-feedback message-symbol-error" role="alert">
            <NavIcon name="error" />{{ targetError }}
          </p>
          <div class="fields">
            <UiField label="类型"
              ><UiSelect
                v-model="targetForm.type"
                :options="targetTypeOptions"
                class="w-full" /></UiField
            ><UiField label="权重"
              ><UiInput
                v-model.number="targetForm.weight"
                type="number"
                step="0.1"
                class="w-full" /></UiField
            ><UiField label="优先级"
              ><UiInput
                v-model.number="targetForm.priority"
                type="number"
                class="w-full" /></UiField
            ><UiField v-if="targetForm.type === 'reference'" label="渠道"
              ><UiSelect
                v-model="targetForm.channel_id"
                :options="channelOptions"
                placeholder="请选择渠道"
                class="w-full"
                @update:model-value="applySelectedChannelDefaultWeight" /></UiField
            ><UiField v-else label="上游名称"
              ><UiInput v-model="targetForm.inline_config.name" class="w-full"
            /></UiField>
          </div>
          <UiField v-if="targetForm.type === 'reference'" label="上游模型 ID"
            ><UiSelect
              v-model="targetForm.upstream_model_id"
              :options="selectedChannelModelOptions"
              :disabled="!selectedChannelModels().length"
              placeholder="请选择上游模型"
              class="w-full"
          /></UiField>
          <div v-if="targetForm.type === 'inline'" class="space-y-4">
            <div class="fields">
              <UiField label="提供商"
                ><UiSelect
                  v-model="targetForm.inline_config.provider"
                  :options="providerOptions"
                  class="w-full"
                  @update:model-value="applyInlineProviderDefaultApiType" /></UiField
              ><UiField label="上游接口类型"
                ><UiSelect
                  v-model="targetForm.inline_config.api_type"
                  :options="inlineApiTypeOptions"
                  class="w-full"
              /></UiField>
            </div>
            <UiField label="超时 (秒)"
              ><UiInput
                v-model.number="targetForm.inline_config.timeout"
                type="number"
                class="w-full" /></UiField
            ><UiField label="自定义请求头"
              ><HeaderEditor v-model="targetForm.inline_config.custom_headers" /></UiField
            ><UiField label="Base URL"
              ><UiInput
                v-model="targetForm.inline_config.base_url"
                placeholder="https://api.openai.com"
                class="w-full" /></UiField
            ><UiField label="上游模型 ID"
              ><UiInput
                v-model="targetForm.upstream_model_id"
                placeholder="例如 gpt-4o 或 claude-3-5-sonnet-latest"
                class="w-full" /></UiField
            ><UiField label="API Key"
              ><UiInput v-model="targetForm.inline_config.api_key" type="password" class="w-full"
            /></UiField>
          </div>
          <UiButton variant="primary" block :loading="targetSubmitting" @click="addTarget">{{
            targetSubmitting ? '添加中...' : '添加路由目标'
          }}</UiButton>
        </template>
      </div>
      <template #footer
        ><div class="flex justify-end gap-2">
          <UiButton @click="closeEditor">取消</UiButton
          ><UiButton variant="primary" :loading="submitting" @click="submitForm">保存</UiButton>
        </div></template
      >
    </UiDrawer>
  </div>
</template>

<script setup lang="ts">
import { useUnsavedForm } from '@/composables/useUnsavedChanges'
import UiSpinner from '@/components/ui/UiSpinner.vue'
import PageHeader from '@/components/PageHeader.vue'
import ListState from '@/components/ListState.vue'
import NavIcon from '@/components/NavIcon.vue'
import ModelIcon from '@/components/ModelIcon.vue'
import { modelIconOptions, resolveModelIdentity, upstreamModelNames } from '@/utils/modelIdentity'

import UiField from '@/components/ui/UiField.vue'
import UiInput from '@/components/ui/UiInput.vue'
import UiTextarea from '@/components/ui/UiTextarea.vue'
import UiCheckbox from '@/components/ui/UiCheckbox.vue'
import { computed, ref, onMounted } from 'vue'
import { Pencil, Trash2 } from 'lucide-vue-next'
import { listChannels } from '@/api/channels'
import {
  addModelChannel,
  createModel,
  deleteModel,
  deleteModelChannel,
  listModelChannels,
  listModels,
  updateModel,
} from '@/api/models'
import { useConfirm, useToast } from '@/composables/useFeedback'
import HeaderEditor from '@/components/HeaderEditor.vue'
import UiBadge from '@/components/ui/UiBadge.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiCard from '@/components/ui/UiCard.vue'
import UiDrawer from '@/components/ui/UiDrawer.vue'
import UiDropdown from '@/components/ui/UiDropdown.vue'
import UiDropdownItem from '@/components/ui/UiDropdownItem.vue'
import UiEmpty from '@/components/ui/UiEmpty.vue'
import UiSelect from '@/components/ui/UiSelect.vue'

const confirm = useConfirm()
const toast = useToast()

const models = ref<any[]>([])
const channels = ref<any[]>([])
const modelRefs = ref<any[]>([])
const loading = ref(true)
const loadError = ref('')
const dialogVisible = ref(false)
const isEditing = ref(false)
const submitting = ref(false)
const editingId = ref('')
const deletingModelId = ref('')
const removingTargetId = ref('')
const targetError = ref('')
const search = ref('')
const brandFilter = ref('')
const iconOptions = modelIconOptions.map(option => ({ ...option, icon: option.value }))
const modelIdentity = (m: any) => resolveModelIdentity(m.name, upstreamModelNames(m), m.icon)
const brandOptions = computed(() => [
  { label: '全部品牌', value: '' },
  ...Array.from(new Map(models.value.map(m => {
    const identity = modelIdentity(m)
    return [identity.id, { label: identity.label, value: identity.id }]
  })).values()),
])
const filteredModels = computed(() => {
  const query = search.value.trim().toLowerCase()
  return models.value.filter(m => (!brandFilter.value || modelIdentity(m).id === brandFilter.value)
    && (!query || [m.name, m.display_name, ...upstreamModelNames(m)].some(value => value?.toLowerCase().includes(query))))
})
const targetSubmitting = ref(false)
const form = ref<any>({
  name: '',
  display_name: '',
  icon: 'auto',
  routing_strategy: 'default',
  custom_js: '',
  failover_enabled: true,
  is_listed: true,
  supports_thinking: false,
  default_thinking_effort: 'none',
  claude_thinking_mode: 'adaptive',
})
const targetForm = ref<any>(newTargetForm())
const routingStrategyOptions = [
  { label: '默认（顺序）', value: 'default' },
  { label: '随机', value: 'random' },
  { label: '加权', value: 'weighted' },
  { label: '自定义JS', value: 'custom_js' },
]
const thinkingEffortOptions = [
  { label: '关闭', value: 'none' },
  { label: '低', value: 'low' },
  { label: '中', value: 'medium' },
  { label: '高', value: 'high' },
]
const claudeThinkingModeOptions = [
  { label: 'Adaptive', value: 'adaptive' },
  { label: '旧版 Enabled', value: 'enabled' },
  { label: 'Disabled', value: 'disabled' },
]
const providerOptions = [
  { label: 'OpenAI', value: 'openai' },
  { label: 'Anthropic', value: 'anthropic' },
  { label: 'Azure', value: 'azure' },
  { label: 'Google', value: 'google' },
  { label: 'Custom', value: 'custom' },
]
const targetTypeOptions = [
  { label: '选择渠道', value: 'reference' },
  { label: '直接上游', value: 'inline' },
]
const channelOptions = computed(() =>
  channels.value.map((ch) => ({
    label: `${ch.name}（默认权重 ${ch.default_weight}）`,
    value: ch.id,
  }))
)

const inlineApiTypeOptions = computed(() => apiTypeOptions(targetForm.value.inline_config.provider))
function newTargetForm() {
  return {
    type: channels.value.length ? 'reference' : 'inline',
    channel_id: '',
    upstream_model_id: '',
    priority: 0,
    weight: 1.0,
    inline_config: {
      name: '',
      provider: 'openai',
      api_type: 'openai',
      base_url: '',
      api_key: '',
      timeout: 30,
      max_retries: 2,
      custom_headers: [],
    },
  }
}
function defaultApiType(provider: string) {
  return provider === 'anthropic' ? 'claude' : 'openai'
}
function applyInlineProviderDefaultApiType() {
  targetForm.value.inline_config.api_type = defaultApiType(targetForm.value.inline_config.provider)
}
function headerItemsToObject(items: { key: string; value: string }[]) {
  const result: Record<string, string> = {}
  for (const item of items) if (item.key.trim()) result[item.key.trim()] = item.value
  return result
}
function apiTypeOptions(provider: string) {
  const openaiOptions = [
    { label: 'Auto', value: 'auto' },
    { label: 'OpenAI Chat Completions', value: 'openai' },
    { label: 'OpenAI Responses', value: 'responses' },
  ]
  if (provider === 'anthropic') return [{ label: 'Claude Messages', value: 'claude' }]
  if (provider === 'custom')
    return [...openaiOptions, { label: 'Claude Messages', value: 'claude' }]
  return openaiOptions
}
const selectedChannelModelOptions = computed(() =>
  selectedChannelModels().map((m: string) => ({ label: m, value: m }))
)
function modelPayload() {
  return {
    name: form.value.name,
    display_name: form.value.display_name,
    icon: form.value.icon,
    routing_strategy: form.value.routing_strategy,
    custom_js: form.value.custom_js,
    failover_enabled: form.value.failover_enabled,
    is_listed: form.value.is_listed,
    supports_thinking: form.value.supports_thinking,
    default_thinking_effort: form.value.default_thinking_effort,
    claude_thinking_mode: form.value.claude_thinking_mode,
  }
}
async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const [modelRes, channelRes] = await Promise.all([listModels(), listChannels()])
    models.value = modelRes.data || []
    channels.value = channelRes.data || []
  } catch (e) {
    loadError.value = '模型管理加载失败，请检查网络后重试'
  } finally {
    loading.value = false
  }
}
function openCreate() {
  isEditing.value = false
  form.value = {
    name: '',
    display_name: '',
    icon: 'auto',
    routing_strategy: 'default',
    custom_js: '',
    failover_enabled: true,
    is_listed: true,
    supports_thinking: false,
    default_thinking_effort: 'none',
    claude_thinking_mode: 'adaptive',
  }
  modelRefs.value = []
  targetError.value = ''
  targetForm.value = newTargetForm()
  dialogVisible.value = true
}
async function openEdit(m: any) {
  isEditing.value = true
  form.value = { ...m, icon: m.icon || 'auto' }
  targetForm.value = newTargetForm()
  targetError.value = ''
  try {
    editingId.value = m.id
    modelRefs.value = (await listModelChannels(m.id)).data || []
  } catch (e) {
    toast.error('操作失败，请检查配置后重试')
    modelRefs.value = m.channel_refs || []
  } finally {
    editingId.value = ''
  }
  dialogVisible.value = true
}
async function submitForm() {
  try {
    submitting.value = true
    if (isEditing.value) await updateModel(form.value.id, modelPayload())
    else await createModel(modelPayload())
    toast.success('保存成功')
    dialogVisible.value = false
    await load()
  } catch (e) {
    toast.error('操作失败，请检查配置后重试')
  } finally {
    submitting.value = false
  }
}
function applySelectedChannelDefaultWeight() {
  const selected = channels.value.find((ch) => ch.id === targetForm.value.channel_id)
  if (selected) {
    targetForm.value.weight = selected.default_weight
    targetForm.value.upstream_model_id = selected.upstream_models?.[0] || ''
  }
}
function selectedChannelModels() {
  return channels.value.find((ch) => ch.id === targetForm.value.channel_id)?.upstream_models || []
}
async function refreshModelRefs() {
  modelRefs.value = (await listModelChannels(form.value.id)).data || []
}
async function addTarget() {
  targetError.value = ''
  if (!form.value.id) return (targetError.value = '请先保存模型，再添加路由目标')
  const data: Record<string, any> = {
    type: targetForm.value.type,
    priority: targetForm.value.priority,
    weight: targetForm.value.weight,
    upstream_model_id: targetForm.value.upstream_model_id,
  }
  if (targetForm.value.type === 'reference') {
    if (!targetForm.value.channel_id) return (targetError.value = '请选择一个渠道')
    if (!targetForm.value.upstream_model_id)
      return (targetError.value = '请选择该渠道要代理的上游模型 ID')
    data.channel_id = targetForm.value.channel_id
  } else {
    data.inline_config = {
      ...targetForm.value.inline_config,
      custom_headers: headerItemsToObject(targetForm.value.inline_config.custom_headers || []),
    }
    if (!data.inline_config.name) return (targetError.value = '请填写上游名称')
    if (!data.inline_config.base_url) return (targetError.value = '请填写上游 Base URL')
    if (!targetForm.value.upstream_model_id)
      return (targetError.value = '请填写要代理的上游模型 ID')
  }
  try {
    targetSubmitting.value = true
    await addModelChannel(form.value.id, data)
    targetForm.value = newTargetForm()
    await refreshModelRefs()
    await load()
  } catch (e) {
    toast.error('操作失败，请检查配置后重试')
    targetError.value = '添加失败，请检查配置或查看后端日志'
  } finally {
    targetSubmitting.value = false
  }
}
async function removeTarget(refId: string) {
  if (!form.value.id) return
  const ok = await confirm({
    title: '确认移除',
    content: '确定移除该路由目标吗？',
    positiveText: '移除',
    negativeText: '取消',
    variant: 'danger',
  })
  if (!ok) return
  removingTargetId.value = refId
  try {
    await deleteModelChannel(form.value.id, refId)
    await refreshModelRefs()
    await load()
  } catch (e) {
    toast.error('操作失败，请检查配置后重试')
  } finally {
    removingTargetId.value = ''
  }
}
async function deleteModelItem(id: string) {
  const ok = await confirm({
    title: '确认删除',
    content: '确定删除该模型配置吗？',
    positiveText: '删除',
    negativeText: '取消',
    variant: 'danger',
  })
  if (!ok) return
  deletingModelId.value = id
  try {
    await deleteModel(id)
    toast.success('模型已删除')
    await load()
  } catch (e) {
    toast.error('操作失败，请检查配置后重试')
  } finally {
    deletingModelId.value = ''
  }
}
const { beforeClose, closeEditor } = useUnsavedForm(
  dialogVisible,
  () => ({ form: form.value, target: targetForm.value }),
  submitting
)

onMounted(load)
</script>
