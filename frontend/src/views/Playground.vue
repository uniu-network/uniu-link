<template>
  <div class="page-stack">
    <PageHeader title="演练场" description="通过网关发送请求，验证模型输出与协议兼容性。"
      ><UiButton :loading="loading" :disabled="sending" @click="load"
        ><NavIcon name="refresh" />刷新模型</UiButton
      ></PageHeader
    >
    <ListState :error="loadError" @retry="load" />
    <div class="playground-layout">
      <fluent-card class="ui-card"
        ><section class="chat-shell">
          <header class="chat-header">
            <div class="chat-identity">
              <ModelIcon :model="selectedModel" :icon="selectedModelConfig?.icon" :upstream-models="upstreamModelNames(selectedModelConfig)" :size="24" framed />
              <div><h2>会话</h2>
              <p class="secondary-text">
                {{ selectedModel || '未选择模型' }} · {{ selectedApiLabel }}
              </p></div>
            </div>
            <UiButton
              variant="ghost"
              size="icon"
              aria-label="清空对话"
              title="清空对话"
              :disabled="sending || !messages.length"
              @click="clearMessages"
              ><Trash2
            /></UiButton>
          </header>
          <fluent-divider />
          <div class="chat-content">
            <UiSpinner :show="loading">
              <UiEmpty
                v-if="!messages.length"
                title="开始一次模型演练"
                description="选择协议和模型，输入消息后发送。"
                ><template #icon><NavIcon name="comment" /></template
              ></UiEmpty>
              <article v-for="item in messages" :key="item.id" class="chat-message reveal-item" :class="{ 'chat-message-user': item.role === 'user' }">
                <p
                  class="chat-role"
                  :class="
                    item.role === 'error'
                      ? 'message-symbol-error'
                      : item.role === 'user'
                        ? 'brand-color'
                        : ''
                  "
                >
                  <ModelIcon v-if="item.role === 'assistant'" :model="item.model" :icon="modelConfig(item.model)?.icon" :upstream-models="upstreamModelNames(modelConfig(item.model))" :size="18" />
                  {{ item.role === 'user' ? '你' : item.role === 'error' ? '错误' : '模型' }}
                </p>
                <details v-if="item.thinking" open class="chat-thinking">
                  <summary>思考过程</summary>
                  <p class="chat-text secondary-text">{{ item.thinking }}</p>
                </details>
                <p v-if="item.content" class="chat-text">{{ item.content }}</p>
                <p
                  v-else-if="sending && item.role === 'assistant' && !item.thinking"
                  role="status"
                  class="inline-feedback secondary-text"
                >
                  <fluent-progress-ring class="button-progress" aria-label="等待模型输出" />思考中…
                </p>
              </article>
            </UiSpinner>
          </div>
          <fluent-divider />
          <footer class="chat-composer">
            <UiTextarea
              v-model="input"
              rows="3"
              aria-label="用户消息"
              placeholder="输入用户消息，Enter 换行"
            />
            <div class="mt-3 flex flex-wrap items-center justify-between gap-3">
              <p class="secondary-text">当前协议：{{ selectedApiLabel }}</p>
              <UiButton
                variant="primary"
                :loading="sending"
                :disabled="!canSend || loading"
                @click="sendMessage"
                ><Send v-if="!sending" />{{ sending ? '发送中…' : '发送' }}</UiButton
              >
            </div>
          </footer>
        </section></fluent-card
      >
      <UiCard title="参数设置" class="playground-settings">
        <template #extra
          ><UiButton
            variant="ghost"
            size="icon"
            :aria-label="advancedSettingsOpen ? '收起高级参数' : '展开高级参数'"
            :aria-expanded="advancedSettingsOpen"
            aria-controls="advanced-parameters"
            @click="advancedSettingsOpen = !advancedSettingsOpen"
            ><SlidersHorizontal /></UiButton
        ></template>
        <div class="stack">
          <UiField label="API 协议"
            ><UiSelect v-model="apiMode" :options="apiModeOptions" :disabled="sending"
          /></UiField>
          <UiField label="模型"
            ><UiSelect
              v-model="selectedModel"
              :options="modelOptions"
              placeholder="请选择模型"
              :disabled="sending"
          /></UiField>
          <div
            id="advanced-parameters"
            class="advanced-parameters"
            :class="{ 'advanced-open': advancedSettingsOpen }"
          >
            <div class="stack">
              <fluent-divider />
              <UiField label="流式输出"
                ><UiSelect v-model="stream" :options="streamOptions" :disabled="sending"
              /></UiField>
              <UiField label="思考强度"
                ><UiSelect v-model="thinking" :options="thinkingOptions" :disabled="sending"
              /></UiField>
              <UiField label="Temperature"
                ><UiInput
                  v-model.number="temperature"
                  type="number"
                  min="0"
                  max="2"
                  step="0.1"
                  placeholder="不传"
                  :disabled="sending"
              /></UiField>
              <UiField label="Max Tokens"
                ><UiInput
                  v-model.number="maxTokens"
                  type="number"
                  min="1"
                  placeholder="不传"
                  :disabled="sending"
              /></UiField>
              <UiField label="System / Instructions"
                ><UiTextarea
                  v-model="systemPrompt"
                  rows="3"
                  placeholder="可选系统提示词"
                  :disabled="sending"
              /></UiField>
              <UiField label="自定义参数 JSON"
                ><div class="flex justify-end">
                  <UiButton variant="link" :disabled="sending" @click="customParams = '{}'"
                    >重置</UiButton
                  >
                </div>
                <UiTextarea v-model="customParams" rows="6" :disabled="sending" />
                <p class="secondary-text">
                  合并到请求体中，模型、流式和思考强度以表单配置为准。
                </p></UiField
              >
              <fluent-divider />
              <details>
                <summary>请求预览</summary>
                <pre class="request-preview mt-3">{{ requestPreview }}</pre>
              </details>
            </div>
          </div>
        </div>
      </UiCard>
    </div>
  </div>
</template>

<script setup lang="ts">
import PageHeader from '@/components/PageHeader.vue'
import NavIcon from '@/components/NavIcon.vue'
import ModelIcon from '@/components/ModelIcon.vue'
import { upstreamModelNames } from '@/utils/modelIdentity'
import ListState from '@/components/ListState.vue'
import UiCard from '@/components/ui/UiCard.vue'

import UiField from '@/components/ui/UiField.vue'
import UiInput from '@/components/ui/UiInput.vue'
import UiTextarea from '@/components/ui/UiTextarea.vue'
import { computed, onMounted, ref } from 'vue'
import { Send, SlidersHorizontal, Trash2 } from 'lucide-vue-next'
import { listModels } from '@/api/models'
import { authFetch } from '@/utils/authFetch'
import { useConfirm, useToast } from '@/composables/useFeedback'
import UiButton from '@/components/ui/UiButton.vue'
import UiEmpty from '@/components/ui/UiEmpty.vue'
import UiSelect from '@/components/ui/UiSelect.vue'
import UiSpinner from '@/components/ui/UiSpinner.vue'

const toast = useToast()
const confirm = useConfirm()

const loading = ref(true)
const loadError = ref('')
const sending = ref(false)
const models = ref<any[]>([])
const messages = ref<ChatMessage[]>([])
const input = ref('')
const advancedSettingsOpen = ref(false)

const apiMode = ref<ApiMode>('openai_chat')
const selectedModel = ref('')
const stream = ref<'true' | 'false'>('true')
const thinking = ref<'none' | 'low' | 'medium' | 'high'>('none')
const temperature = ref<number | null>(null)
const maxTokens = ref<number | null>(null)
const systemPrompt = ref('')
const customParams = ref('{}')
let messageSeed = 0

type ApiMode = 'openai_responses' | 'openai_chat' | 'claude_messages'
type ChatRole = 'user' | 'assistant' | 'error'

interface ChatMessage {
  model?: string
  id: number
  role: ChatRole
  content: string
  thinking: string
}

const apiConfig: Record<ApiMode, { label: string; endpoint: string }> = {
  openai_responses: { label: 'OpenAI Responses', endpoint: '/v1/responses' },
  openai_chat: {
    label: 'OpenAI Completions',
    endpoint: '/v1/chat/completions',
  },
  claude_messages: { label: 'Claude Messages', endpoint: '/v1/messages' },
}

function apiTypeForEndpoint(mode: ApiMode): string {
  if (mode === 'openai_responses') return 'responses'
  if (mode === 'claude_messages') return 'claude'
  return 'openai'
}

const apiModeOptions = [
  { label: 'OpenAI Responses', value: 'openai_responses' },
  { label: 'OpenAI Completions', value: 'openai_chat' },
  { label: 'Claude Messages', value: 'claude_messages' },
]

const modelConfig = (name?: string) => models.value.find(m => m.name === name)
const selectedModelConfig = computed(() => modelConfig(selectedModel.value))

const modelOptions = computed(() =>
  models.value.map((m) => ({
    label: m.display_name || m.name,
    value: m.name,
    model: m.name,
    icon: m.icon,
    upstreamModels: upstreamModelNames(m),
  }))
)

const streamOptions = [
  { label: '开启', value: 'true' },
  { label: '关闭', value: 'false' },
]

const thinkingOptions = [
  { label: '关闭', value: 'none' },
  { label: '低', value: 'low' },
  { label: '中', value: 'medium' },
  { label: '高', value: 'high' },
]

const selectedApiLabel = computed(() => apiConfig[apiMode.value].label)
const canSend = computed(() => !!selectedModel.value && !!input.value.trim())
const requestPreview = computed(() => {
  try {
    return JSON.stringify(buildRequestBody(input.value || '你好'), null, 2)
  } catch (error) {
    return error instanceof Error ? error.message : '自定义参数 JSON 格式错误'
  }
})

function nextId() {
  messageSeed += 1
  return messageSeed
}

function conversationForRequest(nextUserMessage: string) {
  const completedTurns: Array<{ role: 'user' | 'assistant'; content: string }> = []
  const history = messages.value.filter((item) => item.role === 'user' || item.role === 'assistant')

  for (let index = 0; index < history.length; index += 1) {
    const user = history[index]
    const assistant = history[index + 1]
    if (
      user?.role === 'user' &&
      assistant?.role === 'assistant' &&
      user.content.trim() &&
      assistant.content.trim()
    ) {
      completedTurns.push(
        { role: 'user', content: user.content },
        { role: 'assistant', content: assistant.content }
      )
      index += 1
    }
  }

  return [...completedTurns, { role: 'user' as const, content: nextUserMessage }]
}

function optionalNumber(value: number | null) {
  if (value === null || value === undefined) return undefined
  return Number.isFinite(value) ? value : undefined
}

function applyOptionalGenerationParams(
  body: Record<string, any>,
  maxTokenField: 'max_tokens' | 'max_output_tokens'
) {
  const parsedTemperature = optionalNumber(temperature.value)
  const parsedMaxTokens = optionalNumber(maxTokens.value)
  if (parsedTemperature !== undefined) {
    body.temperature = parsedTemperature
  }
  if (parsedMaxTokens !== undefined) {
    body[maxTokenField] = parsedMaxTokens
  }
}

function parseCustomParams() {
  const value = customParams.value.trim()
  if (!value) return {}
  const parsed = JSON.parse(value)
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error('自定义参数必须是 JSON 对象')
  }
  return parsed
}

function applyThinking(body: Record<string, any>) {
  if (thinking.value === 'none') return

  if (apiMode.value === 'claude_messages') {
    body.thinking = { type: 'adaptive', display: 'summarized' }
    body.output_config = { ...(body.output_config || {}), effort: thinking.value }
    return
  }

  if (apiMode.value === 'openai_responses') {
    body.reasoning = { ...(body.reasoning || {}), effort: thinking.value }
    return
  }

  body.reasoning_effort = thinking.value
}

function buildRequestBody(nextUserMessage: string) {
  const conversation = conversationForRequest(nextUserMessage)
  const custom = parseCustomParams()
  let body: Record<string, any>

  if (apiMode.value === 'openai_responses') {
    body = {
      model: selectedModel.value,
      input: conversation.map((item) => ({
        role: item.role,
        content: item.content,
      })),
    }
    applyOptionalGenerationParams(body, 'max_output_tokens')
    if (systemPrompt.value.trim()) {
      body.instructions = systemPrompt.value.trim()
    }
  } else if (apiMode.value === 'claude_messages') {
    body = {
      model: selectedModel.value,
      messages: conversation.map((item) => ({
        role: item.role,
        content: item.content,
      })),
    }
    applyOptionalGenerationParams(body, 'max_tokens')
    if (systemPrompt.value.trim()) {
      body.system = systemPrompt.value.trim()
    }
  } else {
    body = {
      model: selectedModel.value,
      messages: [
        ...(systemPrompt.value.trim()
          ? [{ role: 'system', content: systemPrompt.value.trim() }]
          : []),
        ...conversation.map((item) => ({
          role: item.role,
          content: item.content,
        })),
      ],
    }
    applyOptionalGenerationParams(body, 'max_tokens')
  }

  body = { ...body, ...custom }
  body.model = selectedModel.value
  body.stream = stream.value === 'true'
  applyThinking(body)
  return body
}

function extractTextFromResponse(data: any): {
  content: string
  thinking: string
} {
  if (!data) return { content: '', thinking: '' }
  if (typeof data.output_text === 'string') {
    let thinking = ''
    if (Array.isArray(data.output)) {
      for (const item of data.output) {
        if (item.type === 'reasoning') {
          const texts = (item.summary || item.content || [])
            .map((c: any) => c.text || '')
            .filter(Boolean)
          thinking += texts.join('')
        }
      }
    }
    return { content: data.output_text, thinking }
  }
  if (Array.isArray(data.output)) {
    let content = ''
    let thinking = ''
    for (const item of data.output) {
      if (item.type === 'reasoning') {
        const texts = (item.summary || item.content || [])
          .map((c: any) => c.text || '')
          .filter(Boolean)
        thinking += texts.join('')
      } else {
        const texts = (item.content || [])
          .map((c: any) => c.text || c.output_text || '')
          .filter(Boolean)
        content += texts.join('')
      }
    }
    return { content, thinking }
  }
  if (Array.isArray(data.choices)) {
    const choice = data.choices[0]
    const content = choice?.message?.content || choice?.text || ''
    const thinking = choice?.message?.reasoning_content || choice?.message?.reasoning || ''
    return { content, thinking }
  }
  if (Array.isArray(data.content)) {
    let content = ''
    let thinking = ''
    for (const item of data.content) {
      if (item.type === 'thinking') {
        thinking += item.thinking || ''
      } else {
        content += item.text || ''
      }
    }
    return { content, thinking }
  }
  return { content: JSON.stringify(data, null, 2), thinking: '' }
}

function extractStreamContent(data: any): string {
  if (!data || data === '[DONE]') return ''
  if (data.type === 'response.output_text.delta') return data.delta || ''
  if (data.type === 'response.reasoning_summary_text.delta') return ''
  if (data.type === 'response.reasoning_text.delta') return ''
  if (data.type === 'content_block_delta') {
    if (data.delta?.type === 'thinking_delta') return ''
    return data.delta?.text || ''
  }
  if (data.choices?.[0]?.delta?.content) return data.choices[0].delta.content
  if (data.choices?.[0]?.delta?.reasoning_content) return ''
  if (data.choices?.[0]?.delta?.reasoning) return ''
  if (data.delta?.type === 'thinking_delta') return ''
  if (data.delta?.thinking) return ''
  if (data.delta?.text) return data.delta.text
  if (typeof data.delta === 'string') return data.delta
  return ''
}

function extractStreamThinking(data: any): string {
  if (!data || data === '[DONE]') return ''
  if (data.type === 'response.reasoning_summary_text.delta') return data.delta || ''
  if (data.type === 'response.reasoning_text.delta') return data.delta || ''
  if (data.type === 'content_block_delta' && data.delta?.type === 'thinking_delta')
    return data.delta.thinking || ''
  if (data.choices?.[0]?.delta?.reasoning_content) return data.choices[0].delta.reasoning_content
  if (data.choices?.[0]?.delta?.reasoning) return data.choices[0].delta.reasoning
  if (data.delta?.type === 'thinking_delta') return data.delta.thinking || ''
  if (data.delta?.thinking) return data.delta.thinking
  return ''
}

async function readStream(response: Response, msgIndex: number) {
  const reader = response.body?.getReader()
  if (!reader) return

  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    const chunks = buffer.split('\n\n')
    buffer = chunks.pop() || ''

    for (const chunk of chunks) {
      const dataLines = chunk
        .split('\n')
        .filter((line) => line.startsWith('data:'))
        .map((line) => line.replace(/^data:\s*/, ''))

      for (const line of dataLines) {
        if (!line || line === '[DONE]') continue
        try {
          const parsed = JSON.parse(line)
          const contentDelta = extractStreamContent(parsed)
          const thinkingDelta = extractStreamThinking(parsed)
          if (thinkingDelta) messages.value[msgIndex].thinking += thinkingDelta
          if (contentDelta) messages.value[msgIndex].content += contentDelta
        } catch {
          messages.value[msgIndex].content += line
        }
      }
    }
  }
}

async function sendMessage() {
  if (!canSend.value || sending.value) return

  const userText = input.value.trim()
  let body: Record<string, any>
  try {
    body = buildRequestBody(userText)
  } catch (error) {
    toast.warning(error instanceof Error ? error.message : '自定义参数 JSON 格式错误')
    return
  }

  const userMessage: ChatMessage = {
    id: nextId(),
    role: 'user',
    content: userText,
    thinking: '',
  }
  const assistantMessage: ChatMessage = {
    id: nextId(),
    role: 'assistant',
    model: selectedModel.value,
    content: '',
    thinking: '',
  }
  messages.value.push(userMessage, assistantMessage)
  const msgIndex = messages.value.length - 1
  input.value = ''
  sending.value = true

  try {
    const response = await authFetch('/api/admin/playground', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        ...body,
        _api_type: apiTypeForEndpoint(apiMode.value),
      }),
    })

    if (!response.ok) {
      const errorText = await response.text()
      throw new Error(errorText || `HTTP ${response.status}`)
    }

    if (stream.value === 'true') {
      await readStream(response, msgIndex)
    } else {
      const data = await response.json()
      const extracted = extractTextFromResponse(data)
      messages.value[msgIndex].content = extracted.content
      messages.value[msgIndex].thinking = extracted.thinking
    }

    if (!messages.value[msgIndex].content && !messages.value[msgIndex].thinking) {
      messages.value[msgIndex].content = '[无文本输出]'
    }
  } catch (error) {
    messages.value[msgIndex].role = 'error'
    messages.value[msgIndex].content = error instanceof Error ? error.message : '请求失败'
  } finally {
    sending.value = false
  }
}

async function clearMessages() {
  if (
    await confirm({
      title: '清空对话？',
      content: '本次会话的所有消息将被清除。',
      positiveText: '清空对话',
    })
  )
    messages.value = []
}

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const res = await listModels()
    models.value = res.data || []
    selectedModel.value = models.value[0]?.name || ''
  } catch (error) {
    loadError.value = '模型列表加载失败，请检查网络后重试'
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>
