import axios from 'axios'
import CryptoJS from 'crypto-js'
import { useAuthStore } from '@/stores/auth'

const api = axios.create({
  baseURL: '/api/admin',
  headers: {
    'Content-Type': 'application/json',
  },
})

function generateNonce(): string {
  const arr = new Uint8Array(16)
  crypto.getRandomValues(arr)
  return Array.from(arr, (b) => b.toString(16).padStart(2, '0')).join('')
}

function computeHmacSignature(
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

api.interceptors.request.use((config) => {
  const authStore = useAuthStore()
  if (authStore.token) {
    const timestamp = Math.floor(Date.now() / 1000).toString()
    const nonce = generateNonce()
    const path = '/api/admin' + (config.url || '')

    // 签名必须与实际发出的字节一致，因此这里复刻 axios transformRequest 的序列化规则：
    // undefined 表示不发送 body；null、对象、数字等走 JSON.stringify（null 会变成 'null'）；
    // 字符串先尝试按 JSON 解析，能解析时原样（去空白）发送，否则再 JSON.stringify 一次。
    const raw = config.data
    let serialized = ''
    if (raw !== undefined) {
      if (typeof raw === 'string') {
        try {
          JSON.parse(raw)
          serialized = raw.trim()
        } catch {
          serialized = JSON.stringify(raw)
        }
      } else {
        serialized = JSON.stringify(raw) ?? ''
      }
    }
    const bodyHash = CryptoJS.SHA256(serialized).toString(CryptoJS.enc.Hex)

    const signature = computeHmacSignature(
      config.method?.toUpperCase() || 'GET',
      path,
      timestamp,
      nonce,
      bodyHash,
      authStore.token,
    )

    config.headers['X-Admin-Timestamp'] = timestamp
    config.headers['X-Admin-Nonce'] = nonce
    config.headers['X-Admin-Signature'] = signature
    delete config.headers.Authorization
  }
  return config
})

api.interceptors.response.use(
  (response) => {
    if (response.data && typeof response.data === 'object' && 'is_success_response' in response.data) {
      response.data = response.data.data?.detail_result ?? response.data
    }
    return response
  },
  (error) => {
    if (error.response?.status === 401) {
      const authStore = useAuthStore()
      authStore.logout()
      window.location.href = '/login'
    }
    return Promise.reject(error)
  }
)

export default api
