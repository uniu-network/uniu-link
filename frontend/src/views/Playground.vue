<template>
  <div class="grid min-h-[calc(100vh-8rem)] gap-6 xl:grid-cols-[1fr_380px]">
    <div class="flex min-h-[680px] flex-col rounded-xl border border-border bg-card shadow-sm">
      <div class="flex items-center justify-between border-b border-border p-4">
        <UiButton :disabled="sending || !messages.length" @click="clearMessages"><Trash2 class="h-4 w-4" />清空对话</UiButton>
      </div>
      <UiSpinner :show="loading" class="flex-1">
        <div class="flex-1 overflow-auto p-4 thin-scrollbar">
          <UiEmpty v-if="!messages.length" title="开始一次模型演练" description="选择协议和模型，输入消息后发送。">
            <template #icon><MessageSquareText class="mb-3 h-10 w-10 text-muted-foreground" /></template>
          </UiEmpty>
          <div v-else class="space-y-3">
            <UiCard v-for="item in messages" :key="item.id">
              <p class="mb-2 text-sm font-semibold" :class="item.role === 'error' ? 'text-red-600 dark:text-red-400' : item.role === 'user' ? 'text-foreground' : 'text-muted-foreground'">{{ item.role === 'user' ? '你' : item.role === 'error' ? '错误' : '模型' }}</p>
              <details v-if="item.thinking" open class="mb-3 rounded-lg border border-border p-3"><summary class="cursor-pointer text-sm font-medium">思考过程</summary><p class="mt-2 whitespace-pre-wrap text-xs text-muted-foreground">{{ item.thinking }}</p></details>
              <p v-if="item.content" class="whitespace-pre-wrap text-sm leading-6">{{ item.content }}</p>
              <p v-else-if="sending && item.role === 'assistant' && !item.thinking" class="text-sm text-muted-foreground">思考中...</p>
            </UiCard>
          </div>
        </div>
      </UiSpinner>
      <div class="border-t border-border p-4">
        <textarea v-model="input" rows="3" placeholder="输入用户消息，Enter 换行" class="form-input min-h-24 w-full py-2" />
        <div class="mt-3 flex items-center justify-between gap-3"><p class="text-sm text-muted-foreground">当前协议：{{ selectedApiLabel }}</p><UiButton variant="primary" :loading="sending" :disabled="!canSend" @click="sendMessage"><Send v-if="!sending" class="h-4 w-4" />{{ sending ? '发送中...' : '发送' }}</UiButton></div>
      </div>
    </div>

    <UiCard title="参数设置" class="h-fit">
      <div class="space-y-4">
        <Field label="API 协议"><select v-model="apiMode" class="form-input w-full"><option v-for="option in apiModeOptions" :key="option.value" :value="option.value">{{ option.label }}</option></select></Field>
        <Field label="模型"><select v-model="selectedModel" class="form-input w-full"><option value="">请选择模型</option><option v-for="option in modelOptions" :key="option.value" :value="option.value">{{ option.label }}</option></select></Field>
        <div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-1 2xl:grid-cols-2"><Field label="流式输出"><select v-model="stream" class="form-input w-full"><option v-for="option in streamOptions" :key="option.value" :value="option.value">{{ option.label }}</option></select></Field><Field label="思考强度"><select v-model="thinking" class="form-input w-full"><option v-for="option in thinkingOptions" :key="option.value" :value="option.value">{{ option.label }}</option></select></Field></div>
        <div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-1 2xl:grid-cols-2"><Field label="Temperature"><input v-model.number="temperature" type="number" min="0" max="2" step="0.1" placeholder="不传" class="form-input w-full" /></Field><Field label="Max Tokens"><input v-model.number="maxTokens" type="number" min="1" placeholder="不传" class="form-input w-full" /></Field></div>
        <Field label="System / Instructions"><textarea v-model="systemPrompt" rows="4" placeholder="可选系统提示词" class="form-input min-h-28 w-full py-2" /></Field>
        <Field label="自定义参数 JSON"><div class="mb-2 flex justify-end"><UiButton variant="link" size="sm" @click="customParams = '{}'">重置</UiButton></div><textarea v-model="customParams" rows="8" class="form-input min-h-48 w-full py-2" /><p class="mt-1 text-xs text-muted-foreground">会合并到请求体中，模型、流式和思考强度以表单配置为准。</p></Field>
        <UiCard title="请求预览"><pre class="max-h-80 overflow-auto whitespace-pre-wrap rounded-lg bg-muted p-3 text-xs thin-scrollbar">{{ requestPreview }}</pre></UiCard>
      </div>
    </UiCard>
  </div>
</template>

<script setup lang="ts">
import { computed, defineComponent, onMounted, ref, h } from "vue";
import { Trash2, MessageSquareText, Send } from "lucide-vue-next";
import { listModels } from "@/api/models";
import { authFetch } from "@/utils/authFetch";
import { useToast } from "@/composables/useFeedback";
import UiButton from "@/components/ui/UiButton.vue";
import UiCard from "@/components/ui/UiCard.vue";
import UiEmpty from "@/components/ui/UiEmpty.vue";
import UiSpinner from "@/components/ui/UiSpinner.vue";

const Field = defineComponent({ props: { label: String }, setup(props, { slots }) { return () => h('label', { class: 'block space-y-2 text-sm font-medium' }, [h('span', props.label), slots.default?.()]) } });
const toast = useToast();

const loading = ref(true);
const sending = ref(false);
const models = ref<any[]>([]);
const messages = ref<ChatMessage[]>([]);
const input = ref("");

const apiMode = ref<ApiMode>("openai_chat");
const selectedModel = ref("");
const stream = ref<"true" | "false">("true");
const thinking = ref<"none" | "low" | "medium" | "high">("none");
const temperature = ref<number | null>(null);
const maxTokens = ref<number | null>(null);
const systemPrompt = ref("");
const customParams = ref("{}");
let messageSeed = 0;

type ApiMode = "openai_responses" | "openai_chat" | "claude_messages";
type ChatRole = "user" | "assistant" | "error";

interface ChatMessage {
  id: number;
  role: ChatRole;
  content: string;
  thinking: string;
}

const apiConfig: Record<ApiMode, { label: string; endpoint: string }> = {
  openai_responses: { label: "OpenAI Responses", endpoint: "/v1/responses" },
  openai_chat: {
    label: "OpenAI Completions",
    endpoint: "/v1/chat/completions",
  },
  claude_messages: { label: "Claude Messages", endpoint: "/v1/messages" },
};

function apiTypeForEndpoint(mode: ApiMode): string {
  if (mode === "openai_responses") return "responses";
  if (mode === "claude_messages") return "claude";
  return "openai";
}

const apiModeOptions = [
  { label: "OpenAI Responses", value: "openai_responses" },
  { label: "OpenAI Completions", value: "openai_chat" },
  { label: "Claude Messages", value: "claude_messages" },
];

const modelOptions = computed(() =>
  models.value.map((m) => ({
    label: m.display_name || m.name,
    value: m.name,
  })),
);

const streamOptions = [
  { label: "开启", value: "true" },
  { label: "关闭", value: "false" },
];

const thinkingOptions = [
  { label: "关闭", value: "none" },
  { label: "低", value: "low" },
  { label: "中", value: "medium" },
  { label: "高", value: "high" },
];

const selectedApiLabel = computed(() => apiConfig[apiMode.value].label);
const canSend = computed(() => !!selectedModel.value && !!input.value.trim());
const requestPreview = computed(() => {
  try {
    return JSON.stringify(buildRequestBody(input.value || "你好"), null, 2);
  } catch (error) {
    return error instanceof Error ? error.message : "自定义参数 JSON 格式错误";
  }
});

function nextId() {
  messageSeed += 1;
  return messageSeed;
}

function conversationForRequest(nextUserMessage: string) {
  const completedTurns: Array<{ role: "user" | "assistant"; content: string }> =
    [];
  const history = messages.value.filter(
    (item) => item.role === "user" || item.role === "assistant",
  );

  for (let index = 0; index < history.length; index += 1) {
    const user = history[index];
    const assistant = history[index + 1];
    if (
      user?.role === "user" &&
      assistant?.role === "assistant" &&
      user.content.trim() &&
      assistant.content.trim()
    ) {
      completedTurns.push(
        { role: "user", content: user.content },
        { role: "assistant", content: assistant.content },
      );
      index += 1;
    }
  }

  return [
    ...completedTurns,
    { role: "user" as const, content: nextUserMessage },
  ];
}

function optionalNumber(value: number | null) {
  if (value === null || value === undefined) return undefined;
  return Number.isFinite(value) ? value : undefined;
}

function applyOptionalGenerationParams(
  body: Record<string, any>,
  maxTokenField: "max_tokens" | "max_output_tokens",
) {
  const parsedTemperature = optionalNumber(temperature.value);
  const parsedMaxTokens = optionalNumber(maxTokens.value);
  if (parsedTemperature !== undefined) {
    body.temperature = parsedTemperature;
  }
  if (parsedMaxTokens !== undefined) {
    body[maxTokenField] = parsedMaxTokens;
  }
}

function parseCustomParams() {
  const value = customParams.value.trim();
  if (!value) return {};
  const parsed = JSON.parse(value);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("自定义参数必须是 JSON 对象");
  }
  return parsed;
}

function applyThinking(body: Record<string, any>) {
  if (thinking.value === "none") return;

  if (apiMode.value === "claude_messages") {
    body.thinking = { type: "adaptive", display: "summarized" };
    body.output_config = { ...(body.output_config || {}), effort: thinking.value };
    return;
  }

  if (apiMode.value === "openai_responses") {
    body.reasoning = { ...(body.reasoning || {}), effort: thinking.value };
    return;
  }

  body.reasoning_effort = thinking.value;
}

function buildRequestBody(nextUserMessage: string) {
  const conversation = conversationForRequest(nextUserMessage);
  const custom = parseCustomParams();
  let body: Record<string, any>;

  if (apiMode.value === "openai_responses") {
    body = {
      model: selectedModel.value,
      input: conversation.map((item) => ({
        role: item.role,
        content: item.content,
      })),
    };
    applyOptionalGenerationParams(body, "max_output_tokens");
    if (systemPrompt.value.trim()) {
      body.instructions = systemPrompt.value.trim();
    }
  } else if (apiMode.value === "claude_messages") {
    body = {
      model: selectedModel.value,
      messages: conversation.map((item) => ({
        role: item.role,
        content: item.content,
      })),
    };
    applyOptionalGenerationParams(body, "max_tokens");
    if (systemPrompt.value.trim()) {
      body.system = systemPrompt.value.trim();
    }
  } else {
    body = {
      model: selectedModel.value,
      messages: [
        ...(systemPrompt.value.trim()
          ? [{ role: "system", content: systemPrompt.value.trim() }]
          : []),
        ...conversation.map((item) => ({
          role: item.role,
          content: item.content,
        })),
      ],
    };
    applyOptionalGenerationParams(body, "max_tokens");
  }

  body = { ...body, ...custom };
  body.model = selectedModel.value;
  body.stream = stream.value === "true";
  applyThinking(body);
  return body;
}

function extractTextFromResponse(data: any): {
  content: string;
  thinking: string;
} {
  if (!data) return { content: "", thinking: "" };
  if (typeof data.output_text === "string") {
    let thinking = "";
    if (Array.isArray(data.output)) {
      for (const item of data.output) {
        if (item.type === "reasoning") {
          const texts = (item.summary || item.content || [])
            .map((c: any) => c.text || "")
            .filter(Boolean);
          thinking += texts.join("");
        }
      }
    }
    return { content: data.output_text, thinking };
  }
  if (Array.isArray(data.output)) {
    let content = "";
    let thinking = "";
    for (const item of data.output) {
      if (item.type === "reasoning") {
        const texts = (item.summary || item.content || [])
          .map((c: any) => c.text || "")
          .filter(Boolean);
        thinking += texts.join("");
      } else {
        const texts = (item.content || [])
          .map((c: any) => c.text || c.output_text || "")
          .filter(Boolean);
        content += texts.join("");
      }
    }
    return { content, thinking };
  }
  if (Array.isArray(data.choices)) {
    const choice = data.choices[0];
    const content = choice?.message?.content || choice?.text || "";
    const thinking =
      choice?.message?.reasoning_content || choice?.message?.reasoning || "";
    return { content, thinking };
  }
  if (Array.isArray(data.content)) {
    let content = "";
    let thinking = "";
    for (const item of data.content) {
      if (item.type === "thinking") {
        thinking += item.thinking || "";
      } else {
        content += item.text || "";
      }
    }
    return { content, thinking };
  }
  return { content: JSON.stringify(data, null, 2), thinking: "" };
}

function extractStreamContent(data: any): string {
  if (!data || data === "[DONE]") return "";
  if (data.type === "response.output_text.delta") return data.delta || "";
  if (data.type === "response.reasoning_summary_text.delta") return "";
  if (data.type === "response.reasoning_text.delta") return "";
  if (data.type === "content_block_delta") {
    if (data.delta?.type === "thinking_delta") return "";
    return data.delta?.text || "";
  }
  if (data.choices?.[0]?.delta?.content) return data.choices[0].delta.content;
  if (data.choices?.[0]?.delta?.reasoning_content) return "";
  if (data.choices?.[0]?.delta?.reasoning) return "";
  if (data.delta?.type === "thinking_delta") return "";
  if (data.delta?.thinking) return "";
  if (data.delta?.text) return data.delta.text;
  if (typeof data.delta === "string") return data.delta;
  return "";
}

function extractStreamThinking(data: any): string {
  if (!data || data === "[DONE]") return "";
  if (data.type === "response.reasoning_summary_text.delta")
    return data.delta || "";
  if (data.type === "response.reasoning_text.delta") return data.delta || "";
  if (
    data.type === "content_block_delta" &&
    data.delta?.type === "thinking_delta"
  )
    return data.delta.thinking || "";
  if (data.choices?.[0]?.delta?.reasoning_content)
    return data.choices[0].delta.reasoning_content;
  if (data.choices?.[0]?.delta?.reasoning)
    return data.choices[0].delta.reasoning;
  if (data.delta?.type === "thinking_delta") return data.delta.thinking || "";
  if (data.delta?.thinking) return data.delta.thinking;
  return "";
}

async function readStream(response: Response, msgIndex: number) {
  const reader = response.body?.getReader();
  if (!reader) return;

  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const chunks = buffer.split("\n\n");
    buffer = chunks.pop() || "";

    for (const chunk of chunks) {
      const dataLines = chunk
        .split("\n")
        .filter((line) => line.startsWith("data:"))
        .map((line) => line.replace(/^data:\s*/, ""));

      for (const line of dataLines) {
        if (!line || line === "[DONE]") continue;
        try {
          const parsed = JSON.parse(line);
          const contentDelta = extractStreamContent(parsed);
          const thinkingDelta = extractStreamThinking(parsed);
          if (thinkingDelta) messages.value[msgIndex].thinking += thinkingDelta;
          if (contentDelta) messages.value[msgIndex].content += contentDelta;
        } catch {
          messages.value[msgIndex].content += line;
        }
      }
    }
  }
}

async function sendMessage() {
  if (!canSend.value || sending.value) return;

  const userText = input.value.trim();
  let body: Record<string, any>;
  try {
    body = buildRequestBody(userText);
  } catch (error) {
    toast.warning(
      error instanceof Error ? error.message : "自定义参数 JSON 格式错误",
    );
    return;
  }

  const userMessage: ChatMessage = {
    id: nextId(),
    role: "user",
    content: userText,
    thinking: "",
  };
  const assistantMessage: ChatMessage = {
    id: nextId(),
    role: "assistant",
    content: "",
    thinking: "",
  };
  messages.value.push(userMessage, assistantMessage);
  const msgIndex = messages.value.length - 1;
  input.value = "";
  sending.value = true;

  try {
    const response = await authFetch("/api/admin/playground", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ...body,
        _api_type: apiTypeForEndpoint(apiMode.value),
      }),
    });

    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(errorText || `HTTP ${response.status}`);
    }

    if (stream.value === "true") {
      await readStream(response, msgIndex);
    } else {
      const data = await response.json();
      const extracted = extractTextFromResponse(data);
      messages.value[msgIndex].content = extracted.content;
      messages.value[msgIndex].thinking = extracted.thinking;
    }

    if (
      !messages.value[msgIndex].content &&
      !messages.value[msgIndex].thinking
    ) {
      messages.value[msgIndex].content = "[无文本输出]";
    }
  } catch (error) {
    messages.value[msgIndex].role = "error";
    messages.value[msgIndex].content =
      error instanceof Error ? error.message : "请求失败";
  } finally {
    sending.value = false;
  }
}

function clearMessages() {
  messages.value = [];
}

async function load() {
  loading.value = true;
  try {
    const res = await listModels();
    models.value = res.data || [];
    selectedModel.value = models.value[0]?.name || "";
  } catch (error) {
    console.error(error);
    toast.error("模型列表加载失败");
  } finally {
    loading.value = false;
  }
}

onMounted(load);
</script>
