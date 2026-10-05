import openai from '@lobehub/icons-static-svg/icons/openai.svg'
import claude from '@lobehub/icons-static-svg/icons/claude-color.svg'
import gemini from '@lobehub/icons-static-svg/icons/gemini-color.svg'
import deepseek from '@lobehub/icons-static-svg/icons/deepseek-color.svg'
import qwen from '@lobehub/icons-static-svg/icons/qwen-color.svg'
import kimi from '@lobehub/icons-static-svg/icons/kimi-color.svg'
import minimax from '@lobehub/icons-static-svg/icons/minimax-color.svg'
import zhipu from '@lobehub/icons-static-svg/icons/zhipu-color.svg'
import grok from '@lobehub/icons-static-svg/icons/grok.svg'
import meta from '@lobehub/icons-static-svg/icons/meta-color.svg'
import mistral from '@lobehub/icons-static-svg/icons/mistral-color.svg'
import doubao from '@lobehub/icons-static-svg/icons/doubao-color.svg'
import azure from '@lobehub/icons-static-svg/icons/azure-color.svg'
import google from '@lobehub/icons-static-svg/icons/google-color.svg'

export interface ModelIdentity {
  id: string
  label: string
  icon?: string
  monochrome?: boolean
}

// Static imports keep the icon subset local to the build, with no CDN or React runtime.
const identities: Record<string, ModelIdentity> = {
  openai: { id: 'openai', label: 'OpenAI', icon: openai, monochrome: true },
  claude: { id: 'claude', label: 'Claude', icon: claude },
  gemini: { id: 'gemini', label: 'Gemini', icon: gemini },
  deepseek: { id: 'deepseek', label: 'DeepSeek', icon: deepseek },
  qwen: { id: 'qwen', label: 'Qwen', icon: qwen },
  kimi: { id: 'kimi', label: 'Kimi', icon: kimi },
  minimax: { id: 'minimax', label: 'MiniMax', icon: minimax },
  zhipu: { id: 'zhipu', label: '智谱 GLM', icon: zhipu },
  grok: { id: 'grok', label: 'Grok', icon: grok, monochrome: true },
  meta: { id: 'meta', label: 'Meta Llama', icon: meta },
  mistral: { id: 'mistral', label: 'Mistral', icon: mistral },
  doubao: { id: 'doubao', label: '豆包', icon: doubao },
  azure: { id: 'azure', label: 'Azure', icon: azure },
  google: { id: 'google', label: 'Google', icon: google },
}
const unknown: ModelIdentity = { id: 'unknown', label: '自定义模型' }
export const modelIconOptions = [
  { value: 'auto', label: '自动识别' },
  { value: 'generic', label: '通用图标' },
  ...Object.values(identities).map((item) => ({ value: item.id, label: item.label })),
]
// Recognize a family at a token boundary, not arbitrary substrings (e.g. mygpt).
const families: [RegExp, string][] = [
  [/^(?:gpt|chatgpt|codex|o1|o3|o4|dall-e|sora|whisper|tts|text-embedding)(?:$|[-_.:])/i, 'openai'],
  [/^claude(?:$|[-_.:])/i, 'claude'],
  [/^(?:gemini|gemma|imagen|veo)(?:$|[-_.:])/i, 'gemini'],
  [/^deepseek(?:$|[-_.:])/i, 'deepseek'],
  [/^(?:qwen\d*|qwq|qvq)(?:$|[-_.:])/i, 'qwen'],
  [/^(?:kimi|moonshot)(?:$|[-_.:])/i, 'kimi'],
  [/^(?:minimax|abab\d*)(?:$|[-_.:])/i, 'minimax'],
  [/^(?:glm|chatglm\d*)(?:$|[-_.:])/i, 'zhipu'],
  [/^grok(?:$|[-_.:])/i, 'grok'],
  [/^llama(?:$|[-_.:\d])/i, 'meta'],
  [/^(?:mistral|mixtral|codestral|magistral|ministral)(?:$|[-_.:])/i, 'mistral'],
  [/^(?:doubao|seedream|seedance)(?:$|[-_.:])/i, 'doubao'],
]

function fromName(name: string): ModelIdentity | undefined {
  // Namespace paths such as openrouter/anthropic/claude-sonnet remain recognizable.
  const leaf = name.trim().split('/').pop() || ''
  const match = families.find(([pattern]) => pattern.test(leaf))
  return match ? identities[match[1]] : undefined
}

export function resolveModelIdentity(
  name = '',
  upstreamModels: readonly string[] = [],
  icon = 'auto'
): ModelIdentity {
  if (icon && icon !== 'auto')
    return identities[icon] || { id: 'unknown', label: '通用图标' }
  const direct = fromName(name)
  if (direct) return direct
  // An alias can represent several providers. Only use upstream identity if all agree.
  const upstream = upstreamModels.map(fromName)
  if (upstream.length && upstream[0] && upstream.every((item) => item?.id === upstream[0]?.id))
    return upstream[0]
  return unknown
}

export interface ModelPresentation {
  name: string
  icon?: string
  channel_refs?: { upstream_model_id?: string }[]
}

export function upstreamModelNames(model?: ModelPresentation): string[] {
  return (model?.channel_refs || []).map((ref) => ref.upstream_model_id || '')
}

export function resolveProviderIdentity(provider = ''): ModelIdentity {
  const key = provider.toLowerCase()
  if (key === 'anthropic') return { ...identities.claude, label: 'Anthropic' }
  return identities[key] || { id: 'unknown', label: provider === 'custom' ? '自定义渠道' : provider || '未知提供商' }
}
