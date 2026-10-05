<template>
  <div class="login-page">
    <div class="login-theme"><ThemeToggle /></div>
    <UiCard>
      <div class="login-brand">
        <NavIcon name="gateway" :size="30" class="brand-color" />
        <div>
          <h1>UniuLink</h1>
          <p class="secondary-text">AI 网关管理后台</p>
        </div>
      </div>
      <div class="login-intro"><h2>登录控制台</h2><p class="secondary-text">连接模型，管理每一次调用。</p></div>
      <form class="stack" @submit.prevent="handleLogin">
        <UiField label="Admin API Key"
          ><UiInput
            v-model="apiKey"
            type="password"
            autocomplete="current-password"
            placeholder="请输入管理员密钥"
            :disabled="loading"
            required
            class="w-full"
        /></UiField>
        <p v-if="error" role="alert" class="inline-feedback message-symbol-error">
          <NavIcon name="error" />{{ error }}
        </p>
        <UiButton variant="primary" native-type="submit" :loading="loading" block>{{
          loading ? '登录中…' : '登录'
        }}</UiButton>
      </form>
    </UiCard>
    <p class="login-note secondary-text">使用管理员密钥访问网关控制台</p>
  </div>
</template>

<script setup lang="ts">
import UiField from '@/components/ui/UiField.vue'
import UiInput from '@/components/ui/UiInput.vue'
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import NavIcon from '@/components/NavIcon.vue'
import ThemeToggle from '@/components/ThemeToggle.vue'
import { useAuthStore } from '@/stores/auth'
import CryptoJS from 'crypto-js'
import UiButton from '@/components/ui/UiButton.vue'
import UiCard from '@/components/ui/UiCard.vue'

const router = useRouter()
const authStore = useAuthStore()

const apiKey = ref('')
const loading = ref(false)
const error = ref('')

function generateNonce(): string {
  const arr = new Uint8Array(16)
  crypto.getRandomValues(arr)
  return Array.from(arr, (b) => b.toString(16).padStart(2, '0')).join('')
}

function computeSignature(
  method: string,
  path: string,
  timestamp: string,
  nonce: string,
  bodyHash: string,
  key: string
): string {
  const stringToSign = `${method.toUpperCase()}\n${path}\n${timestamp}\n${nonce}\n${bodyHash}`
  return CryptoJS.HmacSHA256(stringToSign, key).toString(CryptoJS.enc.Hex)
}

async function handleLogin() {
  if (loading.value) return
  if (!apiKey.value.trim()) {
    error.value = '请输入 API Key'
    return
  }
  loading.value = true
  error.value = ''

  try {
    const timestamp = Math.floor(Date.now() / 1000).toString()
    const nonce = generateNonce()
    const bodyHash = CryptoJS.SHA256('').toString(CryptoJS.enc.Hex)
    const signature = computeSignature(
      'POST',
      '/api/admin/auth/verify',
      timestamp,
      nonce,
      bodyHash,
      apiKey.value
    )

    const res = await fetch('/api/admin/auth/verify', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Admin-Timestamp': timestamp,
        'X-Admin-Nonce': nonce,
        'X-Admin-Signature': signature,
      },
    })
    if (res.ok) {
      authStore.login(apiKey.value)
      router.push('/')
    } else {
      error.value = 'API Key 无效'
    }
  } catch {
    error.value = '网络错误，请检查后端服务是否启动'
  } finally {
    loading.value = false
  }
}
</script>
