import { ref, watch } from 'vue'

const STORAGE_KEY = 'theme'

const isDark = ref(localStorage.getItem(STORAGE_KEY) === 'dark')

function applyThemeClass(value: boolean) {
  document.documentElement.classList.toggle('dark', value)
}

applyThemeClass(isDark.value)

watch(isDark, (val) => {
  localStorage.setItem(STORAGE_KEY, val ? 'dark' : 'light')
  applyThemeClass(val)
})

export function useTheme() {
  return {
    isDark,
    toggleTheme() {
      isDark.value = !isDark.value
    },
  }
}
