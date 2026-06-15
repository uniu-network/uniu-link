import CryptoJS from 'crypto-js'
import { useAuthStore } from '@/stores/auth'

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

export async function authFetch(url: string, options: RequestInit = {}): Promise<Response> {
  const authStore = useAuthStore()
  if (!authStore.token) {
    throw new Error('Not authenticated')
  }

  const method = (options.method || 'GET').toUpperCase()
  const bodyStr = options.body ? String(options.body) : ''
  const timestamp = Math.floor(Date.now() / 1000).toString()
  const nonce = generateNonce()
  const bodyHash = CryptoJS.SHA256(bodyStr || '').toString(CryptoJS.enc.Hex)

  const signature = computeHmacSignature(method, url, timestamp, nonce, bodyHash, authStore.token)

  const headers = new Headers(options.headers as Record<string, string> | undefined)
  headers.set('X-Admin-Timestamp', timestamp)
  headers.set('X-Admin-Nonce', nonce)
  headers.set('X-Admin-Signature', signature)
  headers.delete('Authorization')

  return fetch(url, { ...options, headers })
}
