<template>
  <div class="grid min-h-screen place-items-center bg-background px-4 py-10 text-foreground">
    <div class="pointer-events-none fixed inset-0 bg-[radial-gradient(circle_at_top,rgba(0,0,0,0.08),transparent_34%)] dark:bg-[radial-gradient(circle_at_top,rgba(255,255,255,0.12),transparent_34%)]" />
    <UiCard class="relative w-full max-w-[420px] shadow-vercel" padded>
      <div class="mb-7 text-center">
        <div class="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-foreground text-background shadow-sm">
          <Zap class="h-6 w-6" />
        </div>
        <h1 class="text-2xl font-semibold tracking-tight">UniuLink</h1>
        <p class="mt-1 text-sm text-muted-foreground">AI Gateway 管理后台</p>
      </div>

      <form class="space-y-4" @submit.prevent="handleLogin">
        <label class="space-y-2 text-sm font-medium">
          <span>Admin API Key</span>
          <input
            v-model="apiKey"
            type="password"
            placeholder="请输入 Admin API Key"
            class="h-10 w-full rounded-md border border-input bg-background px-3 text-sm outline-none transition focus:ring-2 focus:ring-ring"
          />
        </label>

        <UiButton
          variant="primary"
          native-type="submit"
          :loading="loading"
          block
        >
          {{ loading ? '登录中...' : '登录' }}
        </UiButton>

        <p v-if="error" class="text-center text-sm text-red-600 dark:text-red-400">
          {{ error }}
        </p>
      </form>
    </UiCard>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { Zap } from 'lucide-vue-next'
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
  key: string,
): string {
  const stringToSign = `${method.toUpperCase()}\n${path}\n${timestamp}\n${nonce}\n${bodyHash}`
  return CryptoJS.HmacSHA256(stringToSign, key).toString(CryptoJS.enc.Hex)
}

async function handleLogin() {
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
    const signature = computeSignature('POST', '/api/admin/auth/verify', timestamp, nonce, bodyHash, apiKey.value)

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
