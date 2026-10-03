import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export const useAuthStore = defineStore('auth', () => {
  let savedKey = ''
  try {
    savedKey = localStorage.getItem('admin_key') || ''
  } catch {
    /* Keep the session usable without storage. */
  }
  const token = ref(savedKey)

  const isAuthenticated = computed(() => !!token.value)

  function login(adminKey: string) {
    token.value = adminKey
    try {
      localStorage.setItem('admin_key', adminKey)
    } catch {
      /* The current session remains in memory. */
    }
  }

  function logout() {
    token.value = ''
    try {
      localStorage.removeItem('admin_key')
    } catch {
      /* The in-memory session is already cleared. */
    }
  }

  return { token, isAuthenticated, login, logout }
})
