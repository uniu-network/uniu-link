import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem('admin_key') || '')

  const isAuthenticated = computed(() => !!token.value)

  function login(adminKey: string) {
    token.value = adminKey
    localStorage.setItem('admin_key', adminKey)
  }

  function logout() {
    token.value = ''
    localStorage.removeItem('admin_key')
  }

  return { token, isAuthenticated, login, logout }
})
